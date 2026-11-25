"""Tela Plano: Reserva de emergência + Patrimônio, o que fazer no mês (checklist) e a capacidade do mês.

Cada real investido está em UM só lugar (plan/places.py). As contas de cada parte estão nos módulos de
plan/; aqui só se junta tudo no formato da tela.
"""

from __future__ import annotations

import calendar
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import Investment, InvestmentSnapshot, ItemStatus
from findash.invest.classes import FIXED_INCOME_CLASSES, ClassMap
from findash.invest.portfolio import positions
from findash.invest.wealth import wealth
from findash.plan import settings as S
from findash.plan.base import essential_average, extra_paycheck, shift_month
from findash.plan.capacity import MonthCapacity, contributions_by_asset, month_capacity
from findash.plan.contribution import MonthSplit, PatrimonySplit, core_weights, split_month, split_patrimony
from findash.plan.places import PATRIMONY, RESERVE, Holding, assign, totals
from findash.sync.service import stale_hours
from findash.web.views.common import available_months, iso, last_months, wealth_json

LABELS = {RESERVE: "Reserva de emergência", PATRIMONY: "Patrimônio"}
COLORS = {RESERVE: "var(--goal-reserva)", PATRIMONY: "var(--goal-patrimonio)"}
SUGGESTED = ("renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo")
CORE_CLASSES = ("Ações", "BDR")
ON_TARGET_TOLERANCE = 0.02  # até 2 pontos do alvo conta como "no alvo"
CHECKLIST_MAX = 5
DONE_RATIO = 0.95  # a cotação muda entre a sugestão e a compra: 95% do valor já marca ✓
PREVIEW_LAST_DAYS = 5
# "Onde comprar" de cada linha da checklist (cálculo a partir das metas; não é recomendação)
WHERE_RESERVE = {
    "CDB/RDB": "CDB de liquidez diária (para a Reserva de emergência)",
    "Tesouro": "Tesouro Selic (para a Reserva de emergência)",
}
WHERE_FIXED = "renda fixa (Tesouro Selic ou CDB de liquidez diária)"
WHERE_UNDEFINED = "defina os alvos da carteira em “Ajustar o plano”"


def data_as_of(session: Session) -> str | None:
    """Data/hora do dado na Pluggy (UTC, com Z): 'Dados da Pluggy até ...'."""
    value = session.scalar(select(func.max(ItemStatus.pluggy_last_updated_at)))
    return f"{value.isoformat()}Z" if value else None


def data_stale_hours(session: Session, now: datetime) -> int | None:
    """Horas desde a última atualização da Pluggy, só quando passa do limite (dado antigo); senão None."""
    return stale_hours(session.scalar(select(func.max(ItemStatus.pluggy_last_updated_at))), now)


def _setting_json(session: Session, key: str, month: str) -> dict:
    current = S.value_at(session, key, month)
    return {
        "value": current.value,
        "effective_month": current.effective_month,
        "id": current.id,
        "history": [
            {
                "id": r.id,
                "effective_month": r.effective_month,
                "value": S.merged(key, r.value_json),
                "created_at": iso(r.created_at),
            }
            for r in S.changes(session, key)
        ],
    }


def resolver(session: Session, key: str) -> Callable[[str], dict]:
    """Valor da meta em qualquer mês (inclusive futuro), lendo o histórico uma vez só."""
    rows = S.history(session, key)
    months = [r.effective_month for r in rows]

    def at(month: str) -> dict:
        index = bisect_right(months, month)
        return S.merged(key, rows[index - 1].value_json) if index else S.DEFAULTS[key]

    return at


def capacity_json(cap: MonthCapacity) -> dict:
    return {
        "month": cap.month,
        "closed": cap.closed,
        "income": cap.income_cents,
        "salary_remaining": cap.salary_remaining_cents,
        "salary_remaining_paydays": [iso(d) for d in cap.salary_remaining_paydays],
        "expenses": cap.expenses_cents,
        "fixed_pending": cap.fixed_pending_cents,
        "variable_daily": cap.variable_daily_cents,
        "days_remaining": cap.days_remaining,
        "variable_estimate": cap.variable_estimate_cents,
        "variable_months": [{"month": m, "cents": c, "days": d} for m, c, d in cap.variable_months],
        "contributions": cap.contributions_cents,
        "redemptions": cap.redemptions_cents,
        "contributions_net": cap.contributions_net_cents,
        "projected_surplus": cap.projected_surplus_cents,
        "capacity": cap.capacity_cents,
        "bank": cap.bank_cents,
        "card_bill": cap.card_bill_cents,
        "balance_date": iso(cap.balance_date),
        "cushion": cap.cushion_cents,
        "cash_available": cap.cash_available_cents,
        "depends_on_future_salary": cap.depends_on_future_salary,
    }


