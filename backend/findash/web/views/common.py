"""Utilidades compartilhadas pelas visões da API (valores sempre em centavos; datas ISO)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import STATE_ACTIVE, Transaction
from findash.invest.wealth import Wealth


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(p) for p in month.split("-"))
    index = year * 12 + mon - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_of(day: date) -> str:
    return f"{day:%Y-%m}"


def last_months(current: str, count: int) -> list[str]:
    return [shift_month(current, -n) for n in range(count - 1, -1, -1)]


def available_months(session: Session) -> list[str]:
    first, last = session.execute(
        select(func.min(Transaction.date), func.max(Transaction.date)).where(Transaction.state == STATE_ACTIVE)
    ).one()
    if first is None:
        return []
    months, cursor = [], month_of(first)
    while cursor <= month_of(last):
        months.append(cursor)
        cursor = shift_month(cursor, 1)
    return list(reversed(months))


def iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def in_transit_json(w: Wealth) -> dict:
    labels = dict(w.assets)
    return {
        "cents": w.in_transit_cents,
        "items": [
            {
                "id": o.transaction_id,
                "date": iso(o.day),
                "description": o.description,
                "cents": o.cents,
                "until": iso(o.until),
                "suggestion": None
                if o.suggestion not in labels
                else {"id": o.suggestion, "label": labels[o.suggestion]},
            }
            for o in w.in_transit
        ],
        # ativos da foto mais recente, para "já chegou (é o ativo X)"
        "assets": [{"id": i, "label": label} for i, label in w.assets] if w.in_transit else [],
    }


def wealth_json(w: Wealth | None, *, series: bool = True) -> dict | None:
    """Patrimônio total = carteira como no app do banco + em trânsito (o mesmo número em todas as telas)."""
    if w is None:
        return None
    out = {"date": iso(w.day), "total": w.total_cents, "portfolio": w.portfolio_cents, "in_transit": in_transit_json(w)}
    if series:
        first, last = w.series[0], w.series[-1]
        change = last.total_cents - first.total_cents
        out["change"] = {
            "cents": change,
            "since": iso(first.day),
            "pct": change / first.total_cents if first.total_cents else None,
        }
        out["series"] = [
            {
                "date": iso(d.day),
                "total": d.total_cents,
                "portfolio": d.portfolio_cents,
                "in_transit": d.in_transit_cents,
            }
            for d in w.series
        ]
    return out
