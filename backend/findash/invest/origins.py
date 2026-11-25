"""Origem dos créditos de resgate e venda na conta corrente.

Um crédito "Valor recebido de Investimentos" / "Resgate ..." é ligado ao(s) ativo(s) de onde saiu:
1. pelas fotos diárias (investment_snapshots): queda de quantidade (ou de saldo, sem quantidade)
   entre duas fotos consecutivas vira um evento de saída datado na foto que mostrou a queda;
2. para o passado sem fotos, pelas vendas em investment_transactions (SELL/AMORTIZATION).

Regras de pareamento (iguais para as duas fontes):
- janela: o crédito cai de D−1 a D+3 DIAS ÚTEIS do evento D (liquidação D+2 atravessa fins de
  semana; feriados não são considerados);
- soma: vários eventos do MESMO dia podem compor um crédito (o dia inteiro, todos os eventos de um
  ativo no dia, ou combinações de até 4 eventos quando o dia tem poucos eventos);
- tolerância: |crédito − valor| <= max(R$ 0,10; 3% do valor), comparando com o valor bruto e com o
  líquido (IR, taxas e variação de preço entre a foto e a venda);
- entre os candidatos válidos vence a menor diferença; empate: menos eventos, depois data mais próxima.
O que não casa fica como "resgate de origem não identificada" (continua sendo movimento interno).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations, pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import InvestmentSnapshot, InvestmentTransaction

SOURCE_SNAPSHOT = "foto"
SOURCE_TRANSACTION = "transacao"
SALE_TYPES = ("SELL", "AMORTIZATION")
WINDOW_BEFORE_BDAYS, WINDOW_AFTER_BDAYS = 1, 3
TOLERANCE_PCT = Decimal("0.03")
TOLERANCE_MIN_CENTS = 10
MAX_COMBINATION = 4
MAX_POOL_FOR_COMBINATIONS = 16
BALANCE_DROP_MIN_PCT = Decimal("0.01")  # sem quantidade: queda de saldo menor que isso é oscilação de preço


@dataclass(frozen=True)
class OriginEvent:
    source: str
    event_date: date
    investment_id: str
    gross_cents: int
    net_cents: int | None
    investment_transaction_id: str | None = None

    @property
    def key(self) -> tuple:
        return (self.source, self.investment_transaction_id or self.investment_id, self.event_date)


@dataclass(frozen=True)
class Credit:
    transaction_id: str
    date: date
    cents: int  # positivo


def add_business_days(day: date, offset: int) -> date:
    step = 1 if offset >= 0 else -1
    remaining = abs(offset)
    while remaining:
        day += timedelta(days=step)
        if day.weekday() < 5:
            remaining -= 1
    return day


def in_window(event_date: date, credit_date: date) -> bool:
    return (
        add_business_days(event_date, -WINDOW_BEFORE_BDAYS)
        <= credit_date
        <= add_business_days(event_date, WINDOW_AFTER_BDAYS)
    )


def tolerance(value_cents: int) -> int:
    return max(TOLERANCE_MIN_CENTS, int(abs(value_cents) * TOLERANCE_PCT))


def snapshot_drop_events(session: Session) -> list[OriginEvent]:
    """Quedas de posição entre fotos consecutivas (por ativo)."""
    rows = list(session.scalars(select(InvestmentSnapshot).order_by(InvestmentSnapshot.snapshot_date)))
    dates = sorted({r.snapshot_date for r in rows})
    by_day: dict[date, dict[str, InvestmentSnapshot]] = defaultdict(dict)
    for r in rows:
        by_day[r.snapshot_date][r.investment_id] = r
    events: list[OriginEvent] = []
    for previous_day, current_day in pairwise(dates):
        current = by_day[current_day]
        for investment_id, before in by_day[previous_day].items():
            event = _drop(before, current.get(investment_id), current_day)
            if event is not None:
                events.append(event)
    return events


def _drop(before: InvestmentSnapshot, after: InvestmentSnapshot | None, day: date) -> OriginEvent | None:
    gross_before = before.amount_cents if before.amount_cents is not None else before.balance_cents
    net_before = before.balance_cents if before.balance_cents is not None else gross_before
    if not gross_before or gross_before <= 0:
        return None
    if after is None:  # ativo sumiu da lista: saiu inteiro
        return OriginEvent(SOURCE_SNAPSHOT, day, before.investment_id, gross_before, net_before)
    if before.quantity is not None and after.quantity is not None and before.quantity > 0:
        sold = before.quantity - after.quantity
        if sold <= 0:
            return None
        share = sold / before.quantity
        price = after.unit_value if after.unit_value else before.unit_value
        gross = int((sold * price * 100).quantize(Decimal(1))) if price else int(Decimal(gross_before) * share)
        net = int((Decimal(net_before) * share).quantize(Decimal(1))) if net_before is not None else None
        return OriginEvent(SOURCE_SNAPSHOT, day, before.investment_id, gross, net) if gross > 0 else None
    gross_after = after.amount_cents if after.amount_cents is not None else after.balance_cents
    if gross_after is None:
        return None
    dropped = gross_before - gross_after
    if dropped <= max(TOLERANCE_MIN_CENTS, int(gross_before * BALANCE_DROP_MIN_PCT)):
        return None
    net_after = after.balance_cents if after.balance_cents is not None else gross_after
    return OriginEvent(
        SOURCE_SNAPSHOT,
        day,
        before.investment_id,
        dropped,
        (net_before - net_after) if net_before is not None else None,
    )


def sale_events(session: Session) -> list[OriginEvent]:
    events = []
    for inv in session.scalars(
        select(InvestmentTransaction)
        .where(InvestmentTransaction.type.in_(SALE_TYPES))
        .order_by(InvestmentTransaction.date, InvestmentTransaction.id)
    ):
        gross = abs(inv.amount_cents or 0) or abs(inv.net_amount_cents or 0)
        if not gross:
            continue
        net = abs(inv.net_amount_cents) if inv.net_amount_cents is not None else None
        events.append(OriginEvent(SOURCE_TRANSACTION, inv.date, inv.investment_id, gross, net, inv.id))
    return events


def match_credits(
    credits: list[Credit], snapshot_events: list[OriginEvent], transaction_events: list[OriginEvent]
) -> dict[str, list[OriginEvent]]:
    """Liga cada crédito a um conjunto de eventos; fotos primeiro, depois transações de venda."""
    ordered = sorted(credits, key=lambda c: (c.date, -c.cents, c.transaction_id))
    result: dict[str, list[OriginEvent]] = {}
    for events in (snapshot_events, transaction_events):
        used: set[tuple] = set()
        for credit in ordered:
            if credit.transaction_id in result:
                continue
            found = _best_match(
                credit, [e for e in events if e.key not in used and in_window(e.event_date, credit.date)]
            )
            if found:
                used.update(e.key for e in found)
                result[credit.transaction_id] = found
    return result


def _best_match(credit: Credit, pool: list[OriginEvent]) -> list[OriginEvent] | None:
    by_day: dict[date, list[OriginEvent]] = defaultdict(list)
    for event in pool:
        by_day[event.event_date].append(event)
    best: tuple | None = None
    for day, events in by_day.items():
        for group in _groups(events):
            diff = _difference(credit.cents, group)
            if diff is None:
                continue
            rank = (diff, len(group), abs((credit.date - day).days), [e.key for e in group])
            if best is None or rank < best[0]:
                best = (rank, group)
    return list(best[1]) if best else None


def _groups(events: list[OriginEvent]):
    events = sorted(events, key=lambda e: e.key)
    seen: set[tuple] = set()

    def emit(group):
        signature = tuple(e.key for e in group)
        if signature not in seen:
            seen.add(signature)
            return group
        return None

    candidates = [(e,) for e in events]
    candidates.append(tuple(events))
    by_investment: dict[str, list[OriginEvent]] = defaultdict(list)
    for event in events:
        by_investment[event.investment_id].append(event)
    candidates += [tuple(group) for group in by_investment.values()]
    if len(events) <= MAX_POOL_FOR_COMBINATIONS:
        for size in range(2, min(MAX_COMBINATION, len(events)) + 1):
            candidates += list(combinations(events, size))
    for group in candidates:
        if emit(group) is not None:
            yield group


def _difference(credit_cents: int, group) -> int | None:
    gross = sum(e.gross_cents for e in group)
    diffs = [abs(credit_cents - gross)] if abs(credit_cents - gross) <= tolerance(gross) else []
    if all(e.net_cents is not None for e in group):
        net = sum(e.net_cents for e in group)
        if abs(credit_cents - net) <= tolerance(net):
            diffs.append(abs(credit_cents - net))
    return min(diffs) if diffs else None