def flows_json(contributions: int, redemptions: int) -> dict:
    """'Aportei · Resgatei · Saldo do mês' (nunca só o líquido)."""
    return {
        "contributions": contributions,
        "redemptions": redemptions,
        "net": contributions - redemptions,
        "shrinking": redemptions > contributions,
    }


def _latest_prices(session: Session) -> dict[str, int]:
    """Última cotação conhecida (centavos) por código de negociação."""
    out: dict[str, tuple[date, int]] = {}
    rows = session.execute(
        select(Investment.code, InvestmentSnapshot.snapshot_date, InvestmentSnapshot.unit_value)
        .join(InvestmentSnapshot, InvestmentSnapshot.investment_id == Investment.id)
        .where(Investment.code.is_not(None), InvestmentSnapshot.unit_value.is_not(None))
    )
    for code, day, price in rows:
        ticker = code.strip().upper()
        if price and price > 0 and (ticker not in out or day >= out[ticker][0]):
            out[ticker] = (day, round(float(price) * 100))
    return {k: v for k, (_, v) in out.items()}


def role_of(asset_class: str, ticker: str, core: set[str], satellite: set[str]) -> str | None:
    """Papel de uma ação/BDR: núcleo, satélite ou (sem marcação) manter. None para as outras classes."""
    if asset_class not in CORE_CLASSES:
        return None
    return "nucleo" if ticker in core else "satelite" if ticker in satellite else "manter"


def bucket_of(asset_class: str, ticker: str, core: set[str], satellite: set[str] = frozenset()) -> str:
    if asset_class in FIXED_INCOME_CLASSES:
        return "renda_fixa"
    if asset_class == "ETF Global":
        return "etf_global"
    if asset_class == "ETF Brasil":
        return "etf_brasil"
    if asset_class == "FIIs":
        return "fiis"
    role = role_of(asset_class, ticker, core, satellite)
    if role is None:
        return "satelite"  # classe "Outros": oportunidade, dentro do teto
    return {"nucleo": "acoes_nucleo", "manter": "acoes_mantidas", "satelite": "satelite"}[role]


def _ticker(h: Holding) -> str:
    return (h.position.investment.code or "").strip().upper()


