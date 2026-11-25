"""Sincronização com a Pluggy.

Fluxo de uma execução:
1. registra um sync_run 'running' (commit próprio, para sobreviver a falhas);
2. busca TUDO na Pluggy, de cada item configurado (item, contas, transações, investimentos e as
   transações de investimentos);
3. aplica no banco numa única transação: ou tudo entra, ou nada muda. Buscar antes de gravar é o que
   permite isso: uma falha de rede no meio da busca não deixa o banco pela metade;
4. fecha o sync_run com contagens (sucesso) ou com a mensagem de erro mascarada (falha).

Regras:
- upsert sempre pelo id da Pluggy: rodar N vezes seguidas não duplica nada;
- nada é apagado: o que sai da janela de 12 meses da Pluggy continua no banco;
- PENDING que some da API vira 'substituida' (achamos a versão confirmada, com outro id)
  ou 'removida' (cancelada); nos dois casos deixa de contar nos totais;
- uma foto da carteira por dia e por ativo; nova execução no mesmo dia atualiza a foto;
- primeira execução de cada conta/ativo: histórico completo; depois, janela incremental
  de OVERLAP_DAYS dias (ampliada para cobrir as PENDING ainda abertas). `full=True` força tudo.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from findash.config import ItemConfig, local_date, to_utc_naive, utcnow
from findash.db.models import (
    STATE_ACTIVE,
    STATE_REMOVED,
    STATE_REPLACED,
    Account,
    AccountSnapshot,
    Investment,
    InvestmentSnapshot,
    InvestmentTransaction,
    ItemStatus,
    SyncRun,
    Transaction,
)
from findash.pluggy.errors import PluggyAuthError, PluggyError
from findash.pluggy.models import (
    PluggyAccount,
    PluggyInvestment,
    PluggyInvestmentTransaction,
    PluggyItem,
    PluggyTransaction,
)
from findash.security import Redactor
from findash.sync.normalize import credit_limits, normalized_amount_cents, pluggy_date, to_cents

OVERLAP_DAYS = 60
PENDING_LOOKBACK_DAYS = 5
CONSENT_WARNING_DAYS = 30
REPLACEMENT_DAYS_BEFORE = 5
REPLACEMENT_DAYS_AFTER = 15
FUZZY_AMOUNT_TOLERANCE = Decimal("0.15")  # PENDING em moeda estrangeira muda de valor ao confirmar
_IN_CHUNK = 500

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_API = 3

log = logging.getLogger(__name__)


class PluggySource(Protocol):
    """O que a sincronização precisa da Pluggy (o PluggyClient real ou um falso nos testes)."""

    def get_item(self, item_id: str) -> dict[str, Any]: ...
    def list_accounts(self, item_id: str) -> list[dict[str, Any]]: ...
    def list_transactions(self, account_id: str, date_from: date | None = None) -> list[dict[str, Any]]: ...
    def list_investments(self, item_id: str) -> list[dict[str, Any]]: ...
    def list_investment_transactions(
        self, investment_id: str, date_from: date | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass
class SyncStats:
    accounts_seen: int = 0
    transactions_new: int = 0
    transactions_updated: int = 0
    transactions_unchanged: int = 0
    transactions_replaced: int = 0
    transactions_removed: int = 0
    investments_new: int = 0
    investments_updated: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    investment_transactions_new: int = 0
    investment_transactions_updated: int = 0
    account_snapshots_created: int = 0
    account_snapshots_updated: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    run_id: int
    stats: SyncStats
    started_at: datetime
    finished_at: datetime


class SyncFailed(Exception):
    def __init__(self, message: str, *, exit_code: int, run_id: int | None):
        super().__init__(message)
        self.exit_code = exit_code
        self.run_id = run_id


@dataclass
class _Fetched:
    institution: str
    item: dict[str, Any]
    accounts: list[dict[str, Any]]
    transactions: dict[str, list[dict[str, Any]]]
    windows: dict[str, date | None]
    investments: list[dict[str, Any]]
    investment_transactions: dict[str, list[dict[str, Any]]]


# ====================================================================== orquestração


def run_sync(
    session_factory: sessionmaker,
    source: PluggySource,
    items: Sequence[ItemConfig],
    *,
    redactor: Redactor,
    full: bool = False,
    clock: Callable[[], datetime] = utcnow,
) -> SyncResult:
    started = clock()
    with session_factory() as session:
        run = SyncRun(started_at=started, status="running", full_sync=full)
        session.add(run)
        session.commit()
        run_id = run.id

    try:
        with session_factory() as session:
            today = local_date(started)
            fetched = [_fetch(source, session, item, today=today, full=full) for item in items]
            stats = SyncStats()
            for one in fetched:
                _apply(session, one, stats, now=started, today=today, redactor=redactor)
            run = session.get(SyncRun, run_id)
            _fill_run(run, stats)
            run.status = "success"
            run.finished_at = clock()
            session.commit()
            finished = run.finished_at
    except PluggyError as exc:
        message = redactor(str(exc))
        _mark_failed(session_factory, run_id, message, clock)
        raise SyncFailed(
            message, exit_code=EXIT_AUTH if isinstance(exc, PluggyAuthError) else EXIT_API, run_id=run_id
        ) from None
    except Exception as exc:
        message = redactor(f"{type(exc).__name__}: {exc}")
        _mark_failed(session_factory, run_id, message, clock)
        raise SyncFailed(message, exit_code=EXIT_ERROR, run_id=run_id) from exc

    for warning in stats.warnings:
        log.warning(warning)
    return SyncResult(run_id=run_id, stats=stats, started_at=started, finished_at=finished)


def _mark_failed(session_factory: sessionmaker, run_id: int, message: str, clock: Callable[[], datetime]) -> None:
    log.error("Sincronização %s falhou: %s", run_id, message)
    with session_factory() as session:
        run = session.get(SyncRun, run_id)
        run.status = "error"
        run.error_message = message
        run.finished_at = clock()
        session.commit()


def _fill_run(run: SyncRun, stats: SyncStats) -> None:
    for name in (
        "accounts_seen",
        "transactions_new",
        "transactions_updated",
        "transactions_replaced",
        "transactions_removed",
        "investments_new",
        "investments_updated",
        "snapshots_created",
        "snapshots_updated",
        "investment_transactions_new",
        "investment_transactions_updated",
    ):
        setattr(run, name, getattr(stats, name))
    run.warnings = "\n".join(stats.warnings) or None


# ====================================================================== busca


def _fetch(source: PluggySource, session: Session, config: ItemConfig, *, today: date, full: bool) -> _Fetched:
    item_id = config.id
    item = source.get_item(item_id)
    accounts = source.list_accounts(item_id)
    transactions: dict[str, list[dict[str, Any]]] = {}
    windows: dict[str, date | None] = {}
    for account in accounts:
        window = None if full else _transaction_window(session, account["id"], today)
        windows[account["id"]] = window
        log.info("Transações da conta %s… desde %s", account.get("subtype"), window or "o início")
        transactions[account["id"]] = source.list_transactions(account["id"], window)
    investments = source.list_investments(item_id)
    investment_transactions: dict[str, list[dict[str, Any]]] = {}
    for investment in investments:
        window = None if full else _investment_window(session, investment["id"], today)
        investment_transactions[investment["id"]] = source.list_investment_transactions(investment["id"], window)
    return _Fetched(config.institution, item, accounts, transactions, windows, investments, investment_transactions)


def _transaction_window(session: Session, account_id: str, today: date) -> date | None:
    known = session.scalar(select(Transaction.id).where(Transaction.account_id == account_id).limit(1))
    if known is None:
        return None  # conta nova: todo o histórico disponível
    window = today - timedelta(days=OVERLAP_DAYS)
    oldest_pending = session.scalar(
        select(func.min(Transaction.date)).where(
            Transaction.account_id == account_id,
            Transaction.status == "PENDING",
            Transaction.state == STATE_ACTIVE,
        )
    )
    if oldest_pending is not None:
        window = min(window, oldest_pending - timedelta(days=PENDING_LOOKBACK_DAYS))
    return window


def _investment_window(session: Session, investment_id: str, today: date) -> date | None:
    known = session.scalar(
        select(InvestmentTransaction.id).where(InvestmentTransaction.investment_id == investment_id).limit(1)
    )
    return None if known is None else today - timedelta(days=OVERLAP_DAYS)


# ====================================================================== aplicação


def _apply(
    session: Session, fetched: _Fetched, stats: SyncStats, *, now: datetime, today: date, redactor: Redactor
) -> None:
    # Limpa segredos de TODO o payload antes de mapear: vale para raw_json e para colunas derivadas.
    fetched = _Fetched(
        institution=fetched.institution,
        item=_scrub(fetched.item, redactor),
        accounts=_scrub(fetched.accounts, redactor),
        transactions=_scrub(fetched.transactions, redactor),
        windows=fetched.windows,
        investments=_scrub(fetched.investments, redactor),
        investment_transactions=_scrub(fetched.investment_transactions, redactor),
    )
    _apply_item(session, fetched.item, now=now, stats=stats)

    account_types: dict[str, str] = {}
    _prefetch(session, Account, [a["id"] for a in fetched.accounts])
    for raw in fetched.accounts:
        account = PluggyAccount.model_validate(raw)
        account_types[account.id] = account.type
        limit, available = credit_limits(account.credit_data)
        _upsert(
            session,
            Account,
            account.id,
            now,
            {
                "item_id": fetched.item.get("id"),
                "institution": fetched.institution,
                "type": account.type,
                "subtype": account.subtype,
                "name": account.name,
                "marketing_name": account.marketing_name,
                "number": account.number,
                "currency_code": account.currency_code,
                "balance_cents": to_cents(account.balance),
                "credit_limit_cents": limit,
                "available_credit_limit_cents": available,
                "raw_json": _canonical(raw, redactor),
                "pluggy_updated_at": to_utc_naive(account.updated_at),
            },
        )
        stats.accounts_seen += 1
        session.flush()
        _upsert_account_snapshot(
            session,
            account.id,
            today=today,
            now=now,
            stats=stats,
            values={
                "balance_cents": to_cents(account.balance),
                "credit_limit_cents": limit,
                "available_credit_limit_cents": available,
            },
        )
    session.flush()

    for account_id, raws in fetched.transactions.items():
        _apply_transactions(
            session, account_id, account_types[account_id], raws, now=now, redactor=redactor, stats=stats
        )
        returned = {raw["id"] for raw in raws}
        _resolve_missing_pendings(session, account_id, returned, fetched.windows.get(account_id), now=now, stats=stats)

    _prefetch(session, Investment, [i["id"] for i in fetched.investments])
    for raw in fetched.investments:
        _apply_investment(
            session,
            raw,
            now=now,
            today=today,
            redactor=redactor,
            stats=stats,
            item_id=fetched.item.get("id"),
            institution=fetched.institution,
        )
    session.flush()

    for investment_id, raws in fetched.investment_transactions.items():
        _prefetch(session, InvestmentTransaction, [r["id"] for r in raws])
        for raw in raws:
            tx = PluggyInvestmentTransaction.model_validate(raw)
            outcome = _upsert(
                session,
                InvestmentTransaction,
                tx.id,
                now,
                {
                    "investment_id": investment_id,
                    "date": pluggy_date(tx.date),
                    "trade_date": pluggy_date(tx.trade_date),
                    "type": tx.type,
                    "movement_type": tx.movement_type,
                    "quantity": tx.quantity,
                    "unit_value": tx.value,
                    "amount_cents": to_cents(tx.amount),
                    "net_amount_cents": to_cents(tx.net_amount),
                    "description": tx.description,
                    "raw_json": _canonical(raw, redactor),
                },
            )
            if outcome == "new":
                stats.investment_transactions_new += 1
            elif outcome == "updated":
                stats.investment_transactions_updated += 1
    session.flush()


def _upsert_account_snapshot(
    session: Session, account_id: str, *, today: date, now: datetime, stats: SyncStats, values: dict[str, Any]
) -> None:
    """Uma foto por dia e por conta; nova execução no mesmo dia atualiza a foto."""
    snapshot = session.scalar(
        select(AccountSnapshot).where(AccountSnapshot.snapshot_date == today, AccountSnapshot.account_id == account_id)
    )
    if snapshot is None:
        session.add(AccountSnapshot(snapshot_date=today, account_id=account_id, captured_at=now, **values))
        stats.account_snapshots_created += 1
    else:
        for key, value in values.items():
            setattr(snapshot, key, value)
        snapshot.captured_at = now
        stats.account_snapshots_updated += 1


def _apply_item(session: Session, raw: dict[str, Any], *, now: datetime, stats: SyncStats) -> None:
    item = PluggyItem.model_validate(raw)
    status = session.get(ItemStatus, item.id) or ItemStatus(item_id=item.id)
    status.connector_name = (item.connector or {}).get("name")
    status.status = item.status
    status.execution_status = item.execution_status
    status.pluggy_last_updated_at = to_utc_naive(item.last_updated_at)
    status.next_auto_sync_at = to_utc_naive(item.next_auto_sync_at)
    status.consent_expires_at = to_utc_naive(item.consent_expires_at)
    status.error_json = item.error
    status.checked_at = now
    session.add(status)

    if item.status and item.status != "UPDATED":
        stats.warnings.append(f"Item da Pluggy com status {item.status} (execução: {item.execution_status}).")
    warning = consent_warning(status.consent_expires_at, now)
    if warning:
        stats.warnings.append(warning)


STALE_AFTER = timedelta(hours=36)  # a Pluggy atualiza 1× por dia: mais que isso, ela pulou uma atualização


def stale_hours(last_updated_at: datetime | None, now: datetime) -> int | None:
    """Horas desde a última atualização do dado na Pluggy quando passa de 36 h; None se está em dia."""
    if last_updated_at is None:
        return None
    age = now - last_updated_at
    return int(age.total_seconds() // 3600) if age > STALE_AFTER else None


def consent_warning(expires_at: datetime | None, now: datetime) -> str | None:
    if expires_at is None:
        return None
    remaining = expires_at - now
    if remaining <= timedelta(0):
        return (
            f"AVISO: o consentimento do MeuPluggy EXPIROU em {expires_at:%Y-%m-%d}. "
            "Renove a autorização no Pluggy Dashboard (Demo > Connect Account > MeuPluggy)."
        )
    if remaining < timedelta(days=CONSENT_WARNING_DAYS):
        return (
            f"AVISO: o consentimento do MeuPluggy expira em {remaining.days} dia(s), em {expires_at:%Y-%m-%d}. "
            "Renove a autorização no Pluggy Dashboard (Demo > Connect Account > MeuPluggy)."
        )
    return None


def _apply_transactions(
    session: Session,
    account_id: str,
    account_type: str,
    raws: list[dict[str, Any]],
    *,
    now: datetime,
    redactor: Redactor,
    stats: SyncStats,
) -> None:
    _prefetch(session, Transaction, [r["id"] for r in raws])
    for raw in raws:
        tx = PluggyTransaction.model_validate(raw)
        card = tx.credit_card_metadata or {}
        merchant = tx.merchant or {}
        values = {
            "account_id": account_id,
            "date": pluggy_date(tx.date),
            "occurred_at": to_utc_naive(tx.date),
            "description": tx.description,
            "description_raw": tx.description_raw,
            "amount_original_cents": to_cents(tx.amount),
            "currency_code": tx.currency_code,
            "amount_in_account_currency_cents": to_cents(tx.amount_in_account_currency),
            "amount_normalized_cents": normalized_amount_cents(tx, account_type),
            "type": tx.type,
            "status": tx.status or "POSTED",
            "operation_type": tx.operation_type,
            "merchant_name": merchant.get("name") or merchant.get("businessName"),
            "merchant_cnpj": merchant.get("cnpj"),
            "merchant_json": tx.merchant,
            "payment_data_json": tx.payment_data,
            "mcc": _int_or_none(card.get("payeeMCC")),
            "installment_number": _int_or_none(card.get("installmentNumber")),
            "total_installments": _int_or_none(card.get("totalInstallments")),
            "bill_id": card.get("billId"),
            "purchase_date": pluggy_date(_parse_dt(card.get("purchaseDate"))),
            "category_pluggy": tx.category,
            "category_id_pluggy": tx.category_id,
            "raw_json": _canonical(raw, redactor),
            "pluggy_created_at": to_utc_naive(tx.created_at),
            "pluggy_updated_at": to_utc_naive(tx.updated_at),
        }
        existing = session.get(Transaction, tx.id)
        reactivated = existing is not None and existing.state != STATE_ACTIVE
        outcome = _upsert(session, Transaction, tx.id, now, values)
        if reactivated:
            existing.state = STATE_ACTIVE
            existing.replaced_by_id = None
            existing.state_changed_at = now
            outcome = "updated"
            log.info("Transação %s voltou a aparecer na Pluggy e foi reativada.", tx.id)
        if outcome == "new":
            stats.transactions_new += 1
        elif outcome == "updated":
            stats.transactions_updated += 1
        else:
            stats.transactions_unchanged += 1
    session.flush()


def _resolve_missing_pendings(
    session: Session, account_id: str, returned_ids: set[str], window: date | None, *, now: datetime, stats: SyncStats
) -> None:
    query = select(Transaction).where(
        Transaction.account_id == account_id,
        Transaction.status == "PENDING",
        Transaction.state == STATE_ACTIVE,
    )
    if window is not None:
        # Só dá para afirmar que sumiu se a data estava dentro da janela consultada.
        query = query.where(Transaction.date > window)
    missing = [tx for tx in session.scalars(query) if tx.id not in returned_ids]
    if not missing:
        return
    used = set(session.scalars(select(Transaction.replaced_by_id).where(Transaction.replaced_by_id.is_not(None))))
    for pending in sorted(missing, key=lambda t: (t.date, t.id)):
        replacement = _find_replacement(session, pending, used)
        pending.state_changed_at = now
        if replacement is not None:
            pending.state = STATE_REPLACED
            pending.replaced_by_id = replacement.id
            used.add(replacement.id)
            stats.transactions_replaced += 1
            log.info("PENDING %s substituída por %s.", pending.id, replacement.id)
        else:
            pending.state = STATE_REMOVED
            stats.transactions_removed += 1
            log.info("PENDING %s não voltou da Pluggy e não tem substituta: marcada como removida.", pending.id)
    session.flush()


def _find_replacement(session: Session, pending: Transaction, used: set[str]) -> Transaction | None:
    candidates = [
        tx
        for tx in session.scalars(
            select(Transaction).where(
                Transaction.account_id == pending.account_id,
                Transaction.id != pending.id,
                Transaction.state == STATE_ACTIVE,
                Transaction.status == "POSTED",
                Transaction.date >= pending.date - timedelta(days=REPLACEMENT_DAYS_BEFORE),
                Transaction.date <= pending.date + timedelta(days=REPLACEMENT_DAYS_AFTER),
                Transaction.first_seen_at >= pending.first_seen_at,
            )
        )
        if tx.id not in used
    ]
    if not candidates:
        return None
    description = _norm_text(pending.description)

    def rank(tx: Transaction) -> tuple:
        same_description = bool(description) and _norm_text(tx.description) == description
        return (not same_description, abs((tx.date - pending.date).days), tx.id)

    exact = [tx for tx in candidates if tx.amount_normalized_cents == pending.amount_normalized_cents]
    if exact:
        return min(exact, key=rank)
    close = [
        tx
        for tx in candidates
        if description and _norm_text(tx.description) == description and _amount_close(tx, pending)
    ]
    return min(close, key=rank) if close else None


def _apply_investment(
    session: Session,
    raw: dict[str, Any],
    *,
    now: datetime,
    today: date,
    redactor: Redactor,
    stats: SyncStats,
    item_id: str | None,
    institution: str,
) -> None:
    inv = PluggyInvestment.model_validate(raw)
    outcome = _upsert(
        session,
        Investment,
        inv.id,
        now,
        {
            "item_id": item_id or raw.get("itemId"),
            "institution": institution,
            "name": inv.name,
            "code": inv.code,
            "isin": inv.isin,
            "type": inv.type,
            "subtype": inv.subtype,
            "status": inv.status,
            "currency_code": inv.currency_code,
            "issuer": inv.issuer,
            "issuer_cnpj": inv.issuer_cnpj,
            "purchase_date": pluggy_date(inv.purchase_date),
            "issue_date": pluggy_date(inv.issue_date),
            "due_date": pluggy_date(inv.due_date),
            "rate": inv.rate,
            "rate_type": inv.rate_type,
            "fixed_annual_rate": inv.fixed_annual_rate,
            "raw_json": _canonical(raw, redactor),
            "pluggy_updated_at": to_utc_naive(inv.updated_at),
        },
    )
    if outcome == "new":
        stats.investments_new += 1
    elif outcome == "updated":
        stats.investments_updated += 1
    session.flush()

    snapshot_values = {
        "quantity": inv.quantity,
        "unit_value": inv.value,
        "balance_cents": to_cents(inv.balance),
        "amount_cents": to_cents(inv.amount),
        "amount_original_cents": to_cents(inv.amount_original),
        "amount_profit_cents": to_cents(inv.amount_profit),
        "amount_withdrawal_cents": to_cents(inv.amount_withdrawal),
        "value_date": pluggy_date(inv.date),
        "status": inv.status,
        "captured_at": now,
    }
    snapshot = session.scalar(
        select(InvestmentSnapshot).where(
            InvestmentSnapshot.snapshot_date == today, InvestmentSnapshot.investment_id == inv.id
        )
    )
    if snapshot is None:
        session.add(InvestmentSnapshot(snapshot_date=today, investment_id=inv.id, **snapshot_values))
        stats.snapshots_created += 1
    else:
        for key, value in snapshot_values.items():
            setattr(snapshot, key, value)
        stats.snapshots_updated += 1


# ====================================================================== utilidades


def _upsert(session: Session, model: type, key: str, now: datetime, values: dict[str, Any]) -> str:
    """Insere ou atualiza pelo id da Pluggy. Retorna 'new', 'updated' ou 'unchanged'."""
    obj = session.get(model, key)
    if obj is None:
        session.add(model(id=key, first_seen_at=now, last_seen_at=now, **values))
        return "new"
    obj.last_seen_at = now
    if obj.raw_json == values["raw_json"]:
        return "unchanged"
    for name, value in values.items():
        setattr(obj, name, value)
    return "updated"


def _prefetch(session: Session, model: type, ids: Iterable[str]) -> None:
    """Carrega no identity map, em lotes, os registros que serão consultados por id."""
    ids = list(ids)
    for start in range(0, len(ids), _IN_CHUNK):
        session.scalars(select(model).where(model.id.in_(ids[start : start + _IN_CHUNK]))).all()


def _scrub(value: Any, redactor: Redactor) -> Any:
    """Cópia do payload com segredos mascarados em todas as strings (chaves e valores)."""
    if isinstance(value, str):
        return redactor(value)
    if isinstance(value, dict):
        return {(redactor(k) if isinstance(k, str) else k): _scrub(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, redactor) for v in value]
    return value


def _canonical(raw: Any, redactor: Redactor) -> str:
    """JSON estável (chaves ordenadas) para guardar e comparar; segredos mascarados."""
    return redactor(json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str))


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _amount_close(a: Transaction, b: Transaction) -> bool:
    x, y = a.amount_normalized_cents, b.amount_normalized_cents
    if x == 0 or y == 0 or (x > 0) != (y > 0):
        return False
    return abs(Decimal(x - y)) <= FUZZY_AMOUNT_TOLERANCE * abs(Decimal(y))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
