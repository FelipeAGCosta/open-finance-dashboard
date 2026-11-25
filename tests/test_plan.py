"""Plano: metas com vigência, Reserva por valor fixo, Patrimônio por classe (núcleo, manter,
satélite), checklist do aporte do mês, capacidade do mês e Investimentos.

Contas conferidas à mão nos comentários. Dados 100% sintéticos.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from findash.classify.salary import WEEKLY, SalarySchedule
from findash.classify.summary import month_summary
from findash.db.models import ClassificationOverride, RecurringRule, Transaction
from findash.invest.classes import load_class_map
from findash.invest.performance import monthly_returns, portfolio_series
from findash.invest.portfolio import dividends_by_class, positions
from findash.plan import settings as S
from findash.plan.capacity import month_capacity
from findash.plan.contribution import AssetTarget, core_weights, split_month, split_patrimony, water_fill
from findash.plan.places import PATRIMONY, RESERVE, assign, set_place, totals
from findash.settings import PlanDefaults
from findash.sync.service import stale_hours
from findash.web.views.investments import target_return
from findash.web.views.overview import investments_month
from findash.web.views.plan import PlanState, _checklist, flows_json, month_plan, plan
from ledger import BANK, CARD, CONFIG_DIR, INVESTMENT, Ledger, company

NOW = datetime(2026, 11, 20, 12, 0)
TODAY = date(2026, 11, 20)
DEFAULTS = PlanDefaults(
    monthly_contribution_cents=100_000,
    extra_paycheck=False,
    cash_cushion_cents=20_000,
    reserve_cents=None,
    target_allocation=None,
    assumed_return=0.10,
    aspirational_return=0.12,
)


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def _class_map():
    class_map = load_class_map(CONFIG_DIR, None)
    class_map.tickers.update({"GLOB11": "ETF Global"})
    return class_map


# ------------------------------------------------------------------ vigência das metas


def test_goal_change_applies_from_chosen_month_and_past_months_keep_old_value(session_factory):
    with session_factory() as session:
        assert S.value_at(session, S.MONTHLY_TARGET, "2026-11").effective_month is None  # padrão, nunca gravado
        S.ensure_initial(session, "2026-09", DEFAULTS, now=NOW)
        S.ensure_initial(session, "2026-11", DEFAULTS, now=NOW)  # não duplica
        row = S.save(session, S.MONTHLY_TARGET, "2026-12", {"cents": 100_000, "extra_paycheck": True}, now=NOW)
        assert S.value_at(session, S.MONTHLY_TARGET, "2026-08").value["cents"] == 100_000  # padrão antes do início
        assert S.value_at(session, S.MONTHLY_TARGET, "2026-11").value["extra_paycheck"] is False  # histórico preservado
        assert S.value_at(session, S.MONTHLY_TARGET, "2027-01").value["extra_paycheck"] is True
        assert S.first_month(session, S.MONTHLY_TARGET) == "2026-09"
        S.delete(session, row.id)  # desfazer
        assert S.value_at(session, S.MONTHLY_TARGET, "2027-01").value["extra_paycheck"] is False


def test_history_records_only_real_changes(session_factory):
    target = {"classes": ALLOC, "etf_global": "GLOB11", "etf_brasil": None}
    with session_factory() as session:
        assert S.save(session, S.PATRIMONY_TARGET, "2026-11", target, now=NOW) is not None
        # salvar de novo o mesmo valor (no mesmo mês ou num mês seguinte) não grava nada
        assert S.save(session, S.PATRIMONY_TARGET, "2026-11", target, now=NOW) is None
        assert S.save(session, S.PATRIMONY_TARGET, "2026-12", target, now=NOW) is None
        assert len(S.history(session, S.PATRIMONY_TARGET)) == 1
        # três marcações no mesmo mês: o histórico mostra só a que ficou valendo
        for tickers in (["ACAA3"], ["ACAA3", "BBBB3"], ["BBBB3"]):
            S.save(session, S.CORE, "2026-11", {"tickers": tickers}, now=NOW)
        assert [r.value_json["tickers"] for r in S.changes(session, S.CORE)] == [["BBBB3"]]
        # gravações antigas repetidas (de antes desta regra) também somem do histórico exibido
        from findash.db.models import PlanSetting

        session.add(
            PlanSetting(key=S.CORE, effective_month="2027-01", value_json={"tickers": ["BBBB3"]}, created_at=NOW)
        )
        session.flush()
        assert len(S.changes(session, S.CORE)) == 1 and len(S.history(session, S.CORE)) == 4


ALLOC = {"renda_fixa": 20, "etf_global": 35, "etf_brasil": 20, "acoes_nucleo": 10, "fiis": 5, "satelite": 10}


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        (S.PATRIMONY_TARGET, {"classes": {**ALLOC, "satelite": 0}}, "somar 100%"),
        (S.PATRIMONY_TARGET, {"classes": {**ALLOC, "fiis": None}}, "preencha todos"),
        (S.PATRIMONY_TARGET, {"classes": ALLOC, "etf_global": "ab"}, "código de negociação"),
        (S.RESERVE, {"cents": 500_000, "order": ["Ações"]}, "Composição"),
        (S.MONTHLY_TARGET, {"cents": -1}, "maior ou igual a zero"),
        (S.MONTHLY_TARGET, {"cents": 100, "extra_paycheck": "sim"}, "Pagamento extra"),
        (S.CORE, {"tickers": ["ACAA3", "BBBB3"], "weights": "personalizado", "custom": {"ACAA3": 60}}, "cada empresa"),
        (
            S.CORE,
            {"tickers": ["ACAA3", "BBBB3"], "weights": "personalizado", "custom": {"ACAA3": 60, "BBBB3": 30}},
            "somar 100%",
        ),
        (S.CORE, {"tickers": ["ACAA3"], "weights": "outro"}, "Pesos do núcleo"),
        (S.RETURNS, {"assumed": 0.9, "aspirational": 0.12}, "entre 0% e 50%"),
        ("divisao_objetivos", {"reserva": 100}, "desconhecida"),  # chave que não existe
    ],
)
def test_settings_validation(session_factory, key, value, message):
    with session_factory() as session, pytest.raises(S.PlanError, match=message):
        S.save(session, key, "2026-11", value, now=NOW)


def test_patrimony_target_sums_100_and_core_tickers_are_normalized(session_factory):
    with session_factory() as session:
        S.save(session, S.PATRIMONY_TARGET, "2026-11", {"classes": ALLOC, "etf_global": "glob11"}, now=NOW)
        S.save(session, S.CORE, "2026-11", {"tickers": ["acaa3", "ACAA3", "bbbb3"]}, now=NOW)
        assert S.value_at(session, S.PATRIMONY_TARGET, "2026-11").value["etf_global"] == "GLOB11"
        assert S.value_at(session, S.CORE, "2026-11").value == {
            "tickers": ["ACAA3", "BBBB3"],
            "satellite": [],
            "weights": "iguais",
            "custom": {},
        }
        # gravação antiga (com o destino do extra, que saiu) continua lendo: o campo que não existe mais é ignorado
        from findash.db.models import PlanSetting

        session.add(
            PlanSetting(
                key=S.MONTHLY_TARGET,
                effective_month="2026-11",
                created_at=NOW,
                value_json={"cents": 90_000, "extra_paycheck": True, "campo_antigo": "x"},
            )
        )
        session.flush()
        assert S.value_at(session, S.MONTHLY_TARGET, "2026-11").value == {"cents": 90_000, "extra_paycheck": True}
        with pytest.raises(S.PlanError, match="núcleo e satélite"):
            S.save(session, S.CORE, "2026-11", {"tickers": ["ACAA3"], "satellite": ["acaa3"]}, now=NOW)
        assert S.value_at(session, S.RETURNS, "2026-11").value == {"assumed": 0.10, "aspirational": 0.12}  # padrão


# ------------------------------------------------------------------ Reserva por valor fixo e lugares


def _fixed_income_and_etf(ledger: Ledger) -> tuple[str, str, str]:
    day = date(2026, 11, 19)
    cdb = ledger.investment(None, "FIXED_INCOME", "CDB", name="CDB FICTICIO")
    treasury = ledger.investment(None, "FIXED_INCOME", "TREASURY", name="Tesouro Selic Ficticio")
    etf = ledger.investment("GLOB11", "ETF", "ETF")
    ledger.snapshot(day, cdb, quantity=1, unit_value=None, balance=3000)
    ledger.snapshot(day, treasury, quantity=1, unit_value=None, balance=4000, amount=4100)
    ledger.snapshot(day, etf, quantity=10, unit_value=100, balance=1000)
    return cdb, treasury, etf


def test_reserve_is_a_fixed_value_filled_by_daily_liquidity_first(ledger, session_factory):
    cdb, treasury, _ = _fixed_income_and_etf(ledger)
    with session_factory() as session:
        items = positions(session, _class_map())
        holdings = assign(session, items, reserve_cents=500_000, order=["CDB/RDB", "Tesouro"])
        # Reserva R$ 5.000: CDB (liquidez diária) entra primeiro com 3.000; o Tesouro completa 2.000 e o resto
        # (4.100 bruto − 2.000 = 2.100) é Patrimônio, junto com o ETF (1.000)
        assert totals(holdings) == {RESERVE: 500_000, PATRIMONY: 310_000}
        assert next(h for h in holdings if h.position.investment.id == treasury).parts == {
            RESERVE: 200_000,
            PATRIMONY: 210_000,
        }
        # cada real em um lugar só: a soma dos lugares é a carteira inteira
        assert sum(totals(holdings).values()) == sum(p.value_cents for p in items)
        # composição só com Tesouro: o CDB fica fora da Reserva
        only_treasury = assign(session, items, reserve_cents=500_000, order=["Tesouro"])
        assert totals(only_treasury) == {RESERVE: 410_000, PATRIMONY: 400_000}
        # escolha manual vence e conta na Reserva: o CDB inteiro no Patrimônio, o Tesouro sozinho não completa
        set_place(session, cdb, PATRIMONY, now=NOW)
        manual = assign(session, items, reserve_cents=500_000, order=["CDB/RDB", "Tesouro"])
        assert totals(manual) == {RESERVE: 410_000, PATRIMONY: 400_000}
        assert next(h for h in manual if h.position.investment.id == cdb).reason == "escolha sua"
        # só existem dois lugares: Reserva e Patrimônio
        with pytest.raises(ValueError, match="Lugar inválido"):
            set_place(session, cdb, "objetivo:1", now=NOW)
        # a renda fixa acima da Reserva entra na classe "Renda fixa" do Patrimônio
        set_place(session, cdb, None, now=NOW)
        S.save(session, S.RESERVE, "2026-11", {"cents": 500_000, "order": ["CDB/RDB", "Tesouro"]}, now=NOW)
        pat = PlanState(session, _class_map(), TODAY).patrimony_json()
        assert pat["values"] == {"renda_fixa": 210_000, "etf_global": 100_000} and pat["current"] == 310_000


def test_reserve_without_value_takes_all_automatic_fixed_income(ledger, session_factory):
    _fixed_income_and_etf(ledger)
    with session_factory() as session:
        holdings = assign(session, positions(session, _class_map()), reserve_cents=None, order=["CDB/RDB", "Tesouro"])
        assert totals(holdings) == {RESERVE: 710_000, PATRIMONY: 100_000}


# ------------------------------------------------------------------ divisão do aporte e Patrimônio


def test_patrimony_split_by_class_without_selling_and_never_fiis_or_satellite():
    targets = dict(ALLOC)
    values = {
        "renda_fixa": 0,
        "etf_global": 400_000,
        "etf_brasil": 10_000,
        "acoes_nucleo": 120_000,
        "fiis": 500_000,
        "satelite": 200_000,
    }
    core = {"ACAA3": 100_000, "BBBB3": 20_000}
    # entre as classes que recebem (pesos 20/35/20/10 de 85): nível L com (20/85)·L + ((20/85)·L − 100) = 1.000
    # -> L = 2.337,50: renda fixa 550, ETF Brasil 450; ETF Global e núcleo já estão acima do nível
    result = split_patrimony(
        100_000, targets, values, core, {"etf_global": "GLOB11", "etf_brasil": "BRSL11"}, {"BRSL11": 10_000}
    )
    assert result.buckets == {"renda_fixa": 55_000, "etf_global": 0, "etf_brasil": 45_000, "acoes_nucleo": 0}
    etf, fixed = result.items
    # ETF a R$ 100: 4 cotas (400); a sobra de 50 vai para a renda fixa
    assert (etf.ticker, etf.shares, etf.spend_cents) == ("BRSL11", 4, 40_000)
    assert (fixed.ticker, fixed.spend_cents, fixed.carried_in_cents) == (None, 60_000, 5_000)
    assert result.leftover_cents == 0 and {i.bucket for i in result.items} <= {"renda_fixa", "etf_brasil"}
    # núcleo em pesos iguais: a empresa mais abaixo do peso recebe primeiro (BBBB3 sobe de 200 para 500, igual
    # a ... ainda abaixo de ACAA3): L/2 − 200 = 300 -> tudo para BBBB3
    assert water_fill(30_000, [AssetTarget(t, 1, v) for t, v in core.items()]) == {"ACAA3": 0, "BBBB3": 30_000}
    only_core = split_patrimony(
        30_000, {**{k: 0 for k in targets}, "acoes_nucleo": 100}, values, core, {}, {"BBBB3": 1_000}
    )
    [item] = only_core.items
    assert (item.ticker, item.shares, item.spend_cents) == ("BBBB3", 30, 30_000) and only_core.leftover_cents == 0


def _stocks_etf_and_fii(ledger: Ledger) -> None:
    day = date(2026, 11, 19)
    for code, kind, subtype, balance in (
        ("GLOB11", "ETF", "ETF", 3000),
        ("ACAA3", "EQUITY", "STOCK", 500),
        ("XPTO34", "EQUITY", "BDR", 1500),
        ("CCCC3", "EQUITY", "STOCK", 1000),
    ):
        inv = ledger.investment(code, kind, subtype)
        ledger.snapshot(day, inv, quantity=1, unit_value=balance, balance=balance)
    ledger.snapshot(day, INVESTMENT, quantity=10, unit_value=100, balance=1000)  # FICT11 (FII)


def test_patrimony_deviation_by_class_core_company_and_satellite_cap(ledger, session_factory):
    _stocks_etf_and_fii(ledger)
    with session_factory() as session:
        S.save(session, S.PATRIMONY_TARGET, "2026-11", {"classes": ALLOC, "etf_global": "GLOB11"}, now=NOW)
        S.save(session, S.CORE, "2026-11", {"tickers": ["ACAA3"], "satellite": ["XPTO34"]}, now=NOW)
        pat = PlanState(session, _class_map(), TODAY).patrimony_json()
    buckets = {b["bucket"]: b for b in pat["buckets"]}
    # total 7.000: ETF Global 3.000 = 42,86% (alvo 35% -> +7,86 pontos / +550); núcleo 500; satélite (BDR) 1.500 =
    # 21,4% acima do teto de 10%; CCCC3 (sem marcação) fica em "Ações mantidas"
    assert pat["current"] == 700_000 and buckets["etf_global"]["deviation_cents"] == 300_000 - 245_000
    assert buckets["etf_global"]["deviation_pct"] == pytest.approx(3000 / 7000 - 0.35)
    assert buckets["satelite"]["over_cap"] and not buckets["fiis"]["suggested"] and not buckets["satelite"]["suggested"]
    [company_row] = pat["core"]
    assert company_row["ticker"] == "ACAA3" and company_row["target_pct"] == pytest.approx(0.10)
    assert company_row["deviation_pct"] == pytest.approx(500 / 7000 - 0.10)
    # estado em palavras: renda fixa e ETF Brasil abaixo, ETF Global e FIIs (14,3% × 5%) acima, satélite acima do
    # teto; o núcleo (7,1% × 10%) está 2,9 pontos abaixo -> 6 classes fora do alvo
    assert {b: buckets[b]["state"] for b in buckets} == {
        "renda_fixa": "abaixo",
        "etf_global": "acima",
        "etf_brasil": "abaixo",
        "acoes_nucleo": "abaixo",
        "fiis": "acima",
        "acoes_mantidas": "sem_alvo",
        "satelite": "acima_teto",
    }
    assert pat["off_target"] == 6


# ------------------------------------------------------------------ "O que fazer este mês": checklist


def test_split_order_reserve_first_then_patrimony():
    # falta R$ 300 na Reserva: ela recebe primeiro; o resto da meta (base + pagamento extra) é Patrimônio
    split = split_month(150_000, 30_000)
    assert split.amounts == {RESERVE: 30_000, PATRIMONY: 120_000} and split.reserve_priority_cents == 30_000
    # falta mais do que a meta inteira: tudo para a Reserva
    assert split_month(150_000, 200_000).amounts == {RESERVE: 150_000, PATRIMONY: 0}
    # Reserva completa: tudo para o Patrimônio
    assert split_month(100_000, 0).amounts == {RESERVE: 0, PATRIMONY: 100_000}


def test_extra_paycheck_joins_the_month_target(ledger, session_factory):
    with session_factory() as session:
        session.add(
            RecurringRule(
                kind="salario",
                counterparty_key="EMPREGADORFICTICIO",
                status="automatico",
                paycheck_cents=40_000,
                pay_frequency="weekly",
                payday=0,
                grace_days=2,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        S.save(session, S.MONTHLY_TARGET, "2026-11", {"cents": 100_000, "extra_paycheck": True}, now=NOW)
        state = PlanState(session, _class_map(), TODAY)
        weekly = SalarySchedule(WEEKLY, payday=0)
        assert weekly.extra_paychecks("2026-11") == 1 and weekly.extra_paychecks("2026-12") == 0  # 5 e 4 segundas
        assert state.extra_of("2026-11") == 40_000 and state.extra_of("2026-12") == 0
        pat = state.patrimony_json()
        assert month_plan(state, pat, "2026-11", {})[0]["total"] == 140_000
        assert month_plan(state, pat, "2026-12", {})[0]["total"] == 100_000


def test_stock_roles_core_keep_satellite(ledger, session_factory):
    _stocks_etf_and_fii(ledger)
    prices = {"GLOB11": 300_000, "ACAA3": 50_000, "CCCC3": 100_000, "XPTO34": 150_000}
    with session_factory() as session:
        S.save(session, S.PATRIMONY_TARGET, "2026-11", {"classes": ALLOC, "etf_global": "GLOB11"}, now=NOW)
        # sem marcação nenhuma, toda ação/BDR é "Manter": classe própria, sem alvo, fora do núcleo e do satélite
        state = PlanState(session, _class_map(), TODAY)
        pat = state.patrimony_json()
        buckets = {b["bucket"]: b for b in pat["buckets"]}
        assert buckets["acoes_mantidas"]["current"] == 300_000 and buckets["acoes_mantidas"]["target_pct"] is None
        assert buckets["acoes_mantidas"]["state"] == "sem_alvo" and not buckets["acoes_mantidas"]["suggested"]
        assert buckets["acoes_nucleo"]["current"] == 0 and buckets["satelite"]["current"] == 0
        assert buckets["acoes_nucleo"]["needs_core"] is True  # tem alvo, mas nenhuma empresa escolhida
        assert {h["ticker"]: h["role"] for h in plan(session, _class_map(), today=TODAY, now=NOW)["holdings"]} == {
            "GLOB11": None,
            "ACAA3": "manter",
            "XPTO34": "manter",
            "CCCC3": "manter",
            "FICT11": None,
        }
        # nenhuma ação mantida recebe aporte: o dinheiro só vai para renda fixa e ETF
        data, _, split = month_plan(state, pat, "2026-12", prices)
        assert {i.ticker for i in split.items} <= {None, "GLOB11"}
        assert all(line["where"] not in ("ACAA3", "CCCC3", "XPTO34") for line in data["checklist"])
        # marcada como núcleo, ACAA3 passa a receber; CCCC3 (manter) e XPTO34 (satélite) continuam sem aporte
        S.save(session, S.CORE, "2026-11", {"tickers": ["ACAA3"], "satellite": ["XPTO34"]}, now=NOW)
        S.save(session, S.MONTHLY_TARGET, "2026-11", {"cents": 1_000_000}, now=NOW)
        state = PlanState(session, _class_map(), TODAY)
        pat = state.patrimony_json()
        buckets = {b["bucket"]: b for b in pat["buckets"]}
        assert (
            buckets["acoes_nucleo"]["current"],
            buckets["acoes_mantidas"]["current"],
            buckets["satelite"]["current"],
        ) == (50_000, 100_000, 150_000)
        _, _, split = month_plan(state, pat, "2026-12", prices)
        tickers = {i.ticker for i in split.items}
        assert "ACAA3" in tickers and not tickers & {"CCCC3", "XPTO34"}


def test_core_weights_equal_current_proportion_and_custom():
    core = {"ACAA3": 100_000, "BBBB3": 20_000, "DDDD3": 0}
    assert core_weights(core, "iguais", None) == {"ACAA3": 1, "BBBB3": 1, "DDDD3": 1}
    assert core_weights(core, "atual", None) == {"ACAA3": 100_000, "BBBB3": 20_000, "DDDD3": 0}
    assert core_weights(core, "personalizado", {"ACAA3": 50, "BBBB3": 30, "DDDD3": 20}) == {
        "ACAA3": 50,
        "BBBB3": 30,
        "DDDD3": 20,
    }
    # sem dados para o modo pedido, vale "iguais"
    assert core_weights({"ACAA3": 0}, "atual", None) == {"ACAA3": 1}
    assert core_weights(core, "personalizado", {"ACAA3": 100}) == {"ACAA3": 1, "BBBB3": 1, "DDDD3": 1}
    two = {"ACAA3": 100_000, "BBBB3": 20_000}
    only_core = {"renda_fixa": 0, "etf_global": 0, "etf_brasil": 0, "acoes_nucleo": 100, "fiis": 0, "satelite": 0}
    values = {"acoes_nucleo": 120_000}

    def spend(weights):
        result = split_patrimony(60_000, only_core, values, two, {}, {}, weights)
        return {i.ticker: i.spend_cents for i in result.items}

    # iguais: nível L com (L/2 − 1.000) + (L/2 − 200) = 600 -> L = 1.800: ACAA3 já passou de 900; tudo para BBBB3
    assert spend(core_weights(two, "iguais", None)) == {"BBBB3": 60_000}
    # proporção atual (5:1): cada uma recebe na proporção do que já tem -> 500 e 100
    assert spend(core_weights(two, "atual", None)) == {"ACAA3": 50_000, "BBBB3": 10_000}
    # personalizado 75/25: total 1.800 -> alvos 1.350 e 450: ACAA3 +350, BBBB3 +250
    assert spend(core_weights(two, "personalizado", {"ACAA3": 75, "BBBB3": 25})) == {"ACAA3": 35_000, "BBBB3": 25_000}


def test_core_above_target_gets_nothing_until_the_others_catch_up(ledger, session_factory):
    _stocks_etf_and_fii(ledger)
    with session_factory() as session:
        S.save(session, S.PATRIMONY_TARGET, "2026-11", {"classes": ALLOC, "etf_global": "GLOB11"}, now=NOW)
        # ACAA3 + CCCC3 no núcleo = 1.500 de 7.000 = 21,4% (alvo 10%): acima do alvo
        S.save(session, S.CORE, "2026-11", {"tickers": ["ACAA3", "CCCC3"]}, now=NOW)
        state = PlanState(session, _class_map(), TODAY)
        pat = state.patrimony_json()
        core = next(b for b in pat["buckets"] if b["bucket"] == "acoes_nucleo")
        assert core["state"] == "acima" and core["suggested"]
        _, _, split = month_plan(state, pat, "2026-12", {})
        assert split.buckets["acoes_nucleo"] == 0 and split.buckets["renda_fixa"] > 0
        # peso de cada empresa na tela: iguais = metade do alvo do núcleo (5% do Patrimônio) cada
        assert {c["ticker"]: c["target_pct"] for c in pat["core"]} == {
            "CCCC3": pytest.approx(0.05),
            "ACAA3": pytest.approx(0.05),
        }


# ------------------------------------------------------------------ "O que fazer este mês": checklist


def _checklist_setup(ledger: Ledger, session) -> None:
    _fixed_income_and_etf(ledger)  # CDB 3.000, Tesouro 4.100, GLOB11 1.000 (cotação R$ 100)
    S.save(session, S.MONTHLY_TARGET, "2026-11", {"cents": 300_000}, now=NOW)
    S.save(session, S.RESERVE, "2026-11", {"cents": 730_000, "order": ["CDB/RDB", "Tesouro"]}, now=NOW)
    S.save(
        session,
        S.PATRIMONY_TARGET,
        "2026-11",
        {
            "classes": {
                "renda_fixa": 50,
                "etf_global": 50,
                "etf_brasil": 0,
                "acoes_nucleo": 0,
                "fiis": 0,
                "satelite": 0,
            },
            "etf_global": "GLOB11",
        },
        now=NOW,
    )


def test_checklist_reserve_first_then_patrimony_and_ticks_when_contribution_is_detected(ledger, session_factory):
    with session_factory() as session:
        _checklist_setup(ledger, session)
        state = PlanState(session, _class_map(), TODAY)
        pat = state.patrimony_json()
        # Reserva: 7.100 de 7.300 -> R$ 200 vão primeiro para ela; sobram 2.800 para o Patrimônio (hoje só o ETF, com
        # 1.000): nível igual entre renda fixa (0) e ETF (1.000) -> renda fixa 1.900, ETF 900 = 9 cotas de R$ 100
        data, split, _ = month_plan(state, pat, "2026-12", {"GLOB11": 10_000})
        assert split.amounts == {RESERVE: 20_000, PATRIMONY: 280_000} and data["reserve_priority"]["cents"] == 20_000
        assert [(line["amount"], line["where"], line["shares"], line["done"]) for line in data["checklist"]] == [
            (20_000, "CDB de liquidez diária (para a Reserva de emergência)", None, False),
            (90_000, "GLOB11", 9, False),
            (190_000, "renda fixa (Tesouro Selic ou CDB de liquidez diária)", None, False),
        ]
        assert sum(line["amount"] for line in data["checklist"]) == data["total"] == 300_000
        # o app detecta a compra do ETF (a cotação mudou um pouco: 95% do valor já marca) e parte da renda fixa
        detected = {(PATRIMONY, "GLOB11"): 86_000, (PATRIMONY, "rf"): 100_000, (RESERVE, "rf"): 20_000}
        reserve, etf, fixed = month_plan(state, pat, "2026-12", {"GLOB11": 10_000}, detected)[0]["checklist"]
        assert (reserve["done"], etf["done"], fixed["done"]) == (True, True, False) and fixed["detected"] == 100_000
        # comprar uma ação fora da lista não marca nenhuma linha; resgate não conta como aporte feito
        other = {(PATRIMONY, "rf"): 185_000, (PATRIMONY, "ACAO3"): 40_000, (RESERVE, "rf"): -50_000}
        reserve, etf, fixed = month_plan(state, pat, "2026-12", {"GLOB11": 10_000}, other)[0]["checklist"]
        assert fixed["done"] and fixed["detected"] == 185_000 and reserve["detected"] == 0 and not etf["done"]


def test_checklist_has_at_most_five_lines_and_keeps_the_total():
    lines = _checklist(
        [{"where": f"ACAO{i}", "ticker": f"ACAO{i}", "amount": 1_000 * (i + 1), "detected": 0} for i in range(8)]
    )
    assert len(lines) == 5 and sum(line["amount"] for line in lines) == 36_000
    assert lines[-1]["where"] == "outras compras menores: ACAO0, ACAO1, ACAO2, ACAO3" and lines[-1]["amount"] == 10_000
    # o mesmo investimento vindo de duas origens vira uma linha só; valor zero não aparece
    merged = _checklist(
        [
            {"where": "ACAO1", "amount": 5_000, "detected": 5_000, "shares": 1},
            {"where": "ACAO1", "amount": 5_000, "detected": 4_600, "shares": 1},
            {"where": "ACAO2", "amount": 0, "detected": 0},
        ]
    )
    assert merged == [
        {
            "where": "ACAO1",
            "amount": 10_000,
            "detected": 9_600,
            "shares": 2,
            "price": None,
            "ticker": None,
            "done": True,
        }
    ]


def test_next_month_preview_only_in_the_last_five_days(ledger, session_factory):
    with session_factory() as session:
        _checklist_setup(ledger, session)
        session.commit()
        assert (
            plan(session, _class_map(), today=date(2026, 11, 25), now=NOW, with_history=False)["contribution"]["next"]
            is None
        )
        late = plan(session, _class_map(), today=date(2026, 11, 26), now=NOW, with_history=False)["contribution"]
        assert late["next"]["month"] == "2026-12" and late["next"]["total"] == 300_000
        assert late["next"]["checklist"] and all(line["done"] is False for line in late["next"]["checklist"])


def test_stale_data_alert_after_36_hours():
    assert stale_hours(datetime(2026, 11, 19, 0, 0), NOW) is None  # 36 h exatas: ainda em dia
    assert stale_hours(datetime(2026, 11, 18, 23, 0), NOW) == 37
    assert stale_hours(None, NOW) is None


# ------------------------------------------------------------------ aportes claros e gastos


def test_contributed_redeemed_and_balance_never_only_net():
    assert flows_json(150_000, 250_000) == {
        "contributions": 150_000,
        "redemptions": 250_000,
        "net": -100_000,
        "shrinking": True,
    }
    assert flows_json(100_000, 0)["shrinking"] is False


def test_portfolio_change_split_into_new_money_and_growth(ledger, session_factory):
    # fotos 31/10: 1.000; 30/11: 1.560; aporte 500 em 05/11; provento 10 pago na conta em 15/11
    ledger.snapshot(date(2026, 10, 31), INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(date(2026, 11, 30), INVESTMENT, quantity=15, unit_value=104, balance=1560)
    ledger.tx(BANK, date(2026, 11, 5), -500.0, "Aplicação RDB")
    ledger.tx(BANK, date(2026, 11, 15), 10.0, "Valor recebido de Investimentos")
    ledger.classify()
    with session_factory() as session:
        row = investments_month(session, "2026-11", date(2026, 12, 2))
    # variação 560 = aportes − resgates (500) + rendimento (60); o provento (10) foi pago na conta, à parte
    assert (row["change"], row["net_flows"], row["growth"], row["income"]) == (56_000, 50_000, 6_000, 1_000)


def test_extraordinary_expenses_are_separated_and_paid_with_redemptions(ledger, session_factory):
    ledger.tx(
        BANK,
        date(2026, 11, 2),
        1000.0,
        "Transferência Recebida|EMPREGADOR FICTICIO LTDA",
        payment_data={"payer": company("EMPREGADOR FICTICIO LTDA")},
    )
    ledger.tx(CARD, date(2026, 11, 5), -600.0, "Feira Ficticia")
    trip = ledger.tx(CARD, date(2026, 11, 6), -2400.0, "Hotel Ficticio")
    ledger.tx(BANK, date(2026, 11, 7), -500.0, "Aplicação RDB")
    ledger.tx(BANK, date(2026, 11, 8), 2500.0, "Resgate RDB")
    with session_factory() as session:
        session.add(ClassificationOverride(transaction_id=trip, extraordinary=True, created_at=NOW, updated_at=NOW))
        session.commit()
    ledger.classify()
    with session_factory() as session:
        s = month_summary(session, "2026-11")
    # despesas 3.000 = dia a dia 600 + extraordinário 2.400; sobra −2.000, sem o extraordinário +400
    assert (s.expenses_total_cents, s.extraordinary_cents, s.everyday_cents) == (300_000, 240_000, 60_000)
    assert s.result_cents == -200_000 and s.result_everyday_cents == 40_000 and s.savings_rate_everyday == 0.4
    # a renda (1.000) não cobriu 2.000 das despesas; resgates − aportes = 2.000 -> pagos com resgates 2.000
    assert s.paid_with_redemptions_cents == 200_000


def test_capacity_uses_only_everyday_average(ledger, session_factory):
    _salary_and_history(ledger, 1000.0)
    repair = ledger.tx(CARD, date(2026, 9, 12), -3000.0, "Oficina Ficticia")  # extraordinário: fora da média
    with session_factory() as session:
        session.add(ClassificationOverride(transaction_id=repair, extraordinary=True, created_at=NOW, updated_at=NOW))
        session.commit()
    ledger.classify()
    with session_factory() as session:
        cap = month_capacity(session, "2026-11", today=TODAY, cushion_cents=20_000)
        assert session.get(Transaction, repair) is not None
    assert cap.variable_daily_cents == round((96_100 + 90_000 + 96_100) / 92)  # sem os 3.000 da oficina


def test_aspirational_target_line():
    assert target_return(0.12, date(2026, 1, 1), date(2027, 1, 1)) == pytest.approx(0.12)
    assert target_return(0.12, date(2026, 1, 1), date(2026, 7, 2)) == pytest.approx(1.12 ** (182 / 365) - 1)
    assert target_return(0.12, date(2026, 1, 1), date(2026, 1, 1)) == 0


# ------------------------------------------------------------------ capacidade do mês


def _salary_and_history(ledger: Ledger, weekly: float) -> None:
    payer = {"payer": company("EMPREGADOR FICTICIO LTDA")}
    day = date(2026, 6, 1)
    while day <= date(2026, 11, 17):
        if day.weekday() == 0:
            ledger.tx(BANK, day, weekly, "Transferência Recebida|EMPREGADOR FICTICIO LTDA", payment_data=payer)
        day = date.fromordinal(day.toordinal() + 1)
    # variáveis: R$ 961 em agosto e outubro, R$ 900 em setembro (lojas diferentes: não vira gasto fixo)
    for month, amount, shop in (
        (8, 961.0, "Feira Ficticia"),
        (9, 900.0, "Sacolao Ficticio"),
        (10, 961.0, "Quitanda Ficticia"),
    ):
        ledger.tx(CARD, date(2026, month, 10), -amount, shop)


def test_capacity_in_a_comfortable_month(ledger, session_factory):
    _salary_and_history(ledger, 1000.0)
    ledger.tx(CARD, date(2026, 11, 5), -400.0, "Feira Ficticia")
    ledger.tx(BANK, date(2026, 11, 6), -500.0, "Aplicação RDB")
    ledger.tx(BANK, date(2026, 11, 9), 100.0, "Resgate RDB")
    ledger.account_snapshot(date(2026, 11, 20), BANK, 5000)
    ledger.account_snapshot(date(2026, 11, 20), CARD, 400)
    ledger.snapshot(date(2026, 11, 20), INVESTMENT, quantity=1, unit_value=10, balance=10)
    ledger.classify()
    with session_factory() as session:
        cap = month_capacity(session, "2026-11", today=date(2026, 11, 20), cushion_cents=20_000)
    # recebido: segundas 2, 9 e 16 = 3.000; faltam as segundas 23 e 30 = 2.000
    assert cap.income_cents == 300_000 and cap.salary_remaining_cents == 200_000
    # variáveis: (961 + 900 + 961) / 92 dias = 30,67/dia × 10 dias restantes = 306,74
    assert cap.variable_daily_cents == round((96_100 + 90_000 + 96_100) / 92)
    assert cap.days_remaining == 10 and cap.variable_estimate_cents == cap.variable_daily_cents * 10
    assert cap.expenses_cents == 40_000 and cap.contributions_net_cents == 40_000
    expected = 300_000 + 200_000 - 40_000 - 0 - cap.variable_estimate_cents
    assert cap.projected_surplus_cents == expected and cap.capacity_cents == expected - 40_000
    # caixa: 5.000 − 400 − 200 = 4.400; capacidade (~3.893) cabe no caixa: não depende de salário futuro
    assert cap.cash_available_cents == 440_000 and not cap.depends_on_future_salary


def test_capacity_in_a_tight_month_warns_about_future_salary(ledger, session_factory):
    _salary_and_history(ledger, 1000.0)
    ledger.tx(CARD, date(2026, 11, 5), -2600.0, "Loja Ficticia de Moveis")
    ledger.account_snapshot(date(2026, 11, 20), BANK, 600)
    ledger.account_snapshot(date(2026, 11, 20), CARD, 2600)
    ledger.snapshot(date(2026, 11, 20), INVESTMENT, quantity=1, unit_value=10, balance=10)
    ledger.classify()
    with session_factory() as session:
        cap = month_capacity(session, "2026-11", today=date(2026, 11, 20), cushion_cents=20_000)
    # 3.000 + 2.000 − 2.600 − 306,74 = 2.093,26 projetados, mas o caixa hoje é negativo (600 − 2.600 − 200)
    assert cap.variable_estimate_cents == round((96_100 + 90_000 + 96_100) / 92) * 10
    assert cap.capacity_cents == 300_000 + 200_000 - 260_000 - cap.variable_estimate_cents
    assert cap.cash_available_cents == -220_000 and cap.depends_on_future_salary


def test_closed_month_shows_real_surplus(ledger, session_factory):
    _salary_and_history(ledger, 1000.0)
    ledger.tx(BANK, date(2026, 10, 20), -700.0, "Aplicação RDB")
    ledger.classify()
    with session_factory() as session:
        cap = month_capacity(session, "2026-10", today=date(2026, 11, 20), cushion_cents=20_000)
    # outubro: segundas 5, 12, 19, 26 = 4.000; variáveis 961; sem projeções
    assert cap.closed and cap.salary_remaining_cents == 0 and cap.variable_estimate_cents == 0
    assert cap.projected_surplus_cents == 400_000 - 96_100 and cap.contributions_net_cents == 70_000


# ------------------------------------------------------------------ investimentos


def test_gross_is_the_main_value_and_net_is_kept(ledger, session_factory):
    treasury = ledger.investment(None, "FIXED_INCOME", "TREASURY", name="TESOURO FICTICIO")
    ledger.snapshot(date(2026, 11, 19), treasury, quantity=1, unit_value=None, balance=995, amount=1000)
    with session_factory() as session:
        [p] = positions(session, load_class_map(CONFIG_DIR, None))
    assert (p.value_cents, p.net_cents) == (100_000, 99_500)


def test_monthly_gain_and_twr_match_hand_calculation(ledger, session_factory):
    # fotos 29/10 e 31/10: 1.000. Aporte de 500 em 05/11 (débito na conta). Foto 30/11: 1.560. Provento 10 em 15/11.
    ledger.snapshot(date(2026, 10, 29), INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(date(2026, 10, 31), INVESTMENT, quantity=10, unit_value=100, balance=1000)
    ledger.snapshot(date(2026, 11, 30), INVESTMENT, quantity=15, unit_value=104, balance=1560)
    ledger.tx(BANK, date(2026, 11, 5), -500.0, "Aplicação RDB")
    ledger.tx(BANK, date(2026, 11, 15), 10.0, "Valor recebido de Investimentos")
    ledger.classify()
    with session_factory() as session:
        [october, november] = monthly_returns(portfolio_series(session), date(2026, 12, 2))
    assert october.month == "2026-10" and october.partial_since == date(2026, 10, 29)  # fotos só desde 29/10
    assert november.partial_since is None and november.start == date(2026, 10, 31)
    assert (november.start_value, november.end_value, november.contributions, november.redemptions) == (
        100_000,
        156_000,
        50_000,
        0,
    )
    # ganho = variação − aportes + resgates + proventos = 560 − 500 + 0 + 10 = 70
    assert november.gain == 7_000 and november.income == 1_000
    # Dietz modificado: peso do aporte = 25/30; base = 1.000 + 500 × 25/30 = 1.416,67; TWR = 70 / 1.416,67
    assert november.twr == pytest.approx(70 / (1000 + 500 * 25 / 30), rel=1e-9)
    assert not november.in_progress


def test_dividends_by_class_and_asset_per_month(ledger, session_factory):
    stock = ledger.investment("ACAO3", "EQUITY", "STOCK")
    ledger.investment_tx(date(2026, 10, 15), "DIVIDEND", 12.0)  # FICT11 (FII)
    ledger.investment_tx(date(2026, 11, 15), "DIVIDEND", 8.0)
    ledger.investment_tx(date(2026, 11, 20), "JCP", 5.0, investment=stock)
    with session_factory() as session:
        months = dividends_by_class(session, load_class_map(CONFIG_DIR, None), date(2026, 11, 20))
    by_month = {m.month: m for m in months}
    assert len(months) == 12
    assert by_month["2026-10"].by_class == {"FIIs": 1_200}
    assert by_month["2026-11"].by_class == {"Ações": 500, "FIIs": 800} and by_month["2026-11"].total_cents == 1_300
    assert by_month["2026-11"].by_asset == {"FICT11": 800, "ACAO3": 500}