class PlanState:
    """O que a tela inteira precisa, calculado uma vez."""

    def __init__(self, session: Session, class_map: ClassMap, today: date) -> None:
        self.session, self.class_map, self.today = session, class_map, today
        self.month = f"{today:%Y-%m}"
        self.target_at = resolver(session, S.MONTHLY_TARGET)
        self.reserve_setting = S.value_at(session, S.RESERVE, self.month).value
        self.returns = S.value_at(session, S.RETURNS, self.month).value
        self.roles = S.value_at(session, S.CORE, self.month).value
        self.core, self.satellite = set(self.roles["tickers"]), set(self.roles["satellite"])
        self.items = positions(session, class_map)
        self.holdings = assign(
            session, self.items, reserve_cents=self.reserve_setting["cents"], order=self.reserve_setting["order"]
        )
        self.totals = totals(self.holdings)
        reserve = self.reserve_setting["cents"]
        self.reserve_gap = max(0, reserve - self.totals.get(RESERVE, 0)) if reserve is not None else 0

    def extra_of(self, month: str) -> int:
        """Pagamento extra do salário no mês, quando a meta pede para somá-lo."""
        return extra_paycheck(self.session, month).cents if self.target_at(month).get("extra_paycheck") else 0

    def patrimony_json(self) -> dict[str, Any]:
        target = S.value_at(self.session, S.PATRIMONY_TARGET, self.month).value
        pcts = target["classes"]
        defined = all(pcts.get(b) is not None for b in S.BUCKETS)
        values: dict[str, int] = defaultdict(int)
        core_values: dict[str, int] = {}
        members: dict[str, list[dict]] = defaultdict(list)
        for h in self.holdings:
            cents = h.parts.get(PATRIMONY, 0)
            if not cents:
                continue
            ticker = _ticker(h)
            bucket = bucket_of(h.position.asset_class, ticker, self.core, self.satellite)
            values[bucket] += cents
            members[bucket].append({"label": h.position.label, "cents": cents})
            if bucket == "acoes_nucleo":
                core_values[ticker] = core_values.get(ticker, 0) + cents
        total = sum(values.values())
        buckets = []
        for b in S.DISPLAY_BUCKETS:
            current, pct = values.get(b, 0), pcts.get(b)  # "Ações mantidas" não tem alvo
            share = current / total if total else None
            goal_cents = round(total * pct / 100) if pct is not None else None
            deviation = None if pct is None or share is None else share - pct / 100
            over_cap = b == "satelite" and deviation is not None and deviation > 1e-9
            if deviation is None:
                state = "sem_alvo"
            elif b == "satelite":
                state = "acima_teto" if over_cap else "dentro_teto"
            else:
                state = (
                    "abaixo"
                    if deviation < -ON_TARGET_TOLERANCE
                    else "acima"
                    if deviation > ON_TARGET_TOLERANCE
                    else "no_alvo"
                )
            buckets.append(
                {
                    "bucket": b,
                    "label": S.BUCKET_LABELS[b],
                    "current": current,
                    "current_pct": share,
                    "target_pct": None if pct is None else pct / 100,
                    "target_cents": goal_cents,
                    "deviation_pct": deviation,
                    "deviation_cents": None if goal_cents is None else current - goal_cents,
                    "suggested": b in SUGGESTED,
                    "cap": b == "satelite",
                    "over_cap": over_cap,
                    "state": state,
                    # núcleo com alvo mas sem empresa escolhida: nada a sugerir até a pessoa escolher
                    "needs_core": b == "acoes_nucleo" and bool(pct) and not core_values,
                    "members": sorted(members.get(b, []), key=lambda m: -m["cents"]),
                }
            )
        weights = core_weights(core_values, self.roles["weights"], self.roles["custom"])
        weight_total = sum(weights.values()) or 1
        core_pct = pcts.get("acoes_nucleo")
        core = []
        for ticker, value in sorted(core_values.items(), key=lambda kv: -kv[1]):
            share = weights[ticker] / weight_total
            each = None if core_pct is None else core_pct / 100 * share
            core.append(
                {
                    "ticker": ticker,
                    "current": value,
                    "current_pct": value / total if total else None,
                    "weight": share,
                    "target_pct": each,
                    "deviation_pct": None if each is None or not total else value / total - each,
                }
            )
        return {
            "current": total,
            "target_defined": defined,
            "off_target": sum(1 for b in buckets if b["state"] in ("abaixo", "acima", "acima_teto")),
            "buckets": buckets,
            "core": core,
            "core_weights": self.roles["weights"],
            "etf_global": target["etf_global"],
            "etf_brasil": target["etf_brasil"],
            "values": dict(values),
            "core_values": core_values,
            "pcts": pcts,
            "weights": weights,
        }

    def reserve_json(self) -> dict[str, Any]:
        first = (available_months(self.session) or [self.month])[-1]
        essentials = essential_average(self.session, self.today, first_month=first)
        current = self.totals.get(RESERVE, 0)
        target = self.reserve_setting["cents"]
        avg = essentials.average_cents
        return {
            "target": target,
            "current": current,
            "gap": self.reserve_gap,
            "complete": target is not None and current >= target,
            "order": self.reserve_setting["order"],
            "essential_average": avg,
            "essential_months": [{"month": m, "cents": c} for m, c in essentials.months],
            "covered_months": current / avg if avg else None,
            "target_months": target / avg if avg and target is not None else None,
            "holdings": [
                {
                    "label": h.position.label,
                    "class": h.position.asset_class,
                    "cents": h.parts[RESERVE],
                    "manual": h.manual == RESERVE,
                }
                for h in self.holdings
                if h.parts.get(RESERVE)
            ],
        }


def _checklist(entries: list[dict]) -> list[dict]:
    """Junta as compras por investimento e limita a lista a CHECKLIST_MAX linhas (o detalhe fica nos cálculos)."""
    lines: dict[str, dict] = {}
    for e in entries:
        if e["amount"] <= 0:
            continue
        line = lines.setdefault(
            e["where"],
            {
                "where": e["where"],
                "amount": 0,
                "detected": 0,
                "shares": None,
                "price": e.get("price"),
                "ticker": e.get("ticker"),
            },
        )
        line["amount"] += e["amount"]
        line["detected"] += max(0, e["detected"])  # resgate não é aporte feito
        if e.get("shares") is not None:
            line["shares"] = (line["shares"] or 0) + e["shares"]
    out = list(lines.values())
    if len(out) > CHECKLIST_MAX:
        keep = sorted(sorted(range(len(out)), key=lambda i: -out[i]["amount"])[: CHECKLIST_MAX - 1])
        rest = [out[i] for i in range(len(out)) if i not in keep]
        out = [out[i] for i in keep] + [
            {
                "where": "outras compras menores: " + ", ".join(line["where"] for line in rest),
                "amount": sum(line["amount"] for line in rest),
                "detected": sum(line["detected"] for line in rest),
                "shares": None,
                "price": None,
                "ticker": None,
            }
        ]
    for line in out:
        line["done"] = line["detected"] >= line["amount"] * DONE_RATIO
    return out


