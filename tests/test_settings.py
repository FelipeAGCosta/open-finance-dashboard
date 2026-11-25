"""Configuração genérica: agenda do salário, settings.yaml, itens da Pluggy e valores iniciais do Plano."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from findash.classify.salary import BIWEEKLY, MONTHLY, WEEKLY, SalarySchedule
from findash.classify.summary import month_summary
from findash.config import ConfigError, ItemConfig, Paths, load_settings, parse_items
from findash.db.models import RecurringRule
from findash.plan import settings as S
from findash.settings import SettingsError, load_app_settings
from ledger import BANK, Ledger, company

NOW = datetime(2026, 11, 20, 12, 0)


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def _paths(tmp_path, personal: str | None = None) -> Paths:
    paths = Paths(tmp_path)
    paths.ensure()
    if personal is not None:
        (paths.data_dir / "settings.yaml").write_text(personal, encoding="utf-8")
    return paths


# ------------------------------------------------------------------ agenda do salário


def test_monthly_schedule_accepts_late_payment_and_clamps_short_months():
    schedule = SalarySchedule(MONTHLY, payday=31, grace_days=3)
    assert schedule.paydays_in_month("2026-02") == [date(2026, 2, 28)]
    assert schedule.reference_payday(date(2026, 3, 2)) == date(2026, 2, 28)  # 2 dias depois, já em março
    assert schedule.reference_payday(date(2026, 3, 10)) is None
    assert schedule.extra_paychecks("2026-05") == 0
    assert schedule.monthly_average_cents(500_000) == 500_000


def test_biweekly_schedule_follows_the_first_payment():
    schedule = SalarySchedule(BIWEEKLY, payday=4, grace_days=2)  # sexta, a cada 2 semanas
    anchor = date(2026, 1, 2)
    assert schedule.paydays_in_month("2026-01", anchor) == [date(2026, 1, 2), date(2026, 1, 16), date(2026, 1, 30)]
    assert schedule.extra_paychecks("2026-01", anchor) == 1
    assert schedule.reference_payday(date(2026, 1, 9), anchor) is None  # sexta da semana "errada"
    assert schedule.monthly_average_cents(200_000) == round(200_000 * 26 / 12)


def test_schedule_rejects_invalid_values():
    with pytest.raises(ValueError):
        SalarySchedule("diario")
    with pytest.raises(ValueError):
        SalarySchedule(WEEKLY, payday=9)
    with pytest.raises(ValueError):
        SalarySchedule(MONTHLY, payday=0)


def test_monthly_salary_on_schedule_keeps_the_paycheck_and_checks_the_month(ledger, session_factory):
    ledger.salary = SalarySchedule(MONTHLY, payday=5, grace_days=3)
    payer = {"payer": company("Empregadora Exemplo")}
    for month, day in ((6, 5), (7, 6), (8, 5), (9, 8), (10, 5)):  # setembro: dia 8, ainda dentro da tolerância
        ledger.tx(BANK, date(2026, month, day), 4200, "Transferência Recebida|EMPREGADORA EXEMPLO", payment_data=payer)
    ledger.classify()
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.kind == "salario"))
        assert (rule.paycheck_cents, rule.pay_frequency, rule.payday, rule.avg_monthly_cents) == (
            420_000,
            MONTHLY,
            5,
            420_000,
        )
        [september] = month_summary(session, "2026-09").salaries
    assert (september.expected_cents, september.received_reference_cents, september.divergent) == (
        420_000,
        420_000,
        False,
    )


def test_biweekly_salary_is_detected_with_its_schedule(ledger, session_factory):
    ledger.salary = SalarySchedule(BIWEEKLY, payday=4, grace_days=2)
    day = date(2026, 6, 5)
    while day <= date(2026, 10, 30):
        ledger.tx(BANK, day, 1800, "Transferência Recebida|EMPREGADORA QUINZENAL", payment_data={"payer": company("X")})
        day += timedelta(days=14)
    ledger.classify()
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.kind == "salario"))
        assert (rule.paycheck_cents, rule.pay_frequency, rule.payday) == (180_000, BIWEEKLY, 4)
        [july] = month_summary(session, "2026-07").salaries
    assert ([d.day for d in july.paydays], july.divergent) == ([3, 17, 31], False)


# ------------------------------------------------------------------ settings.yaml


def test_versioned_settings_are_valid_and_generic(tmp_path):
    settings = load_app_settings(_paths(tmp_path))
    assert settings.salary == SalarySchedule(MONTHLY, payday=5, grace_days=3)
    assert sum(settings.plan.target_allocation.values()) == 100
    S.initial_values(settings.plan)  # passa na mesma validação das gravações da tela


def test_personal_settings_override_field_by_field(tmp_path):
    paths = _paths(tmp_path, "salario:\n  frequencia: semanal\n  dia: Sexta-feira\nplano:\n  reserva: 5000\n")
    settings = load_app_settings(paths)
    assert (settings.salary.frequency, settings.salary.payday, settings.salary.grace_days) == (WEEKLY, 4, 3)
    assert settings.plan.reserve_cents == 500_000
    assert settings.plan.monthly_contribution_cents == 100_000  # veio do arquivo versionado


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("salario:\n  frequencia: anual\n", "frequencia"),
        ("salario:\n  frequencia: semanal\n  dia: 5\n", "segunda, terca"),
        ("salario:\n  frequencia: mensal\n  dia: segunda\n", "dia do mês"),
        ("plano:\n  aporte_mensal: -1\n", "aporte_mensal"),
        ("plano:\n  meta_rentabilidade: 12\n", "meta_rentabilidade"),
    ],
)
def test_invalid_settings_are_reported_clearly(tmp_path, content, message):
    with pytest.raises(SettingsError) as caught:
        load_app_settings(_paths(tmp_path, content))
    assert message in str(caught.value)


def test_initial_plan_values_are_saved_once(session_factory, tmp_path):
    defaults = load_app_settings(_paths(tmp_path)).plan
    with session_factory() as session:
        S.ensure_initial(session, "2026-11", defaults, now=NOW)
        S.save(session, S.RESERVE, "2026-11", {"cents": 300_000, "order": ["Tesouro"]}, now=NOW)
        S.ensure_initial(session, "2026-12", defaults, now=NOW)  # não sobrescreve a escolha feita na tela
        assert S.value_at(session, S.RESERVE, "2026-12").value == {"cents": 300_000, "order": ["Tesouro"]}
        assert S.value_at(session, S.PATRIMONY_TARGET, "2026-12").value["classes"]["renda_fixa"] == 40
        assert S.value_at(session, S.MONTHLY_TARGET, "2026-12").effective_month == "2026-11"


def test_allocation_that_does_not_sum_100_is_refused(tmp_path):
    paths = _paths(tmp_path, "plano:\n  alvo_patrimonio:\n    renda_fixa: 50\n")
    with pytest.raises(S.PlanError) as caught:
        S.initial_values(load_app_settings(paths).plan)
    assert "settings.yaml" in str(caught.value)


# ------------------------------------------------------------------ itens da Pluggy


def test_several_items_with_institution_profiles():
    assert parse_items("aaa:nubank, bbb ,") == (ItemConfig("aaa", "nubank"), ItemConfig("bbb", "generic"))
    with pytest.raises(ConfigError):
        parse_items("aaa:banco-inexistente")
    with pytest.raises(ConfigError):
        parse_items("aaa,aaa")


def test_single_item_variable_still_works(tmp_path, monkeypatch):
    for name in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS", "PLUGGY_ITEM_ID"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "PLUGGY_CLIENT_ID=x\nPLUGGY_CLIENT_SECRET=segredo-ficticio\nPLUGGY_ITEM_ID=item-1\n", encoding="utf-8"
    )
    assert load_settings(tmp_path).items == (ItemConfig("item-1"),)
