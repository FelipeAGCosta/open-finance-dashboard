"""Patrimônio total = só o investido (como no app do banco) + "em trânsito". Dados SINTÉTICOS."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from findash.db.models import Investment
from findash.institutions import get_profile
from findash.invest import transit_choices
from findash.invest.wealth import account_balances, wealth
from ledger import BANK, CARD, INVESTMENT, NOW, Ledger

MON, TUE, WED, THU, FRI = (date(2026, 11, d) for d in (2, 3, 4, 5, 6))


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def total(session_factory, today: date):
    with session_factory() as session:
        return wealth(session, today)


def test_total_is_only_the_portfolio_not_bank_minus_card_bill(ledger, session_factory):
    other = ledger.investment("ACAO3", "EQUITY", "STOCK")
    cdb = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB EXEMPLO")
    ledger.account_snapshot(MON, BANK, 1000.00)
    ledger.account_snapshot(MON, CARD, 300.25)  # fatura em aberto
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, other, quantity=5, unit_value=800, balance=4000)
    ledger.snapshot(MON, cdb, quantity=None, unit_value=None, balance=980, amount=1000)  # bruto, como o banco mostra
    w = total(session_factory, MON)
    assert (w.portfolio_cents, w.in_transit_cents, w.total_cents) == (600000, 0, 600000)  # conta e fatura fora
    with session_factory() as session:
        b = account_balances(session)
    assert (b.day, b.bank_cents, b.card_bill_cents) == (MON, 100000, 30025)  # só informação, à parte


def test_purchase_is_in_transit_until_the_position_arrives(ledger, session_factory):
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, TUE, -500.00, "Compra de Renda Variável")  # saiu da conta; a posição chega em D+2
    ledger.classify()

    w = total(session_factory, TUE)
    assert [(o.day, o.cents, o.until) for o in w.in_transit] == [(TUE, 50000, date(2026, 11, 10))]  # D+5 úteis
    assert w.total_cents == 150000  # o patrimônio não fica "parado" com R$ 500 a menos
    assert [(d.day, d.total_cents) for d in w.series] == [(MON, 100000), (TUE, 150000)]

    ledger.snapshot(WED, INVESTMENT, quantity=10, unit_value=101, balance=1010)
    ledger.snapshot(THU, INVESTMENT, quantity=15, unit_value=101, balance=1515)  # 5 cotas × 101 = 505 (1% de diferença)
    w = total(session_factory, THU)
    assert w.in_transit == [] and w.total_cents == 151500  # chegou: sai do "em trânsito" sozinho
    assert [(d.day, d.in_transit_cents, d.total_cents) for d in w.series] == [
        (MON, 0, 100000),
        (TUE, 50000, 150000),
        (WED, 50000, 151000),
        (THU, 0, 151500),
    ]


def test_fixed_income_application_arrives_as_a_new_title(ledger, session_factory):
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, TUE, -2000.00, "Aplicação RDB")
    ledger.tx(BANK, TUE, -300.00, "Aplicação RDB")  # duas aplicações no dia viram um título só
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    assert total(session_factory, TUE).in_transit_cents == 230000
    cdb = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB EXEMPLO")
    ledger.snapshot(WED, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(WED, cdb, quantity=None, unit_value=None, balance=2300.40)
    w = total(session_factory, WED)
    assert w.in_transit == [] and w.total_cents == 330040


def test_unconfirmed_purchase_leaves_after_five_business_days_and_old_ones_are_ignored(ledger, session_factory):
    ledger.tx(BANK, MON, -700.00, "Compra de Renda Variável")  # no dia da primeira foto: pode já estar nela
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, TUE, -400.00, "Compra de Renda Variável")
    ledger.tx(BANK, TUE, 50.00, "Dinheiro resgatado de Saldo de Investimentos")  # resgate não entra
    ledger.classify()
    ledger.snapshot(date(2026, 11, 10), INVESTMENT, quantity=10, unit_value=100, balance=1000)
    assert [o.cents for o in total(session_factory, date(2026, 11, 10)).in_transit] == [40000]  # D+5 úteis: ainda vale
    assert total(session_factory, date(2026, 11, 11)).in_transit == []  # passou da janela: sai sozinho


def test_purchase_paid_elsewhere_keeps_its_own_arrival(ledger, session_factory):
    """Compra registrada de outro ativo, sem saída da conta (paga de outro lugar), não limpa a saída do dia seguinte."""
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    bdr = ledger.investment("XPTO34", "EQUITY", "BDR")
    ledger.investment_tx(MON, "BUY", 330.00, investment=bdr, quantity=6)
    ledger.tx(BANK, TUE, -480.00, "Compra de Renda Variável")
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(TUE, bdr, quantity=6, unit_value=55, balance=330)  # candidato único, mas é a compra de segunda
    w = total(session_factory, FRI)
    assert [o.cents for o in w.in_transit] == [48000] and w.total_cents == 181000


def test_increase_of_an_existing_position_with_purchase_costs(ledger, session_factory):
    """Compra de mais cotas de um ativo que já existia; a saída da conta inclui ~1% de custos."""
    bdr = ledger.investment("XPTO34", "EQUITY", "BDR")
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, bdr, quantity=1, unit_value=20, balance=20)
    ledger.tx(BANK, TUE, -505.05, "Compra de Renda Variável")  # 500,00 de cotas + 5,05 de custos
    ledger.investment_tx(TUE, "BUY", 500.00, investment=bdr, quantity=25)
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(TUE, bdr, quantity=1, unit_value=20, balance=20)
    w = total(session_factory, TUE)
    assert [(o.cents, o.suggestion) for o in w.in_transit] == [(50505, bdr)]  # sugestão: o ativo da compra
    ledger.snapshot(THU, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(THU, bdr, quantity=26, unit_value=19.5, balance=507)  # +25 cotas × 19,50 = 487,50
    w = total(session_factory, THU)
    assert w.in_transit == [] and w.total_cents == 150700


def test_sum_of_new_and_increased_positions_on_the_same_day(ledger, session_factory):
    other = ledger.investment("ACAO3", "EQUITY", "STOCK")
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, other, quantity=10, unit_value=40, balance=400)
    ledger.tx(BANK, TUE, -900.00, "Compra de Renda Variável")  # duas ordens pagas numa saída só
    ledger.classify()
    new = ledger.investment("NOVO11", "EQUITY", "REAL_ESTATE_FUND")
    ledger.snapshot(WED, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(WED, other, quantity=22, unit_value=41.5, balance=913)  # +12 cotas × 41,50 = 498
    ledger.snapshot(WED, new, quantity=4, unit_value=100.5, balance=402)
    w = total(session_factory, WED)
    assert w.in_transit == [] and w.total_cents == 231500


def test_single_candidate_matches_even_with_a_distant_value(ledger, session_factory):
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, TUE, -600.00, "Compra de Renda Variável")
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(THU, INVESTMENT, quantity=15, unit_value=100, balance=1500)  # 500: 17% abaixo, mas é o único
    w = total(session_factory, THU)
    assert w.in_transit == [] and w.total_cents == 150000


def test_two_distant_candidates_do_not_match(ledger, session_factory):
    other = ledger.investment("ACAO3", "EQUITY", "STOCK")
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, other, quantity=10, unit_value=40, balance=400)
    ledger.tx(BANK, TUE, -600.00, "Compra de Renda Variável")
    ledger.classify()
    ledger.snapshot(WED, INVESTMENT, quantity=15, unit_value=100, balance=1500)  # 500
    ledger.snapshot(WED, other, quantity=11, unit_value=40, balance=440)  # 40: nem um nem a soma (540) dá 600
    assert [o.cents for o in total(session_factory, WED).in_transit] == [60000]


def test_purchase_already_in_the_same_day_photo_never_enters_transit(ledger, session_factory):
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.tx(BANK, TUE, -300.00, "Compra de Renda Variável")
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=13, unit_value=100, balance=1300)
    w = total(session_factory, TUE)
    assert w.in_transit == [] and [(d.day, d.in_transit_cents) for d in w.series] == [(MON, 0), (TUE, 0)]


def test_manual_choice_wins_and_persists(ledger, session_factory):
    other = ledger.investment("ACAO3", "EQUITY", "STOCK")
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, other, quantity=10, unit_value=40, balance=400)
    tx = ledger.tx(BANK, TUE, -480.00, "Compra de Renda Variável")
    ledger.classify()
    ledger.snapshot(TUE, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(TUE, other, quantity=10, unit_value=40, balance=400)

    def choose(action, investment=None):
        with session_factory() as session:
            previous = transit_choices.set_choice(session, tx, action, investment, now=NOW)
            session.commit()
        return previous

    assert total(session_factory, TUE).in_transit_cents == 48000
    assert choose(transit_choices.IGNORED) is None
    assert total(session_factory, TUE).in_transit == []  # "ignorar": some e não volta
    assert choose(transit_choices.ARRIVED, other) == transit_choices.Choice(transit_choices.IGNORED)
    w = total(session_factory, TUE)
    assert w.in_transit == [] and w.total_cents == 140000  # "já chegou (é o ACAO3)": não soma de novo
    with session_factory() as session:
        assert transit_choices.load(session) == {tx: transit_choices.Choice(transit_choices.ARRIVED, other)}
    choose(None)  # volta ao automático
    assert total(session_factory, TUE).in_transit_cents == 48000
    with session_factory() as session, pytest.raises(ValueError):
        transit_choices.set_choice(session, tx, transit_choices.ARRIVED, None, now=NOW)


def test_caixinha_counts_net_of_income_tax_like_the_bank_app(ledger, session_factory):
    caixinha = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB - NU FINANCEIRA S.A. - EXEMPLO")
    cdb = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB - BANCO EXEMPLO S.A.")
    treasury = ledger.investment("TESOURO-EX", "FIXED_INCOME", "TREASURY", name="Tesouro Exemplo")
    ledger.snapshot(MON, INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(MON, caixinha, quantity=None, unit_value=None, balance=950.50, amount=990.00)
    ledger.snapshot(MON, cdb, quantity=None, unit_value=None, balance=480.00, amount=500.00)
    ledger.snapshot(MON, treasury, quantity=None, unit_value=None, balance=2950.00, amount=3000.00)
    assert total(session_factory, MON).total_cents == 100000 + 95050 + 50000 + 300000  # Caixinha líquida; o resto bruto
    with session_factory() as session:
        investments = {inv.id: inv for inv in session.scalars(select(Investment))}
    order = (INVESTMENT, caixinha, cdb, treasury)
    nubank, generic = get_profile("nubank"), get_profile("generic")
    assert [nubank.app_group(investments[i]) for i in order] == [
        "Bolsa de valores",
        "Caixinhas",
        "Outros",
        "Tesouro Direto",
    ]
    assert [generic.app_group(investments[i]) for i in order] == [
        "Bolsa de valores",
        "Renda fixa",
        "Renda fixa",
        "Tesouro Direto",
    ]
    assert not generic.values_net_of_tax(investments[caixinha])  # sem o perfil do banco, vale o bruto