def month_plan(
    st: PlanState, pat: dict, month: str, prices: dict[str, int], detected: dict[tuple[str, str], int] | None = None
) -> tuple[dict, MonthSplit, PatrimonySplit]:
    """Meta de um mês e a checklist "R$ X → onde comprar".

    `detected` = aportes − resgates já feitos no mês por (lugar, ativo); None numa prévia (mês futuro).
    """
    detected = detected or {}
    base, extra = st.target_at(month)["cents"], st.extra_of(month)
    paycheck = extra_paycheck(st.session, month)
    total = base + extra
    split = split_month(total, st.reserve_gap)
    pat_amount = split.amounts[PATRIMONY]
    pat_split = split_patrimony(
        pat_amount if pat["target_defined"] else 0,
        pat["pcts"],
        pat["values"],
        pat["core_values"],
        {"etf_global": pat["etf_global"], "etf_brasil": pat["etf_brasil"]},
        prices,
        pat["weights"],
    )
    in_patrimony = {k: c for (place, k), c in detected.items() if place == PATRIMONY}
    entries: list[dict] = []
    if split.amounts[RESERVE] > 0:
        entries.append(
            {
                "where": WHERE_RESERVE.get(st.reserve_setting["order"][0], WHERE_FIXED),
                "amount": split.amounts[RESERVE],
                "detected": sum(c for (place, _), c in detected.items() if place == RESERVE),
            }
        )
    if pat_amount > 0 and not pat["target_defined"]:
        entries.append({"where": WHERE_UNDEFINED, "amount": pat_amount, "detected": sum(in_patrimony.values())})
    for item in pat_split.items:
        if item.ticker:
            entries.append(
                {
                    "where": item.ticker,
                    "ticker": item.ticker,
                    "amount": item.spend_cents,
                    "shares": item.shares,
                    "price": item.price_cents,
                    "detected": in_patrimony.get(item.ticker, 0),
                }
            )
        else:  # renda fixa do Patrimônio: só aplicações em renda fixa contam (comprar outra ação não marca ✓)
            entries.append({"where": WHERE_FIXED, "amount": item.spend_cents, "detected": in_patrimony.get("rf", 0)})
    out = {
        "month": month,
        "base": base,
        "total": total,
        "extra": {
            "active": extra > 0,
            "cents": extra,
            "paycheck": paycheck.paycheck_cents,
            "count": paycheck.count,
            "enabled": bool(st.target_at(month).get("extra_paycheck")),
        },
        "reserve_priority": {
            "active": split.reserve_priority_cents > 0,
            "cents": split.reserve_priority_cents,
            "gap": st.reserve_gap,
        },
        "checklist": _checklist(entries),
        "patrimony": {
            "amount": pat_amount,
            "target_defined": pat["target_defined"],
            "leftover": pat_split.leftover_cents,
            "buckets": [{"bucket": b, "label": S.BUCKET_LABELS[b], "amount": v} for b, v in pat_split.buckets.items()],
            "items": [
                {
                    "bucket": i.bucket,
                    "label": S.BUCKET_LABELS[i.bucket],
                    "ticker": i.ticker,
                    "amount": i.amount_cents,
                    "price": i.price_cents,
                    "shares": i.shares,
                    "spend": i.spend_cents,
                    "carried_in": i.carried_in_cents,
                }
                for i in pat_split.items
            ],
        },
    }
    return out, split, pat_split


