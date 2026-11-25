"""Metas do Plano com histórico de vigência (tabela plan_settings).

Uma gravação vale do mês escolhido em diante; o valor de uma chave no mês M é o da gravação mais
recente com effective_month <= M (empate: a gravada por último). Meses passados mantêm a meta da época.
Campos ainda não definidos pelo usuário ficam vazios (None): a tela guia o preenchimento, nada é inventado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import PlanSetting
from findash.settings import PlanDefaults

MONTHLY_TARGET = "aporte_mensal"  # {"cents": int, "extra_paycheck": bool}: meta base + pagamento extra do salário
CASH_CUSHION = "colchao"  # {"cents": int}
RESERVE = "reserva"  # {"cents": int|None, "order": [classe de renda fixa, ...]}
PATRIMONY_TARGET = (
    "alvo_patrimonio"  # {"classes": {balde: pct|None}, "etf_global": ticker|None, "etf_brasil": ticker|None}
)
# papel de cada ação/BDR (sem marcação = manter) e o peso de cada empresa dentro do núcleo
# {"tickers": [núcleo], "satellite": [satélite], "weights": "iguais" | "atual" | "personalizado", "custom": {ticker: %}}
CORE = "nucleo"
RETURNS = "rentabilidade"  # {"assumed": taxa a.a. padrão da calculadora, "aspirational": meta a.a. dos gráficos}

# Classes da alocação-alvo do Patrimônio (soma 100%). Satélite é um TETO; FIIs e satélite nunca recebem sugestão.
BUCKETS = ("renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo", "fiis", "satelite")
BUCKET_LABELS = {
    "renda_fixa": "Renda fixa",
    "etf_global": "ETF Global",
    "etf_brasil": "ETF Brasil",
    "acoes_nucleo": "Ações brasileiras (núcleo)",
    "fiis": "FIIs",
    "satelite": "Satélite",
    "acoes_mantidas": "Ações mantidas",
}
# Na tela entra também "Ações mantidas": ações/BDRs que só se acompanham (sem alvo e sem aporte, como os FIIs).
DISPLAY_BUCKETS = ("renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo", "fiis", "acoes_mantidas", "satelite")
WEIGHT_MODES = ("iguais", "atual", "personalizado")
DEFAULT_ASSUMED_RATE = 0.10
DEFAULT_ASPIRATIONAL_RATE = 0.12
FIXED_INCOME_ORDER = ("CDB/RDB", "Tesouro")

DEFAULTS: dict[str, Any] = {
    MONTHLY_TARGET: {"cents": 100_000, "extra_paycheck": False},
    CASH_CUSHION: {"cents": 20_000},
    RESERVE: {"cents": None, "order": list(FIXED_INCOME_ORDER)},
    PATRIMONY_TARGET: {"classes": {b: None for b in BUCKETS}, "etf_global": None, "etf_brasil": None},
    CORE: {"tickers": [], "satellite": [], "weights": "iguais", "custom": {}},
    RETURNS: {"assumed": DEFAULT_ASSUMED_RATE, "aspirational": DEFAULT_ASPIRATIONAL_RATE},
}
KEYS = tuple(DEFAULTS)
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
TICKER = re.compile(r"^[A-Z0-9]{4,12}$")


class PlanError(ValueError):
    """Valor de meta inválido (mensagem pronta para a tela)."""


@dataclass
class Setting:
    key: str
    value: Any
    effective_month: str | None  # None = valor padrão (nunca gravado)
    id: int | None


def value_at(session: Session, key: str, month: str) -> Setting:
    row = session.scalars(
        select(PlanSetting)
        .where(PlanSetting.key == key, PlanSetting.effective_month <= month)
        .order_by(PlanSetting.effective_month.desc(), PlanSetting.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return Setting(key, DEFAULTS[key], None, None)
    return Setting(key, merged(key, row.value_json), row.effective_month, row.id)


def merged(key: str, value: dict) -> dict:
    """Valor gravado sobre os padrões, só com os campos atuais (gravações antigas tinham campos que saíram)."""
    return {k: value.get(k, default) for k, default in DEFAULTS[key].items()}


def history(session: Session, key: str) -> list[PlanSetting]:
    return list(
        session.scalars(
            select(PlanSetting).where(PlanSetting.key == key).order_by(PlanSetting.effective_month, PlanSetting.id)
        )
    )


def first_month(session: Session, key: str) -> str | None:
    rows = history(session, key)
    return rows[0].effective_month if rows else None


def changes(session: Session, key: str) -> list[PlanSetting]:
    """Histórico só com mudanças reais: a última gravação de cada mês, sem repetir o valor anterior."""
    last_of_month: dict[str, PlanSetting] = {}
    for row in history(session, key):
        last_of_month[row.effective_month] = row
    out: list[PlanSetting] = []
    for row in last_of_month.values():
        if not out or merged(key, out[-1].value_json) != merged(key, row.value_json):
            out.append(row)
    return out


def save(
    session: Session, key: str, effective_month: str, value: Any, *, now: datetime, force: bool = False
) -> PlanSetting | None:
    """Grava a meta; devolve None (e não grava) quando o valor já é o que vale naquele mês."""
    if key not in DEFAULTS:
        raise PlanError("Meta desconhecida.")
    if not isinstance(effective_month, str) or not MONTH.match(effective_month):
        raise PlanError("Escolha o mês em que a mudança começa a valer.")
    clean = validate(key, value)
    if not force and value_at(session, key, effective_month).value == merged(key, clean):
        return None
    row = PlanSetting(key=key, effective_month=effective_month, value_json=clean, created_at=now)
    session.add(row)
    session.flush()
    return row


def delete(session: Session, setting_id: int) -> bool:
    row = session.get(PlanSetting, setting_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def initial_values(defaults: PlanDefaults) -> dict[str, Any]:
    """Valores iniciais das metas a partir de settings.yaml (validados como qualquer gravação)."""
    classes = defaults.target_allocation or {}
    values = {
        MONTHLY_TARGET: {"cents": defaults.monthly_contribution_cents, "extra_paycheck": defaults.extra_paycheck},
        CASH_CUSHION: {"cents": defaults.cash_cushion_cents},
        RESERVE: {"cents": defaults.reserve_cents, "order": list(FIXED_INCOME_ORDER)},
        PATRIMONY_TARGET: {"classes": {b: classes.get(b) for b in BUCKETS}, "etf_global": None, "etf_brasil": None},
        RETURNS: {"assumed": defaults.assumed_return, "aspirational": defaults.aspirational_return},
    }
    try:
        return {key: validate(key, value) for key, value in values.items()}
    except PlanError as exc:
        raise PlanError(f"settings.yaml (plano): {exc}") from None


def ensure_initial(session: Session, month: str, defaults: PlanDefaults, *, now: datetime) -> None:
    """Grava, a partir do mês dado, as metas que ainda não existem no banco (uma vez só)."""
    for key, value in initial_values(defaults).items():
        if first_month(session, key) is None:
            save(session, key, month, value, now=now, force=True)


# ------------------------------------------------------------------ validação


def _cents(value: Any, label: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanError(f"{label}: informe um valor em reais maior ou igual a zero.")
    return value


def _pct(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        raise PlanError(f"{label}: use um percentual entre 0 e 100.")
    return round(float(value), 2)


def _sum_100(values: list[float | None], label: str) -> None:
    filled = [v for v in values if v is not None]
    if not filled:
        return
    if len(filled) != len(values):
        raise PlanError(f"{label}: preencha todos os percentuais (ou deixe todos vazios).")
    if abs(sum(filled) - 100) > 0.01:
        raise PlanError(f"{label}: os percentuais precisam somar 100% (hoje somam {sum(filled):g}%).")


def _rate(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 0.5:
        raise PlanError(f"{label}: use um valor entre 0% e 50% ao ano.")
    return float(value)


def _ticker(value: Any, label: str) -> str | None:
    if value is None or value == "":
        return None
    ticker = str(value).strip().upper()
    if not TICKER.match(ticker):
        raise PlanError(f"{label}: use o código de negociação (ex.: ABCD11).")
    return ticker


def validate(key: str, value: Any) -> Any:
    if not isinstance(value, dict):
        raise PlanError("Formato inválido.")
    if key == MONTHLY_TARGET:
        extra = value.get("extra_paycheck", False)
        if not isinstance(extra, bool):
            raise PlanError("Pagamento extra do salário: escolha ligado ou desligado.")
        return {"cents": _cents(value.get("cents"), "Meta por mês"), "extra_paycheck": extra}
    if key == CASH_CUSHION:
        return {"cents": _cents(value.get("cents"), "Colchão")}
    if key == RESERVE:
        order = value.get("order", list(FIXED_INCOME_ORDER))
        if (
            not isinstance(order, list)
            or not order
            or len(set(order)) != len(order)
            or any(o not in FIXED_INCOME_ORDER for o in order)
        ):
            raise PlanError("Composição da reserva: escolha entre " + " e ".join(FIXED_INCOME_ORDER) + ".")
        return {"cents": _cents(value.get("cents"), "Valor da reserva", optional=True), "order": order}
    if key == PATRIMONY_TARGET:
        classes = value.get("classes")
        if not isinstance(classes, dict) or set(classes) - set(BUCKETS):
            raise PlanError("Formato inválido.")
        out = {b: _pct(classes.get(b), BUCKET_LABELS[b]) for b in BUCKETS}
        _sum_100(list(out.values()), "Alocação-alvo do Patrimônio")
        return {
            "classes": out,
            "etf_global": _ticker(value.get("etf_global"), "ETF Global"),
            "etf_brasil": _ticker(value.get("etf_brasil"), "ETF Brasil"),
        }
    if key == CORE:
        tickers = value.get("tickers")
        if not isinstance(tickers, list):
            raise PlanError("Formato inválido.")
        satellite = value.get("satellite", [])
        if not isinstance(satellite, list):
            raise PlanError("Formato inválido.")
        core = {_ticker(t, "Núcleo") for t in tickers} - {None}
        sat = {_ticker(t, "Satélite") for t in satellite} - {None}
        if core & sat:
            raise PlanError("Uma ação não pode ser núcleo e satélite ao mesmo tempo.")
        mode = value.get("weights", "iguais")
        if mode not in WEIGHT_MODES:
            raise PlanError("Pesos do núcleo: escolha iguais, proporção atual ou personalizados.")
        custom = value.get("custom") or {}
        if not isinstance(custom, dict):
            raise PlanError("Formato inválido.")
        weights = {_ticker(t, "Núcleo"): _pct(p, "Peso no núcleo") for t, p in custom.items()}
        weights = {t: p for t, p in weights.items() if t in core and p is not None}
        if mode == "personalizado":
            if set(weights) != core or any(p <= 0 for p in weights.values()):
                raise PlanError("Pesos do núcleo: dê um peso maior que zero a cada empresa.")
            if abs(sum(weights.values()) - 100) > 0.01:
                raise PlanError(f"Pesos do núcleo: precisam somar 100% (hoje somam {sum(weights.values()):g}%).")
        return {
            "tickers": sorted(core),
            "satellite": sorted(sat),
            "weights": mode,
            "custom": {t: weights[t] for t in sorted(weights)} if mode == "personalizado" else {},
        }
    if key == RETURNS:
        return {
            "assumed": _rate(value.get("assumed"), "Rendimento esperado"),
            "aspirational": _rate(value.get("aspirational"), "Meta de rentabilidade"),
        }
    raise PlanError("Meta desconhecida.")
