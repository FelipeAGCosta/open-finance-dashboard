"""Regras da sincronização: idempotência, PENDING, histórico, fotos diárias e falhas."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from conftest import (
    BANK_ID,
    CARD_ID,
    DAY1,
    DAY2,
    ITEM_ID,
    ITEMS,
    PENDING_REMOVED_ID,
    PENDING_REPLACED_ID,
    REPLACEMENT_ID,
    FakeSource,
    dump_tables,
    scenario,
)
from findash.db import queries
from findash.db.models import (
    Account,
    AccountSnapshot,
    InvestmentSnapshot,
    InvestmentTransaction,
    ItemStatus,
    SyncRun,
    Transaction,
)
from findash.pluggy.errors import PluggyAuthError, PluggyServerError
from findash.sync.service import EXIT_API, EXIT_AUTH, OVERLAP_DAYS, SyncFailed, run_sync


def sync(session_factory, redactor, data, when, **kwargs):
    source = data if isinstance(data, FakeSource) else FakeSource(data)
    return run_sync(session_factory, source, ITEMS, redactor=redactor, clock=lambda: when, **kwargs)


def count(session_factory, model) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- idempotência


def test_first_sync_loads_everything(session_factory, redactor):
    result = sync(session_factory, redactor, scenario(1), DAY1)
    stats = result.stats
    assert stats.accounts_seen == 2
    assert stats.transactions_new == 10  # 4 conta + 4 cartão + 2 PENDING
    assert stats.investments_new == 4
    assert stats.snapshots_created == 4
    assert stats.investment_transactions_new == 4
    with session_factory() as session:
        run = session.get(SyncRun, result.run_id)
        assert run.status == "success" and run.transactions_new == 10 and run.error_message is None


def test_sync_twice_is_idempotent(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    before = dump_tables(session_factory)

    second = sync(session_factory, redactor, scenario(1), DAY1 + timedelta(minutes=5)).stats

    assert (second.transactions_new, second.transactions_updated) == (0, 0)
    assert (second.transactions_replaced, second.transactions_removed) == (0, 0)
    assert second.transactions_unchanged == 10
    assert (second.investments_new, second.investments_updated) == (0, 0)
    assert (second.snapshots_created, second.snapshots_updated) == (0, 4)  # mesma foto do dia, regravada
    assert (second.investment_transactions_new, second.investment_transactions_updated) == (0, 0)
    assert dump_tables(session_factory) == before


def test_ten_runs_never_duplicate(session_factory, redactor):
    for minute in range(10):
        sync(session_factory, redactor, scenario(1), DAY1 + timedelta(minutes=minute))
    assert count(session_factory, Transaction) == 10
    assert count(session_factory, Account) == 2
    assert count(session_factory, InvestmentSnapshot) == 4
    assert count(session_factory, InvestmentTransaction) == 4
    assert count(session_factory, ItemStatus) == 1
    assert count(session_factory, SyncRun) == 10


def test_first_seen_is_kept_and_last_seen_moves(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    later = DAY1 + timedelta(hours=1)
    sync(session_factory, redactor, scenario(1), later)
    with session_factory() as session:
        tx = session.get(Transaction, "00000000-0000-4000-8000-0000000000b1")
        assert tx.first_seen_at == DAY1 and tx.last_seen_at == later


def test_changed_transaction_is_updated_in_place(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    data = scenario(1)
    data["transactions"][BANK_ID][0]["category"] = "Outra categoria"
    stats = sync(session_factory, redactor, data, DAY1 + timedelta(hours=1)).stats
    assert stats.transactions_updated == 1 and stats.transactions_new == 0
    with session_factory() as session:
        assert session.get(Transaction, "00000000-0000-4000-8000-0000000000b1").category_pluggy == "Outra categoria"
    assert count(session_factory, Transaction) == 10


# ---------------------------------------------------------------- valores normalizados


def test_stored_amounts_follow_single_sign_convention(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    with session_factory() as session:
        amounts = {
            t.id[-2:]: (t.amount_original_cents, t.amount_normalized_cents)
            for t in session.scalars(select(Transaction))
        }
        assert amounts["b1"] == (-5000, -5000)  # Pix enviado: saída
        assert amounts["b2"] == (150000, 150000)  # Pix recebido: entrada
        assert amounts["d1"] == (8990, -8990)  # compra no cartão: veio positiva, vira negativa
        assert amounts["d2"] == (-50000, 50000)  # pagamento da fatura: veio negativo, vira positivo
        assert amounts["d3"] == (1000, -5520)  # USD: original em dólar, normalizado em reais
        installment = session.get(Transaction, "00000000-0000-4000-8000-0000000000d4")
        assert (installment.installment_number, installment.total_installments) == (2, 3)
        assert installment.purchase_date == date(2025, 11, 20)
        assert installment.mcc == 5732
        late_night = session.get(Transaction, "00000000-0000-4000-8000-0000000000b3")
        assert late_night.date == date(2026, 1, 6)  # 02:38Z = 23:38 do dia anterior em Brasília
        assert late_night.merchant_name == "Padaria Exemplo"


# ---------------------------------------------------------------- PENDING


def test_pending_replaced_or_removed_is_kept_but_not_counted(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    with session_factory() as session:
        total_day1 = queries.active_total_cents(session, CARD_ID, date(2026, 1, 1), date(2026, 1, 31))
    # dia 1: d1 -89,90; d2 +500; d3 -55,20; d4 -100; e1 -45; e2 -19,90
    assert total_day1 == -8990 + 50000 - 5520 - 10000 - 4500 - 1990

    stats = sync(session_factory, redactor, scenario(2), DAY2).stats
    assert stats.transactions_new == 1  # d5 (a confirmação de e1, com outro id)
    assert stats.transactions_replaced == 1
    assert stats.transactions_removed == 1

    with session_factory() as session:
        replaced = session.get(Transaction, PENDING_REPLACED_ID)
        removed = session.get(Transaction, PENDING_REMOVED_ID)
        assert (replaced.state, replaced.replaced_by_id, replaced.state_changed_at) == (
            "substituida",
            REPLACEMENT_ID,
            DAY2,
        )
        assert (removed.state, removed.replaced_by_id) == ("removida", None)
        assert session.get(Transaction, REPLACEMENT_ID).state == "ativa"
        # nada apagado: 10 do dia 1 + d5
        assert session.scalar(select(func.count()).select_from(Transaction)) == 11
        total_day2 = queries.active_total_cents(session, CARD_ID, date(2026, 1, 1), date(2026, 1, 31))
    # e1 sai e d5 entra (mesmo valor); e2 deixa de contar
    assert total_day2 == total_day1 + 1990

    again = sync(session_factory, redactor, scenario(2), DAY2 + timedelta(hours=1)).stats
    assert (again.transactions_new, again.transactions_replaced, again.transactions_removed) == (0, 0, 0)


def test_pending_confirmed_with_same_id_just_changes_status(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    data = scenario(1)
    for tx in data["transactions"][CARD_ID]:
        tx["status"] = "POSTED"
    stats = sync(session_factory, redactor, data, DAY2).stats
    assert stats.transactions_updated == 2
    assert (stats.transactions_replaced, stats.transactions_removed) == (0, 0)
    with session_factory() as session:
        assert session.get(Transaction, PENDING_REPLACED_ID).status == "POSTED"


def test_removed_pending_that_reappears_is_reactivated(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    sync(session_factory, redactor, scenario(2), DAY2)
    data = scenario(2)
    data["transactions"][CARD_ID] += [t for t in scenario(1)["transactions"][CARD_ID] if t["id"] == PENDING_REMOVED_ID]
    sync(session_factory, redactor, data, DAY2 + timedelta(hours=2))
    with session_factory() as session:
        tx = session.get(Transaction, PENDING_REMOVED_ID)
        assert (tx.state, tx.replaced_by_id) == ("ativa", None)


# ---------------------------------------------------------------- histórico e janela incremental


def test_history_outside_pluggy_window_is_never_deleted(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    # Um ano depois a Pluggy não devolve mais nada destas contas (fora da janela de 12 meses).
    data = scenario(1)
    data["transactions"] = {BANK_ID: [], CARD_ID: []}
    data["investment_transactions"] = {}
    stats = sync(session_factory, redactor, data, DAY1 + timedelta(days=400)).stats
    assert stats.transactions_new == 0
    assert count(session_factory, Transaction) == 10
    with session_factory() as session:
        posted_states = set(session.scalars(select(Transaction.state).where(Transaction.status == "POSTED")))
    assert posted_states == {"ativa"}


def test_first_sync_reads_full_history_then_incremental(session_factory, redactor):
    first = FakeSource(scenario(1))
    sync(session_factory, redactor, first, DAY1)
    assert all(date_from is None for _, _, date_from in first.calls)

    second = FakeSource(scenario(1))
    sync(session_factory, redactor, second, DAY1 + timedelta(days=1))
    windows = {(kind, key): date_from for kind, key, date_from in second.calls}
    expected = date(2026, 1, 11) - timedelta(days=OVERLAP_DAYS)
    assert windows[("transactions", BANK_ID)] == expected
    # cartão com PENDING abertas desde 2026-01-09: a janela já cobre (60 dias > 5 dias de folga)
    assert windows[("transactions", CARD_ID)] == expected
    assert windows[("investment_transactions", "00000000-0000-4000-8000-000000000101")] == expected
    # investimento sem nenhuma transação conhecida continua lendo tudo
    assert windows[("investment_transactions", "00000000-0000-4000-8000-000000000103")] is None

    full = FakeSource(scenario(1))
    sync(session_factory, redactor, full, DAY1 + timedelta(days=1), full=True)
    assert all(date_from is None for _, _, date_from in full.calls)


def test_window_widens_to_cover_old_open_pending(session_factory, redactor):
    data = scenario(1)
    old_pending = data["transactions"][CARD_ID][-1]
    old_pending["date"] = "2025-10-01T03:00:00.000Z"
    sync(session_factory, redactor, data, DAY1)
    source = FakeSource(scenario(1))
    sync(session_factory, redactor, source, DAY2)
    windows = {key: date_from for kind, key, date_from in source.calls if kind == "transactions"}
    assert windows[CARD_ID] == date(2025, 10, 1) - timedelta(days=5)


# ---------------------------------------------------------------- fotos da carteira


def test_snapshot_is_unique_per_day_and_updated_on_rerun(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    data = scenario(1)
    data["investments"][0].update({"value": 102.0, "balance": 1020.0})
    stats = sync(session_factory, redactor, data, DAY1 + timedelta(hours=3)).stats
    assert (stats.snapshots_created, stats.snapshots_updated) == (0, 4)
    with session_factory() as session:
        rows = session.scalars(
            select(InvestmentSnapshot).where(InvestmentSnapshot.investment_id == "00000000-0000-4000-8000-000000000101")
        ).all()
        assert len(rows) == 1
        assert rows[0].balance_cents == 102000 and rows[0].snapshot_date == date(2026, 1, 10)

    stats = sync(session_factory, redactor, scenario(2), DAY2).stats
    assert (stats.snapshots_created, stats.snapshots_updated) == (4, 0)
    assert count(session_factory, InvestmentSnapshot) == 8
    with session_factory() as session:
        latest = queries.latest_snapshot_date(session)
        groups = {(g.type, g.subtype): g for g in queries.portfolio_by_class(session, latest)}
    assert latest == date(2026, 1, 11)
    assert groups[("EQUITY", "REAL_ESTATE_FUND")].balance_cents == 101000
    assert ("FIXED_INCOME", "CDB") not in groups  # posição encerrada (saldo zero) fica fora da carteira


def test_snapshot_uniqueness_is_enforced_by_the_database(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    with session_factory() as session:
        session.add(
            InvestmentSnapshot(
                snapshot_date=date(2026, 1, 10), investment_id="00000000-0000-4000-8000-000000000101", captured_at=DAY1
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_snapshot_date_uses_brasilia_time(session_factory, redactor):
    late_night_utc = datetime(2026, 1, 11, 1, 30)  # 22:30 de 10/01 em Brasília
    sync(session_factory, redactor, scenario(1), late_night_utc)
    with session_factory() as session:
        assert set(session.scalars(select(InvestmentSnapshot.snapshot_date))) == {date(2026, 1, 10)}


def test_account_snapshots_one_per_day(session_factory, redactor):
    first = sync(session_factory, redactor, scenario(1), DAY1).stats
    assert (first.account_snapshots_created, first.account_snapshots_updated) == (2, 0)
    data = scenario(1)
    data["accounts"][0]["balance"] = 999.99
    rerun = sync(session_factory, redactor, data, DAY1 + timedelta(hours=8)).stats
    assert (rerun.account_snapshots_created, rerun.account_snapshots_updated) == (0, 2)
    with session_factory() as session:
        rows = session.scalars(select(AccountSnapshot).order_by(AccountSnapshot.account_id)).all()
        assert len(rows) == 2
        bank, card = rows
        assert bank.balance_cents == 99999 and bank.snapshot_date == date(2026, 1, 10)
        assert (card.balance_cents, card.credit_limit_cents, card.available_credit_limit_cents) == (
            43210,
            500000,
            456790,
        )
    sync(session_factory, redactor, scenario(2), DAY2)
    assert count(session_factory, AccountSnapshot) == 4
    with session_factory() as session:
        session.add(AccountSnapshot(snapshot_date=date(2026, 1, 11), account_id=BANK_ID, captured_at=DAY2))
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------- item e consentimento


def test_item_status_updated_and_consent_warning(session_factory, redactor):
    data = scenario(1)
    data["item"]["consentExpiresAt"] = "2026-01-30T10:00:00.000Z"  # 19 dias depois de DAY1
    result = sync(session_factory, redactor, data, DAY1)
    assert any("expira em 19 dia(s)" in w for w in result.stats.warnings)
    with session_factory() as session:
        item = session.get(ItemStatus, ITEM_ID)
        assert item.consent_expires_at == datetime(2026, 1, 30, 10, 0)
        assert item.connector_name == "MeuPluggy" and item.checked_at == DAY1
        assert "expira em 19 dia(s)" in session.get(SyncRun, result.run_id).warnings


def test_no_consent_warning_when_far_from_expiry(session_factory, redactor):
    assert sync(session_factory, redactor, scenario(1), DAY1).stats.warnings == []


# ---------------------------------------------------------------- falhas


class FailingSource(FakeSource):
    def __init__(self, data, error):
        super().__init__(data)
        self.error = error

    def list_investments(self, item_id):
        raise self.error


def test_auth_failure_is_recorded_and_database_untouched(session_factory, redactor):
    sync(session_factory, redactor, scenario(1), DAY1)
    before = dump_tables(session_factory, skip=("sync_runs", "item_status"))
    error = PluggyAuthError("Autenticação recusada pela Pluggy (HTTP 401) em POST /auth", status=401)
    with pytest.raises(SyncFailed) as caught:
        sync(session_factory, redactor, FailingSource(scenario(2), error), DAY2)
    assert caught.value.exit_code == EXIT_AUTH
    with session_factory() as session:
        run = session.get(SyncRun, caught.value.run_id)
        assert run.status == "error" and "HTTP 401" in run.error_message and run.finished_at == DAY2
    # a falha no meio da busca não aplica nada do dia 2 (nem a transação nova, nem as substituições)
    assert dump_tables(session_factory, skip=("sync_runs", "item_status")) == before


def test_server_failure_maps_to_api_exit_code(session_factory, redactor):
    with pytest.raises(SyncFailed) as caught:
        sync(session_factory, redactor, FailingSource(scenario(1), PluggyServerError("HTTP 503", status=503)), DAY1)
    assert caught.value.exit_code == EXIT_API
    assert count(session_factory, Transaction) == 0