def plan(session: Session, class_map: ClassMap, *, today: date, now: datetime, with_history: bool = True) -> dict:
    st = PlanState(session, class_map, today)
    month = st.month
    cushion = S.value_at(session, S.CASH_CUSHION, month).value["cents"]

    # --- capacidade e aporte do mês
    cap = month_capacity(session, month, today=today, cushion_cents=cushion)
    fixed_income_place = RESERVE if st.reserve_gap > 0 else PATRIMONY

    def place_of(inv: Investment) -> str:
        for h in st.holdings:
            if h.position.investment.id == inv.id:
                return h.place
        asset_class, _ = class_map.classify(inv.code, inv.subtype)
        return fixed_income_place if asset_class in FIXED_INCOME_CLASSES else PATRIMONY

    def key_of(inv: Investment) -> str:
        asset_class, _ = class_map.classify(inv.code, inv.subtype)
        return "rf" if asset_class in FIXED_INCOME_CLASSES else (inv.code or "rv").strip().upper()

    detected = contributions_by_asset(session, month, place_of, fixed_income_place, key_of)
    pat = st.patrimony_json()
    prices = _latest_prices(session)
    contribution, split, _ = month_plan(st, pat, month, prices, detected)
    total = contribution["total"]
    room = cap.capacity_cents + cap.contributions_net_cents  # sobra projetada do mês (antes dos aportes já feitos)
    last_day = calendar.monthrange(today.year, today.month)[1]
    contribution.update(
        {
            "flows": flows_json(cap.contributions_cents, cap.redemptions_cents),
            "invested": max(0, cap.contributions_net_cents),
            "remaining": max(0, total - cap.contributions_net_cents),
            "capacity": cap.capacity_cents,
            "projected_surplus": room,
            "fits": cap.capacity_cents >= max(0, total - cap.contributions_net_cents),
            "places": [
                {"place": p, "label": LABELS[p], "color": COLORS[p], "planned": split.amounts[p]}
                for p in (RESERVE, PATRIMONY)
                if split.amounts[p] > 0
            ],
            # nos últimos dias do mês, já dá para ver o plano do mês seguinte (sem ✓: ainda não começou)
            "next": (
                month_plan(st, pat, shift_month(month, 1), prices)[0]
                if today.day > last_day - PREVIEW_LAST_DAYS
                else None
            ),
        }
    )

    # --- histórico de aportes (meta da época = base + pagamento extra daquele mês)
    history = []
    first_data = (available_months(session) or [month])[-1]
    target_start = S.first_month(session, S.MONTHLY_TARGET)
    for m in last_months(month, 12) if with_history else []:  # a Visão geral não precisa do histórico
        if m < first_data:
            continue
        cap_m = month_capacity(session, m, today=today, cushion_cents=cushion) if m < month else cap
        meta_m = None
        if target_start and m >= target_start:
            meta_m = st.target_at(m)["cents"] + st.extra_of(m)
        history.append(
            {
                "month": m,
                "contributed": cap_m.contributions_net_cents,
                "contributions": cap_m.contributions_cents,
                "redemptions": cap_m.redemptions_cents,
                "target": meta_m,
                "surplus": cap_m.projected_surplus_cents if cap_m.closed else None,
                "in_progress": m == month,
            }
        )

    return {
        "month": month,
        "today": iso(today),
        "data_as_of": data_as_of(session),
        "data_stale_hours": data_stale_hours(session, now),
        "settings": {key: _setting_json(session, key, month) for key in S.KEYS},
        "capacity": capacity_json(cap),
        "contribution": contribution,
        "wealth": wealth_json(wealth(session, today), series=False),
        "reserve": st.reserve_json(),
        "patrimony": {k: v for k, v in pat.items() if k not in ("values", "core_values", "pcts", "weights")},
        "places": [
            {"place": p, "label": LABELS[p], "color": COLORS[p], "cents": st.totals.get(p, 0)}
            for p in (RESERVE, PATRIMONY)
            if st.totals.get(p, 0) > 0
        ],
        "holdings": [
            {
                "investment_id": h.position.investment.id,
                "label": h.position.label,
                "class": h.position.asset_class,
                "value": h.position.value_cents,
                "place": h.place,
                "place_label": LABELS[h.place],
                "manual": h.manual is not None,
                "reason": h.reason,
                "parts": [{"place": p, "label": LABELS[p], "cents": c} for p, c in h.parts.items()],
                "ticker": _ticker(h) or None,
                "role": role_of(h.position.asset_class, _ticker(h), st.core, st.satellite),
            }
            for h in st.holdings
        ],
        "returns": st.returns,
        "history": history,
    }


def overview_summary(data: dict) -> dict:
    """Resumo do aporte do mês para a Visão geral (o detalhe fica na tela Plano)."""
    c = data["contribution"]
    return {
        "total": c["total"],
        "base": c["base"],
        "extra": c["extra"]["cents"],
        "flows": c["flows"],
        "remaining": c["remaining"],
        "capacity": c["capacity"],
        "fits": c["fits"],
        "projected_surplus": c["projected_surplus"],
        "places": [{"label": p["label"], "planned": p["planned"], "color": p["color"]} for p in c["places"]],
        "reserve_priority": c["reserve_priority"]["active"],
    }
