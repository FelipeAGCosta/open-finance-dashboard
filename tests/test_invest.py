"""Investimentos com dados sintéticos: origem de resgates, TWR/XIRR, patrimônio e proventos."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from findash.config import Paths
from findash.db.models import MarketSeries, RedemptionOrigin, TransactionClassification
from findash.invest import market
from findash.invest.commands import cmd_carteira
from findash.invest.origins import add_business_days
from findash.invest.performance import accumulated_result, period_equivalent, portfolio_series, twr, xirr
from ledger import BANK, CARD, INVESTMENT, NOW, Ledger


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def cls(session_factory, tx_id: str) -> TransactionClassification:
    with session_factory() as session:
        return session.get(TransactionClassification, tx_id)


def origins(session_factory, tx_id: str) -> list[RedemptionOrigin]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(RedemptionOrigin)
                .where(RedemptionOrigin.transaction_id == tx_id)
                .order_by(RedemptionOrigin.gross_cents)
            )
        )


# ---------------------------------------------------------------- origem dos resgates


def test_redemption_linked_to_snapshot_drops_summed_with_income_tax_difference(ledger, session_factory):
    fii = ledger.investment("FIIX11", "EQUITY", "REAL_ESTATE_FUND")
    cdb = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB EXEMPLO")
    monday, tuesday = date(2026, 11, 2), date(2026, 11, 3)
    assert monday.weekday() == 0
    ledger.snapshot(monday, fii, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(monday, cdb, quantity=50000, unit_value=0.02, balance=980, amount=1000)  # IR estimado: R$ 20
    ledger.snapshot(tuesday, fii, quantity=4, unit_value=101, balance=404)  # vendeu 6 cotas (~R$ 606)
    ledger.snapshot(tuesday, cdb, quantity=0, unit_value=0.02, balance=0, amount=0)  # resgate total
    # bruto 606 + 1.000 = 1.606; líquido 600 + 980 = 1.580; o crédito fica entre os dois (IR, taxas, preço)
    credit = ledger.tx(BANK, date(2026, 11, 4), 1586, "Valor recebido de Investimentos")
    orphan = ledger.tx(BANK, date(2026, 11, 20), 300, "Valor recebido de Investimentos")
    stats = ledger.classify()

    result = cls(session_factory, credit)
    assert result.movement_type == "resgate" and "queda na foto diária" in result.movement_rule
    linked = origins(session_factory, credit)
    assert [(o.source, o.investment_id, o.event_date) for o in linked] == [
        ("foto", fii, tuesday),
        ("foto", cdb, tuesday),
    ]
    assert [(o.gross_cents, o.net_cents) for o in linked] == [(60600, 60000), (100000, 98000)]

    unlinked = cls(session_factory, orphan)
    assert (unlinked.movement_type, unlinked.movement_rule) == (
        "resgate",
        "resgate de origem não identificada (acima de R$ 100)",
    )
    assert stats.redemptions_linked == {"foto": 1}
    assert (stats.redemptions_unlinked, stats.redemptions_unlinked_cents) == (1, 30000)


def test_redemption_linked_to_same_day_sales_within_business_day_window(ledger, session_factory):
    thursday = date(2026, 9, 24)
    assert thursday.weekday() == 3
    sells = [ledger.investment_tx(thursday, "SELL", 100.00), ledger.investment_tx(thursday, "SELL", 250.50)]
    # liquidação D+2 úteis cai na segunda-feira (4 dias corridos depois)
    monday = add_business_days(thursday, 2)
    assert monday == date(2026, 9, 28)
    credit = ledger.tx(BANK, monday, 350.50, "Valor recebido de Investimentos")
    # resgate da conta ("Resgate ...") também é ligado; venda 5 dias úteis antes fica fora da janela
    ledger.investment_tx(date(2026, 10, 1), "SELL", 500)
    late = ledger.tx(BANK, add_business_days(date(2026, 10, 1), 5), 500, "Resgate RDB")
    stats = ledger.classify()

    assert "venda (SELL)" in cls(session_factory, credit).movement_rule
    assert sorted(o.investment_transaction_id for o in origins(session_factory, credit)) == sorted(sells)
    assert {o.source for o in origins(session_factory, credit)} == {"transacao"}
    assert cls(session_factory, late).movement_type == "resgate" and origins(session_factory, late) == []
    assert stats.redemptions_linked == {"transacao": 1} and stats.redemptions_unlinked == 1


def test_small_investment_credit_without_origin_is_still_income(ledger, session_factory):
    small = ledger.tx(BANK, date(2026, 10, 15), 12.34, "Valor recebido de Investimentos")
    ledger.classify()
    assert cls(session_factory, small).movement_type == "renda_investimento"


# ---------------------------------------------------------------- TWR e XIRR à mão


def test_twr_matches_hand_calculation():
    d0, d1, d2 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    # dia 1: 1.000 -> 1.100 (+10%); dia 2: aporte de 500 e valor 1.650 -> (1.650 − 1.100 − 500) ÷ 1.100 = +4,5454%
    assert twr([(d0, 100000), (d1, 110000), (d2, 165000)], [(d2, 50000)]) == pytest.approx(0.15)
    # provento pago na conta conta como retorno: 1.000 -> 1.000 com R$ 10 de provento = +1%
    assert twr([(d0, 100000), (d1, 100000)], [], [(d1, 1000)]) == pytest.approx(0.01)
    # resgate de 300 no meio: 1.000 -> 720 com saída de 300 = (720 − 1.000 + 300) ÷ 1.000 = +2%
    assert twr([(d0, 100000), (d1, 72000)], [(d1, -30000)]) == pytest.approx(0.02)
    # trecho de 10 dias (fotos faltando), aporte no dia 5 pesa metade: 100 ÷ (1.000 + 0,5 × 1.000)
    assert twr([(d0, 100000), (d0 + timedelta(days=10), 210000)], [(d0 + timedelta(days=5), 100000)]) == pytest.approx(
        1 / 15
    )
    assert twr([(d0, 100000)], []) is None


def test_xirr_matches_hand_calculation():
    start = date(2025, 1, 1)
    assert xirr([(start, -100000), (start + timedelta(days=365), 110000)]) == pytest.approx(0.10, abs=1e-9)
    assert xirr([(start, -100000), (start + timedelta(days=730), 121000)]) == pytest.approx(0.10, abs=1e-9)
    # dois aportes de 1.000 (hoje e daqui a 1 ano) e 2.310 em 2 anos: 1.000×1,1² + 1.000×1,1 = 2.310 -> 10%
    flows = [(start, -100000), (start + timedelta(days=365), -100000), (start + timedelta(days=730), 231000)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)
    assert period_equivalent(0.10, 365) == pytest.approx(0.10)
    assert xirr([(start, -100000)]) is None


def test_portfolio_performance_uses_contributions_and_photo_dates(ledger, session_factory):
    d1, d2, d3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
    ledger.snapshot(d1, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, d2, -500, "Aplicação em Tesouro Direto")  # aporte: entra na carteira
    ledger.snapshot(d2, INVESTMENT, quantity=15, unit_value=101.33, balance=1520)  # (1.520 − 1.000 − 500) ÷ 1.000 = 2%
    ledger.snapshot(d3, INVESTMENT, quantity=15, unit_value=102.344, balance=1535.2)  # +1%
    ledger.classify()
    with session_factory() as session:
        series = portfolio_series(session)
    result = accumulated_result(series)
    assert result.twr == pytest.approx(1.02 * 1.01 - 1, abs=1e-9)
    assert (result.start_value, result.end_value, result.net_flows) == (100000, 153520, 50000)
    assert result.xirr_annual is not None and result.xirr_period > 0


# Patrimônio total (só o investido + em trânsito): tests/test_wealth.py


# ---------------------------------------------------------------- mercado (SGS) e CLI


def test_market_cache_and_benchmarks(session_factory):
    calls = []

    def fake_fetch(code, start, end):
        calls.append((code, start, end))
        if code == market.CDI:
            return [(date(2026, 11, 2), Decimal("0.05")), (date(2026, 11, 3), Decimal("0.05"))]
        return [(date(2026, 10, 1), Decimal("0.30"))]

    with session_factory() as session:
        market.refresh(session, date(2026, 10, 1), date(2026, 11, 4), now=NOW, fetch=fake_fetch)
        market.refresh(session, date(2026, 10, 1), date(2026, 11, 4), now=NOW, fetch=fake_fetch)  # só busca o resto
        session.commit()
        assert session.query(MarketSeries).count() == 3
        assert market.cdi_return(session, date(2026, 11, 2), date(2026, 11, 4)).value == pytest.approx(1.0005**2 - 1)
        october = market.ipca_return(session, date(2026, 10, 1), date(2026, 11, 1))
        assert october.value == pytest.approx(0.003)
        half = market.ipca_return(session, date(2026, 10, 1), date(2026, 11, 16))  # novembro ainda sem IPCA
        assert half.value == pytest.approx(0.003) and "11/2026" in half.note
    assert calls[2][1] == date(2026, 11, 3)  # segunda atualização começa no último dia guardado


def test_carteira_command(ledger, session_factory, tmp_path, monkeypatch, capsys):
    import findash.invest.commands as invest_commands

    monkeypatch.setattr(invest_commands, "utcnow", lambda: NOW)
    paths = Paths(tmp_path)
    paths.ensure()
    tesouro = ledger.investment("BRSTNEXEMPLO", "FIXED_INCOME", "TREASURY", name="Tesouro Exemplo 2031")
    for day, value in ((date(2026, 11, 18), 1000), (date(2026, 11, 19), 1001)):
        ledger.snapshot(day, INVESTMENT, quantity=10, unit_value=value / 10, balance=value)
        ledger.snapshot(day, tesouro, quantity=0.05, unit_value=20000, balance=995, amount=1000, original=950)
        ledger.account_snapshot(day, BANK, 200)
        ledger.account_snapshot(day, CARD, 50)
    ledger.investment_tx(date(2026, 10, 15), "INTEREST", 7.5)
    ledger.classify()

    def fake_fetch(code, start, end):
        return [(date(2026, 11, 18), Decimal("0.05"))] if code == market.CDI else []

    assert cmd_carteira(paths, session_factory, fetch=fake_fetch) == 0
    out = capsys.readouterr().out
    assert "FIIs" in out and "Tesouro" in out and "fotos diárias: 2" in out
    assert "R$ 2.001,00" in out and "conta e fatura ficam fora" in out  # patrimônio = carteira bruta: 1.001 + 1.000
    assert "0,05%" in out  # CDI do período
    assert "aplicado R$ 950,00" in out.replace("  ", " ") or "R$ 950,00" in out
    assert "FICT11 R$ 7,50" in out  # provento


def test_asset_variation_discounts_purchases(ledger, session_factory):
    from findash.invest.variation import asset_variations

    d1, d2, d3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
    ledger.snapshot(d1, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.investment_tx(d2, "BUY", 550, quantity=5)  # aporte não é valorização
    ledger.snapshot(d2, INVESTMENT, quantity=15, unit_value=110, balance=1650)
    sold_out = ledger.investment("SAIU3", "EQUITY", "STOCK")
    ledger.snapshot(d1, sold_out, quantity=1, unit_value=10, balance=10)
    ledger.snapshot(d3, INVESTMENT, quantity=15, unit_value=120, balance=1800)
    with session_factory() as session:
        variations = asset_variations(session)
    v = variations[INVESTMENT]
    assert (v.first_date, v.start_cents, v.end_cents, v.bought_cents, v.sold_cents) == (d1, 100000, 180000, 55000, 0)
    assert v.change_cents == 25000 and v.change_pct == pytest.approx(250 / 1550)
    assert sold_out not in variations  # fora da carteira na foto mais recente
