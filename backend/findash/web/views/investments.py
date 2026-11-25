"""Investimentos: alocação, tabela por ativo, evolução, rentabilidade × CDI × IPCA × meta, renda fixa e proventos.

Meta de rentabilidade (aspiracional, definida no Plano): taxa anual r levada ao período pelos dias corridos,
(1 + r)^(dias / 365) − 1, desenhada como linha ao lado do CDI e do IPCA.

O lucro por ativo fica de fora de propósito; a variação de cada
ativo é medida entre a primeira foto em que ele aparece e a mais recente, descontando compras e vendas.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from findash.institutions import get_profile
from findash.invest import market
from findash.invest.classes import ClassMap
from findash.invest.performance import accumulated_result, cumulative_twr, monthly_returns, portfolio_series
from findash.invest.portfolio import (
    allocation,
    dividends,
    dividends_by_class,
    fixed_income,
    positions,
)
from findash.invest.variation import asset_variations
from findash.invest.wealth import wealth
from findash.plan import settings as S
from findash.web.views.common import iso, wealth_json
from findash.web.views.plan import COLORS, LABELS, PlanState, data_as_of

MIN_PERFORMANCE_DAYS = 7  # abaixo disso a interface explica em vez de desenhar um gráfico quase vazio


def target_return(annual: float, start: date, end: date) -> float:
    return (1 + annual) ** (max(0, (end - start).days) / 365) - 1


def investments(session: Session, class_map: ClassMap, *, today: date) -> dict:
    items = positions(session, class_map)
    series = portfolio_series(session)
    aspirational = S.value_at(session, S.RETURNS, f"{today:%Y-%m}").value["aspirational"]
    if not items:
        return {
            "snapshot_date": None,
            "data_as_of": data_as_of(session),
            "total": 0,
            "total_net": 0,
            "wealth": None,
            "bank_view": None,
            "aspirational": aspirational,
            "allocation": [],
            "allocation_by_place": [],
            "assets": [],
            "evolution": [],
            "performance": _performance(session, series, aspirational),
            "monthly": _monthly(session, series, today, aspirational),
            "fixed_income": [],
            "dividends": {"total": 0, "by_month": [], "by_class": []},
        }
    alloc = allocation(items)
    total_wealth = wealth(session, today)
    variations = asset_variations(session)
    div = dividends(session, today)
    assets = []
    for p in items:
        inv, snap = p.investment, p.snapshot
        var = variations.get(inv.id)
        assets.append(
            {
                "id": inv.id,
                "label": p.label,
                "code": inv.code,
                "class": p.asset_class,
                "class_source": p.class_source,
                "quantity": float(snap.quantity) if snap.quantity is not None else None,
                "price": float(snap.unit_value) if snap.unit_value is not None else None,
                "balance": p.value_cents,
                "net": p.net_cents,
                "pct": p.value_cents / alloc.total_cents if alloc.total_cents else None,
                "variation": None
                if var is None
                else {
                    "cents": var.change_cents,
                    "pct": var.change_pct,
                    "since": iso(var.first_date),
                    "bought": var.bought_cents,
                    "sold": var.sold_cents,
                },
                "dividends_12m": div.by_asset.get(inv.code or inv.name or "?", 0)
                if inv.type != "FIXED_INCOME"
                else None,
            }
        )
    fixed = [
        {
            "label": r.label,
            "class": r.asset_class,
            "rate": r.rate,
            "purchase_date": iso(r.purchase_date),
            "due_date": iso(r.due_date),
            "applied": r.applied_cents,
            "gross": r.gross_cents,
            "net": r.net_cents,
            "profit": r.profit_cents,
            "return_pct": r.return_pct,
            "annualized": r.annualized(today),
        }
        for r in fixed_income(items)
    ]
    st = PlanState(session, class_map, today)
    places = [p for p in ("reserva", "patrimonio") if st.totals.get(p, 0) > 0]
    return {
        "snapshot_date": iso(items[0].snapshot.snapshot_date),
        "data_as_of": data_as_of(session),
        "total": alloc.total_cents,
        "total_net": sum(p.net_cents for p in items),
        "wealth": wealth_json(total_wealth, series=False),
        "bank_view": _bank_view(items, total_wealth),
        "allocation": [
            {"class": c, "cents": v, "pct": v / alloc.total_cents if alloc.total_cents else None}
            for c, v in alloc.by_class.items()
        ],
        "aspirational": aspirational,
        "allocation_by_place": [
            {
                "place": p,
                "label": LABELS[p],
                "color": COLORS[p],
                "cents": st.totals[p],
                "pct": st.totals[p] / alloc.total_cents if alloc.total_cents else None,
            }
            for p in places
        ],
        "assets": assets,
        "evolution": [{"date": iso(d), "value": v} for d, v in series.valuations],
        "performance": _performance(session, series, aspirational),
        "monthly": _monthly(session, series, today, aspirational),
        "fixed_income": fixed,
        "dividends": {
            "total": div.total_cents,
            "by_month": [{"month": m, "cents": c} for m, c in div.by_month.items()],
            "by_class": [
                {"month": d.month, "total": d.total_cents, "by_class": d.by_class, "by_asset": d.by_asset}
                for d in dividends_by_class(session, class_map, today)
            ],
        },
    }


def _bank_view(items, total_wealth) -> dict:
    """Os grupos que o app do banco usa na tela de investimentos, para conferir os totais lado a lado."""
    profiles = {p.investment.institution: get_profile(p.investment.institution) for p in items}
    groups: dict[str, int] = {}
    for profile in profiles.values():
        groups.update({g: 0 for g in profile.app_groups if g not in groups})
    for p in items:
        group = profiles[p.investment.institution].app_group(p.investment)
        groups[group] = groups.get(group, 0) + p.value_cents
    names = sorted({profile.name for profile in profiles.values()})
    in_transit = total_wealth.in_transit_cents if total_wealth else 0
    return {
        "institution": names[0] if len(names) == 1 else None,
        "groups": [{"label": g, "cents": v} for g, v in groups.items() if v],
        "in_transit": in_transit,
        "total": sum(groups.values()) + in_transit,
    }


def _monthly(session: Session, series, today: date, aspirational: float) -> dict:
    """Rendimento mês a mês: investido no início, aportado, resgatado, ganho, TWR, CDI e IPCA do mês."""
    rows = []
    for r in monthly_returns(series, today):
        cdi = market.cdi_return(session, r.start, r.end)
        ipca = market.ipca_return(session, r.start, r.end)
        rows.append(
            {
                "month": r.month,
                "start": iso(r.start),
                "end": iso(r.end),
                "start_value": r.start_value,
                "end_value": r.end_value,
                "contributions": r.contributions,
                "redemptions": r.redemptions,
                "income": r.income,
                "gain": r.gain,
                "twr": r.twr,
                "cdi": cdi.value,
                "ipca": ipca.value,
                "target": target_return(aspirational, r.start, r.end),
                "ipca_note": ipca.note,
                "partial_since": iso(r.partial_since),
                "in_progress": r.in_progress,
            }
        )
    return {
        "months": rows,
        "total_contributions": sum(r["contributions"] for r in rows),
        "total_redemptions": sum(r["redemptions"] for r in rows),
        "total_gain": sum(r["gain"] for r in rows),
    }


def _performance(session: Session, series, aspirational: float) -> dict:
    days = series.snapshot_days
    result = {
        "days": days,
        "min_days": MIN_PERFORMANCE_DAYS,
        "enough": days >= MIN_PERFORMANCE_DAYS,
        "first_date": iso(series.valuations[0][0]) if days else None,
        "series": [],
        "accumulated": None,
    }
    if days < 2:
        return result
    start = series.valuations[0][0]
    notes: list[str] = []
    points = cumulative_twr(series)
    benchmarks = market.cumulative_benchmarks(session, start, [d for d, _ in points])
    for (d, value), (cdi, ipca) in zip(points, benchmarks, strict=True):
        result["series"].append(
            {
                "date": iso(d),
                "twr": value,
                "cdi": cdi.value,
                "ipca": ipca.value,
                "target": target_return(aspirational, start, d),
            }
        )
        notes = [n for n in (cdi.note, ipca.note) if n]
    acc = accumulated_result(series)
    if acc is not None:
        last = result["series"][-1]
        result["accumulated"] = {
            "twr": acc.twr,
            "xirr_annual": acc.xirr_annual,
            "xirr_period": acc.xirr_period,
            "cdi": last["cdi"],
            "ipca": last["ipca"],
            "net_flows": acc.net_flows,
            "income": acc.income,
            "notes": notes,
            "target": last["target"],
            "above_target": acc.twr >= last["target"] if acc.twr is not None else None,
        }
    return result
