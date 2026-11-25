"""Variação de cada ativo entre a primeira foto em que ele aparece e a foto mais recente.

variação (R$) = saldo final − saldo inicial − (compras − vendas no período)   [saldos brutos]
variação (%)  = variação ÷ (saldo inicial + compras do período)

Compras e vendas de cada trecho entre fotos consecutivas vêm das transações de investimento
(BUY / SELL / AMORTIZATION) do trecho; sem transação registrada, a mudança de quantidade entre as
fotos é valorizada pelo preço da foto mais nova. Assim, aportar mais num ativo não aparece como
"valorização".
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import InvestmentSnapshot, InvestmentTransaction

BUY_TYPES = ("BUY",)
SELL_TYPES = ("SELL", "AMORTIZATION")


@dataclass
class AssetVariation:
    investment_id: str
    first_date: date
    last_date: date
    start_cents: int
    end_cents: int
    bought_cents: int
    sold_cents: int

    @property
    def change_cents(self) -> int:
        return self.end_cents - self.start_cents - (self.bought_cents - self.sold_cents)

    @property
    def change_pct(self) -> float | None:
        base = self.start_cents + self.bought_cents
        return self.change_cents / base if base > 0 else None


def _gross(snap: InvestmentSnapshot) -> int:
    return (snap.amount_cents if snap.amount_cents is not None else snap.balance_cents) or 0


def asset_variations(session: Session) -> dict[str, AssetVariation]:
    snapshots: dict[str, list[InvestmentSnapshot]] = defaultdict(list)
    for snap in session.scalars(select(InvestmentSnapshot).order_by(InvestmentSnapshot.snapshot_date)):
        snapshots[snap.investment_id].append(snap)
    if not snapshots:
        return {}
    latest = max(s.snapshot_date for rows in snapshots.values() for s in rows)
    trades: dict[str, list[InvestmentTransaction]] = defaultdict(list)
    for tx in session.scalars(
        select(InvestmentTransaction).where(InvestmentTransaction.type.in_(BUY_TYPES + SELL_TYPES))
    ):
        trades[tx.investment_id].append(tx)

    result: dict[str, AssetVariation] = {}
    for investment_id, rows in snapshots.items():
        held = [s for s in rows if (s.balance_cents or 0) > 0]
        if not held or held[-1].snapshot_date != latest:
            continue  # nunca teve saldo ou já não está na carteira
        first = held[0]
        window = [s for s in rows if s.snapshot_date >= first.snapshot_date]
        bought = sold = 0
        for before, after in itertools.pairwise(window):
            in_period = [
                t for t in trades.get(investment_id, []) if before.snapshot_date < t.date <= after.snapshot_date
            ]
            if in_period:
                for t in in_period:
                    value = abs(t.amount_cents or t.net_amount_cents or 0)
                    if t.type in BUY_TYPES:
                        bought += value
                    else:
                        sold += value
                continue
            delta = (after.quantity or Decimal(0)) - (before.quantity or Decimal(0))
            price = after.unit_value or before.unit_value
            if delta and price:
                value = int((abs(delta) * price * 100).quantize(Decimal(1)))
                if delta > 0:
                    bought += value
                else:
                    sold += value
        result[investment_id] = AssetVariation(
            investment_id, first.snapshot_date, latest, _gross(first), _gross(held[-1]), bought, sold
        )
    return result
