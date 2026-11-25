"""Patrimônio total = carteira como o app do banco mostra + em trânsito.

Carteira: como o app do banco mostra (`portfolio.bank_cents`): bruto, ou líquido de IR quando o perfil do banco pede.
Saldo da conta e fatura em aberto NÃO entram: aparecem à parte, como informação.

Em trânsito: uma saída da conta para investimento (movimento "aporte": compra de renda variável, aplicação
em Tesouro/CDB) cuja posição ainda não apareceu na foto da carteira (liquidação D+2). Enquanto isso, o valor
soma ao patrimônio para ele não "cair" (nem ficar parado) falsamente.
- chegada = aumento de posição entre duas fotos consecutivas: quantidade maior numa posição que já existia
  (valor = cotas novas × preço da foto), ativo novo (valor inteiro) ou, sem quantidade, saldo maior que a
  oscilação normal;
- compra registrada pela corretora (BUY) sem saída da conta ligada: se há saída do mesmo dia (±1 útil) com
  valor parecido (a saída inclui custos), é a mesma compra e a saída passa a esperar aquele ativo; senão, foi
  paga de outro lugar e fica com a chegada do próprio ativo (não é confundida com outra compra);
- pareamento, nesta ordem: (1) escolha manual ("já chegou, é o ativo X" ou "ignorar"); (2) valor e data:
  chegada entre 3 dias úteis antes e 5 depois da saída, diferença até 6% (mínimo R$ 1), valendo a soma de
  até 4 chegadas do mesmo dia; (3) saídas do mesmo dia somadas; (4) candidato único de D0 a D+5 úteis casa
  mesmo com diferença maior (cotação anda, custos), até 50%;
- compra que já aparece na foto do mesmo dia não chega a entrar em trânsito;
- sem chegada, o valor fica em trânsito por até 5 dias úteis após a saída e depois sai sozinho;
- saídas até o dia da primeira foto da carteira são ignoradas: a posição pode já estar na primeira foto.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations, pairwise

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import (
    STATE_ACTIVE,
    Account,
    AccountSnapshot,
    Investment,
    InvestmentSnapshot,
    InvestmentTransaction,
    Transaction,
    TransactionClassification,
    TransactionLink,
)
from findash.invest import transit_choices
from findash.invest.origins import add_business_days
from findash.invest.portfolio import bank_cents, position_label

WINDOW_BEFORE_BDAYS, WINDOW_AFTER_BDAYS = 3, 5
SAME_PURCHASE_BDAYS = 1  # saída da conta e compra registrada (BUY) com até 1 dia útil de diferença
TOLERANCE_PCT = Decimal("0.06")
TOLERANCE_MIN_CENTS = 100
SINGLE_CANDIDATE_MAX_PCT = Decimal("0.50")  # candidato único: casa com diferença maior, mas não com qualquer coisa
GROWTH_MIN_PCT = Decimal("0.01")  # sem quantidade: alta menor que isso é rendimento ou oscilação, não aporte
MAX_COMBINATION = 4
MAX_POOL = 12


@dataclass(frozen=True)
class Arrival:
    day: date  # foto que mostrou a posição nova
    investment_id: str
    cents: int


@dataclass(frozen=True)
class Purchase:
    """Compra registrada (BUY) sem saída da conta ligada a ela."""

    id: str
    day: date
    investment_id: str
    cents: int


@dataclass
class Outflow:
    transaction_id: str
    day: date
    cents: int  # positivo
    description: str
    investment_ids: frozenset[str] | None = None  # ativo(s) da compra ligada, quando há
    arrived_on: date | None = None  # data da foto que confirmou a chegada
    manual: str | None = None  # "chegou" | "ignorar" (escolha sua)
    suggestion: str | None = None  # ativo provável, para o botão "já chegou (é o ativo X)"

    @property
    def until(self) -> date:
        return add_business_days(self.day, WINDOW_AFTER_BDAYS)

    def in_transit(self, as_of: date) -> bool:
        if self.manual == transit_choices.IGNORED or self.day > as_of or as_of > self.until:
            return False
        return self.arrived_on is None or self.arrived_on > as_of


@dataclass
class WealthDay:
    day: date
    portfolio_cents: int  # carteira como no app do banco
    in_transit_cents: int

    @property
    def total_cents(self) -> int:
        return self.portfolio_cents + self.in_transit_cents


@dataclass
class Wealth:
    day: date  # foto mais recente da carteira
    portfolio_cents: int
    in_transit: list[Outflow]
    series: list[WealthDay]
    assets: list[tuple[str, str]] = field(default_factory=list)  # (id, rótulo) da foto mais recente

    @property
    def in_transit_cents(self) -> int:
        return sum(o.cents for o in self.in_transit)

    @property
    def total_cents(self) -> int:
        return self.portfolio_cents + self.in_transit_cents


def tolerance(cents: int) -> int:
    return max(TOLERANCE_MIN_CENTS, int(abs(cents) * TOLERANCE_PCT))


Rows = dict[date, dict[str, tuple[Investment, InvestmentSnapshot]]]


def _snapshots(session: Session) -> Rows:
    by_day: Rows = defaultdict(dict)
    for snap, inv in session.execute(
        select(InvestmentSnapshot, Investment).join(Investment, Investment.id == InvestmentSnapshot.investment_id)
    ):
        by_day[snap.snapshot_date][inv.id] = (inv, snap)
    return by_day


def arrivals(by_day: Rows) -> list[Arrival]:
    """Aumentos de posição entre fotos consecutivas."""
    days = sorted(by_day)
    events: list[Arrival] = []
    for previous_day, current_day in pairwise(days):
        before_all = by_day[previous_day]
        for investment_id, (inv, after) in by_day[current_day].items():
            before = before_all.get(investment_id)
            cents = _growth(inv, before[1] if before else None, after)
            if cents > 0:
                events.append(Arrival(current_day, investment_id, cents))
    return events


def _growth(inv: Investment, before: InvestmentSnapshot | None, after: InvestmentSnapshot) -> int:
    value_after = bank_cents(inv, after)
    if value_after <= 0:
        return 0
    value_before = bank_cents(inv, before) if before is not None else 0
    if value_before <= 0:
        return value_after  # ativo novo (ou que voltou a ter saldo)
    if before.quantity is not None and after.quantity is not None and after.quantity > 0:
        bought = after.quantity - before.quantity
        if bought <= 0:
            return 0
        return int((Decimal(value_after) * bought / after.quantity).quantize(Decimal(1)))
    grown = value_after - value_before
    return grown if grown > max(TOLERANCE_MIN_CENTS, int(value_before * GROWTH_MIN_PCT)) else 0


def outflows(session: Session, since: date) -> list[Outflow]:
    """Saídas da conta para investimento (movimento "aporte") a partir de `since`."""
    rows = session.execute(
        select(Transaction.id, Transaction.date, Transaction.amount_normalized_cents, Transaction.description)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Account.type == "BANK",
            Transaction.date >= since,
            TransactionClassification.movement_type == "aporte",
            Transaction.amount_normalized_cents < 0,
        )
        .order_by(Transaction.date, Transaction.id)
    ).all()
    ids = [r[0] for r in rows]
    linked = dict(
        session.execute(
            select(TransactionLink.transaction_id, InvestmentTransaction.investment_id)
            .join(InvestmentTransaction, InvestmentTransaction.id == TransactionLink.investment_transaction_id)
            .where(TransactionLink.kind == "investimento", TransactionLink.transaction_id.in_(ids or ["-"]))
        ).all()
    )
    return [
        Outflow(tx_id, day, -cents, description or "", frozenset({linked[tx_id]}) if tx_id in linked else None)
        for tx_id, day, cents, description in rows
    ]


def purchases(session: Session, since: date) -> list[Purchase]:
    """Compras (BUY) registradas a partir de `since` que nenhuma saída da conta já tem ligada."""
    linked = set(
        session.scalars(select(TransactionLink.investment_transaction_id).where(TransactionLink.kind == "investimento"))
    )
    rows = session.scalars(
        select(InvestmentTransaction)
        .where(InvestmentTransaction.type == "BUY", InvestmentTransaction.date >= since)
        .order_by(InvestmentTransaction.date, InvestmentTransaction.id)
    )
    return [
        Purchase(r.id, r.date, r.investment_id, abs(r.net_amount_cents or r.amount_cents or 0))
        for r in rows
        if r.id not in linked and (r.net_amount_cents or r.amount_cents)
    ]


def _same_purchase_days(a: date, b: date) -> bool:
    lo, hi = min(a, b), max(a, b)
    return add_business_days(lo, SAME_PURCHASE_BDAYS) >= hi


def attach_purchases(items: list[Outflow], buys: list[Purchase]) -> list[Purchase]:
    """Liga cada saída à(s) compra(s) registrada(s) do mesmo dia com valor parecido; devolve as que sobram
    (pagas de outro lugar: ficam com a chegada do próprio ativo)."""
    free = list(buys)
    for o in items:
        if o.investment_ids is not None:
            continue
        near = [b for b in free if _same_purchase_days(b.day, o.day)]
        found: tuple[int, tuple[Purchase, ...]] | None = None
        for size in range(1, min(MAX_COMBINATION, len(near)) + 1):
            for group in combinations(near, size):
                diff = abs(o.cents - sum(b.cents for b in group))
                if diff <= tolerance(o.cents) and (found is None or diff < found[0]):
                    found = (diff, group)
            if found is not None:
                break
        if found is not None:
            o.investment_ids = frozenset(b.investment_id for b in found[1])
            free = [b for b in free if b not in found[1]]
    return free


def match(
    items: list[Outflow],
    events: list[Arrival],
    *,
    buys: list[Purchase] | tuple = (),
    choices: dict[str, transit_choices.Choice] | None = None,
) -> None:
    """Marca `arrived_on` nas saídas que casam com chegadas (cada chegada serve a uma saída só)."""
    used: set[int] = set()
    choices = choices or {}

    def in_window(day: date, start: date, before: int) -> bool:
        return add_business_days(start, -before) <= day <= add_business_days(start, WINDOW_AFTER_BDAYS)

    def candidates(o: Outflow, before: int = WINDOW_BEFORE_BDAYS) -> list[int]:
        return [
            i
            for i, e in enumerate(events)
            if i not in used
            and in_window(e.day, o.day, before)
            and (o.investment_ids is None or e.investment_id in o.investment_ids)
        ]

    def closest(cents: int, pool: list[int]) -> int:
        return min(pool, key=lambda i: (abs(events[i].cents - cents), events[i].day, i))

    def best(cents: int, pool: list[int]) -> tuple[int, ...] | None:
        """Chegada (ou soma de chegadas do mesmo dia) mais próxima do valor, dentro da tolerância."""
        by_day: dict[date, list[int]] = defaultdict(list)
        for i in pool:
            by_day[events[i].day].append(i)
        found: tuple[int, int, tuple[int, ...]] | None = None
        for size in range(1, MAX_COMBINATION + 1):
            for same_day in by_day.values():
                if size > len(same_day) or (size > 1 and len(same_day) > MAX_POOL):
                    continue
                for group in combinations(same_day, size):
                    diff = abs(cents - sum(events[i].cents for i in group))
                    if diff <= tolerance(cents) and (found is None or (diff, size) < found[:2]):
                        found = (diff, size, group)
            if found is not None:
                break
        return found[2] if found else None

    def arrive(o: Outflow, group: tuple[int, ...] | list[int]) -> None:
        used.update(group)
        o.arrived_on = max(events[i].day for i in group)

    # (1) escolha manual
    for o in items:
        choice = choices.get(o.transaction_id)
        if choice is None:
            continue
        o.manual = choice.action
        if choice.action == transit_choices.ARRIVED:
            pool = [i for i in candidates(o) if events[i].investment_id == choice.investment_id]
            if pool:
                arrive(o, [closest(o.cents, pool)])
            else:
                o.arrived_on = o.day  # você disse que chegou: não fica em trânsito
    auto = [o for o in items if o.manual is None]
    # compras pagas de outro lugar ficam com a chegada do próprio ativo
    for b in buys:
        pool = [
            i
            for i, e in enumerate(events)
            if i not in used and e.investment_id == b.investment_id and in_window(e.day, b.day, WINDOW_BEFORE_BDAYS)
        ]
        if pool:
            used.add(closest(b.cents, pool))
    # (2) valor e data
    for o in auto:
        group = best(o.cents, candidates(o))
        if group:
            arrive(o, group)
    # (3) saídas do mesmo dia somadas
    by_day: dict[date, list[Outflow]] = defaultdict(list)
    for o in auto:
        if o.arrived_on is None:
            by_day[o.day].append(o)
    for same_day in by_day.values():
        if len(same_day) < 2:
            continue
        pool = sorted({i for o in same_day for i in candidates(o)})
        group = best(sum(o.cents for o in same_day), pool)
        if group:
            used.update(group)
            for o in same_day:
                o.arrived_on = max(events[i].day for i in group)
    # (4) candidato único de D0 a D+5 úteis
    for o in auto:
        if o.arrived_on is not None:
            continue
        pool = candidates(o, before=0)
        if len(pool) == 1 and abs(events[pool[0]].cents - o.cents) <= o.cents * SINGLE_CANDIDATE_MAX_PCT:
            arrive(o, pool)
    # sugestão para o botão "já chegou (é o ativo X)"
    for o in items:
        if o.arrived_on is not None:
            continue
        if o.investment_ids is not None and len(o.investment_ids) == 1:
            o.suggestion = next(iter(o.investment_ids))
        else:
            pool = candidates(o)
            o.suggestion = events[closest(o.cents, pool)].investment_id if pool else None


def wealth(session: Session, today: date) -> Wealth | None:
    """Patrimônio total de hoje e a série diária (um ponto por foto da carteira)."""
    by_day = _snapshots(session)
    if not by_day:
        return None
    portfolio = {day: sum(bank_cents(inv, snap) for inv, snap in rows.values()) for day, rows in by_day.items()}
    days = sorted(portfolio)
    first, last = days[0], days[-1]
    items = [o for o in outflows(session, first) if o.day > first]
    buys = attach_purchases(items, purchases(session, first - timedelta(days=7)))
    match(items, arrivals(by_day), buys=buys, choices=transit_choices.load(session))
    as_of_today = max(today, last)
    series = []
    for day in days:
        as_of = as_of_today if day == last else day  # o último ponto é o de hoje, igual ao número principal
        series.append(WealthDay(day, portfolio[day], sum(o.cents for o in items if o.in_transit(as_of))))
    assets = sorted(
        ((inv.id, position_label(inv)) for inv, snap in by_day[last].values() if bank_cents(inv, snap) > 0),
        key=lambda a: a[1],
    )
    return Wealth(last, portfolio[last], [o for o in items if o.in_transit(as_of_today)], series, assets)


@dataclass
class AccountBalances:
    day: date
    bank_cents: int
    card_bill_cents: int  # fatura em aberto (positivo = dívida)


def account_balances(session: Session) -> AccountBalances | None:
    """Saldo da conta corrente e fatura em aberto na foto mais recente das contas (fora do patrimônio)."""
    day = session.scalar(select(func.max(AccountSnapshot.snapshot_date)))
    if day is None:
        return None
    values = {"BANK": 0, "CREDIT": 0}
    for kind, balance in session.execute(
        select(Account.type, AccountSnapshot.balance_cents)
        .join(Account, Account.id == AccountSnapshot.account_id)
        .where(AccountSnapshot.snapshot_date == day)
    ):
        if kind in values:
            values[kind] += balance or 0
    return AccountBalances(day, values["BANK"], values["CREDIT"])
