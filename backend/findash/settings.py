"""Preferências do app (nada secreto): config/settings.yaml, sobrescrito campo a campo por data/settings.yaml.

O arquivo versionado traz valores genéricos; o de data/ (fora do Git) guarda os seus. Credenciais
continuam só no arquivo de ambiente (.env).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from findash.classify.salary import BIWEEKLY, MONTHLY, WEEKLY, SalarySchedule
from findash.config import Paths

SETTINGS_FILE = "settings.yaml"
_FREQUENCIES = {
    "semanal": WEEKLY,
    "quinzenal": BIWEEKLY,
    "mensal": MONTHLY,
    WEEKLY: WEEKLY,
    BIWEEKLY: BIWEEKLY,
    MONTHLY: MONTHLY,
}
_WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
}


class SettingsError(Exception):
    """settings.yaml inválido. A mensagem diz o arquivo e o campo."""


@dataclass(frozen=True)
class PlanDefaults:
    """Valores iniciais das metas do Plano: gravados quando a meta ainda não existe no banco."""

    monthly_contribution_cents: int
    extra_paycheck: bool
    cash_cushion_cents: int
    reserve_cents: int | None
    target_allocation: dict[str, float] | None
    assumed_return: float
    aspirational_return: float


@dataclass(frozen=True)
class AppSettings:
    salary: SalarySchedule
    plan: PlanDefaults


def load_app_settings(paths: Paths) -> AppSettings:
    data = _read(paths.config_dir / SETTINGS_FILE)
    personal = paths.data_dir / SETTINGS_FILE
    if personal.exists():
        data = _deep_merge(data, _read(personal))
    return AppSettings(salary=_salary(data.get("salario") or {}), plan=_plan(data.get("plano") or {}))


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SettingsError(f"arquivo não encontrado: {path.name}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SettingsError(f"{path.name}: YAML inválido: {exc}") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path.name}: esperado um bloco com 'salario' e 'plano'")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _plain(text: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(text).strip().lower())
    return "".join(c for c in normalized if not unicodedata.combining(c)).removesuffix("-feira")


def _salary(block: dict[str, Any]) -> SalarySchedule:
    frequency = _FREQUENCIES.get(_plain(block.get("frequencia", "mensal")))
    if frequency is None:
        raise SettingsError("salario.frequencia: use semanal, quinzenal ou mensal")
    raw_day = block.get("dia", 5)
    if frequency == MONTHLY:
        if isinstance(raw_day, bool) or not isinstance(raw_day, int):
            raise SettingsError("salario.dia: no salário mensal, informe o dia do mês (1 a 31)")
        payday = raw_day
    else:
        payday = _WEEKDAYS.get(_plain(raw_day), -1)
        if payday < 0:
            raise SettingsError(
                "salario.dia: no salário semanal/quinzenal, use segunda, terca, quarta, quinta ou sexta"
            )
    try:
        return SalarySchedule(frequency, payday, int(block.get("tolerancia_dias", 3)))
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"salario: {exc}") from None


def _cents(value: Any, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise SettingsError(f"plano.{field}: informe um valor em reais maior ou igual a zero")
    return round(value * 100)


def _rate(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 0.5:
        raise SettingsError(f"plano.{field}: use uma taxa anual entre 0 e 0.5 (ex.: 0.10 = 10%)")
    return float(value)


def _plan(block: dict[str, Any]) -> PlanDefaults:
    allocation = block.get("alvo_patrimonio")
    if allocation is not None and (
        not isinstance(allocation, dict) or not all(isinstance(v, (int, float)) for v in allocation.values())
    ):
        raise SettingsError("plano.alvo_patrimonio: percentuais por classe (renda_fixa, etf_global, ...)")
    extra = block.get("extra_salario", False)
    if not isinstance(extra, bool):
        raise SettingsError("plano.extra_salario: use true ou false")
    return PlanDefaults(
        monthly_contribution_cents=_cents(block.get("aporte_mensal", 1000), "aporte_mensal"),
        extra_paycheck=extra,
        cash_cushion_cents=_cents(block.get("colchao", 200), "colchao"),
        reserve_cents=_cents(block.get("reserva"), "reserva", optional=True),
        target_allocation={str(k): float(v) for k, v in allocation.items()} if allocation else None,
        assumed_return=_rate(block.get("rentabilidade_esperada", 0.10), "rentabilidade_esperada"),
        aspirational_return=_rate(block.get("meta_rentabilidade", 0.12), "meta_rentabilidade"),
    )
