"""Gastos fixos do mês: a ÚNICA conta usada pelas telas Gastos, Fixos, Plano e Visão geral.

- "Fixo" de uma transação é transaction_classifications.is_fixed (override da transação > regra de
  gasto fixo não desmarcada > variável; ver recurrence.apply_fixed_flags).
- Pago no mês = soma das transações fixas do mês (despesas − estornos). É o número da tela Gastos.
- Cada regra de gasto fixo tem um estado:
    ativo       conta no total mensal;
    inativo     automática sem pagamento há mais de max(45 dias, 1,5 × intervalo típico) — fora do
                total (ex.: assinatura cancelada). A escolha manual "sim" continua vencendo;
    desmarcado  escolha manual "não".
- A vencer no mês corrente = regras ativas que ainda não cobraram neste mês (valor = média mensal).
- Total mensal = soma da média mensal das regras ativas.
- Transações marcadas como fixas "só esta" (sem regra) entram no pago do mês, agrupadas por contraparte.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.classify.summary import month_bounds
from findash.db.models import (
    RULE_NO,
    RULE_YES,
    STATE_ACTIVE,
    RecurringRule,
    Transaction,
    TransactionClassification,
)

INACTIVE_MIN_DAYS = 45
INACTIVE_FACTOR = 1.5
ACTIVE, INACTIVE, OFF = "ativo", "inativo", "desmarcado"
HISTORY_MONTHS = 6


def inactive_after_days(rule: RecurringRule) -> int:
    return max(INACTIVE_MIN_DAYS, math.ceil(INACTIVE_FACTOR * (rule.median_interval_days or 30)))


def data_date(session: Session) -> date | None:
    """Data do dado mais recente do banco: referência para 'sem pagamento há N dias'."""
    return session.scalar(select(func.max(Transaction.date)).where(Transaction.state == STATE_ACTIVE))


def rule_state(rule: RecurringRule, last_payment: date | None, as_of: date | None) -> tuple[str, bool]:
    """(estado, parado): parado = sem pagamento além do limite (informativo para escolhas manuais)."""
    stale = bool(last_payment and as_of and (as_of - last_payment).days > inactive_after_days(rule))
    if rule.status == RULE_NO:
        return OFF, stale
    if rule.status == RULE_YES:
        return ACTIVE, stale
    return (INACTIVE if stale else ACTIVE), stale


@dataclass
class FixedItem:
    key: str
    label: str | None
    category: str | None
    rule_id: int | None  # None = só transações marcadas uma a uma
    status: str | None  # automatico | manual_sim | manual_nao
    state: str
    stale: bool
    expected_cents: int  # média mensal
    paid_cents: int = 0  # neste mês
    last_payment: date | None = None
    last_cents: int | None = None
    pending_cents: int = 0  # ainda deve cair neste mês
    count: int = 0  # transações fixas neste mês


@dataclass
class FixedMonth:
    month: str
    as_of: date | None
    items: list[FixedItem] = field(default_factory=list)

    @property
    def paid_cents(self) -> int:
        return sum(i.paid_cents for i in self.items)

    @property
    def pending_cents(self) -> int:
        return sum(i.pending_cents for i in self.items)

    @property
    def monthly_cents(self) -> int:
        """Total mensal: média das regras ativas."""
        return sum(i.expected_cents for i in self.items if i.rule_id is not None and i.state == ACTIVE)


def fixed_month(session: Session, month: str, *, today: date) -> FixedMonth:
    start, end = month_bounds(month)
    as_of = data_date(session)
    rules = {r.id: r for r in session.scalars(select(RecurringRule).where(RecurringRule.kind == "fixo"))}
    last = {
        rule_id: (day, cents)
        for rule_id, day, cents in session.execute(
            select(TransactionClassification.recurring_rule_id, Transaction.date, Transaction.amount_normalized_cents)
            .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
            .where(
                Transaction.state == STATE_ACTIVE,
                TransactionClassification.recurring_rule_id.in_(list(rules) or [-1]),
                TransactionClassification.movement_type == "despesa",
            )
            .order_by(Transaction.date)
        )
    }
    result = FixedMonth(month, as_of)
    by_rule: dict[int, FixedItem] = {}
    for rule in rules.values():
        last_day, last_cents = last.get(rule.id, (None, None))
        state, stale = rule_state(rule, last_day, as_of)
        item = FixedItem(
            rule.counterparty_key,
            rule.counterparty,
            rule.category,
            rule.id,
            rule.status,
            state,
            stale,
            rule.avg_monthly_cents or 0,
            last_payment=last_day,
            last_cents=abs(last_cents) if last_cents is not None else None,
        )
        by_rule[rule.id] = item
        result.items.append(item)

    singles: dict[str, FixedItem] = {}
    rows = session.execute(
        select(TransactionClassification, Transaction)
        .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Transaction.date >= start,
            Transaction.date < end,
            TransactionClassification.is_fixed.is_(True),
        )
    )
    for cls, tx in rows:
        spent = -tx.amount_normalized_cents
        rule = rules.get(cls.recurring_rule_id) if cls.recurring_rule_id else None
        if rule is not None and rule.status != RULE_NO:
            item = by_rule[rule.id]
        else:
            key = cls.counterparty_key or f"?{tx.id}"
            item = singles.get(key)
            if item is None:
                item = FixedItem(key, cls.counterparty or tx.description, cls.category, None, None, ACTIVE, False, 0)
                singles[key] = item
                result.items.append(item)
            item.last_payment = max(item.last_payment or tx.date, tx.date)
        item.paid_cents += spent
        item.count += cls.movement_type == "despesa"

    current = f"{today:%Y-%m}"
    for item in by_rule.values():
        if item.state != ACTIVE or item.paid_cents > 0:
            continue
        if month > current or (month == current and item.expected_cents > 0):
            item.pending_cents = item.expected_cents
    result.items.sort(
        key=lambda i: (
            i.rule_id is None,
            {ACTIVE: 0, INACTIVE: 1, OFF: 2}[i.state],
            -(i.paid_cents or i.expected_cents),
            i.label or "",
        )
    )
    return result


# ------------------------------------------------------------------ regra criada pela interface


def counterparty_history(session: Session, key: str, *, months: int = HISTORY_MONTHS) -> dict:
    """Média mensal, meses, intervalo típico e datas das despesas (sem parcelas) de uma contraparte."""
    latest = data_date(session)
    if latest is None:
        return {}
    index = latest.year * 12 + latest.month - 1 - (months - 1)
    window_start = date(index // 12, index % 12 + 1, 1)
    rows = session.execute(
        select(
            Transaction.date,
            Transaction.amount_normalized_cents,
            TransactionClassification.counterparty,
            TransactionClassification.category,
            Transaction.total_installments,
        )
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(
            Transaction.state == STATE_ACTIVE,
            TransactionClassification.counterparty_key == key,
            TransactionClassification.movement_type == "despesa",
            Transaction.date >= window_start,
        )
        .order_by(Transaction.date)
    ).all()
    rows = [r for r in rows if (r.total_installments or 0) <= 1]
    if not rows:
        return {}
    month_keys = {(r.date.year, r.date.month) for r in rows}
    first_per_month: dict[tuple[int, int], date] = {}
    for r in rows:
        k = (r.date.year, r.date.month)
        first_per_month[k] = min(first_per_month.get(k, r.date), r.date)
    days = sorted(first_per_month.values())
    interval = int(median((b - a).days for a, b in itertools.pairwise(days))) if len(days) > 1 else None
    total = sum(-r.amount_normalized_cents for r in rows)
    return {
        "avg_monthly_cents": int((Decimal(total) / len(month_keys)).quantize(Decimal(1), ROUND_HALF_UP)),
        "months_count": len(month_keys),
        "median_interval_days": interval,
        "first_date": rows[0].date,
        "last_date": rows[-1].date,
        "counterparty": Counter(r.counterparty for r in rows).most_common(1)[0][0],
        "category": Counter(r.category for r in rows).most_common(1)[0][0],
    }


def set_counterparty_fixed(
    session: Session, key: str, fixed: bool, *, now: datetime, label: str | None = None, category: str | None = None
) -> tuple[RecurringRule, str | None]:
    """'Contraparte é fixa' (sim/não): cria ou atualiza a regra manual. Devolve (regra, status anterior ou None)."""
    rule = session.scalar(
        select(RecurringRule).where(RecurringRule.kind == "fixo", RecurringRule.counterparty_key == key)
    )
    status = RULE_YES if fixed else RULE_NO
    if rule is not None:
        previous = rule.status
        if rule.status != status:
            rule.status, rule.status_changed_at, rule.updated_at = status, now, now
        return rule, previous
    history = counterparty_history(session, key)
    rule = RecurringRule(
        kind="fixo",
        counterparty_key=key,
        counterparty=history.get("counterparty") or label,
        category=history.get("category") or category,
        status=status,
        avg_monthly_cents=history.get("avg_monthly_cents"),
        months_count=history.get("months_count"),
        median_interval_days=history.get("median_interval_days"),
        first_date=history.get("first_date"),
        last_date=history.get("last_date"),
        detected=False,
        created_at=now,
        updated_at=now,
        status_changed_at=now,
    )
    session.add(rule)
    session.flush()
    return rule, None


def remove_rule(session: Session, rule_id: int) -> None:
    """Desfaz uma regra criada pela interface (as classificações são religadas no próximo recálculo)."""
    for cls in session.scalars(
        select(TransactionClassification).where(TransactionClassification.recurring_rule_id == rule_id)
    ):
        cls.recurring_rule_id = None
    session.flush()
    rule = session.get(RecurringRule, rule_id)
    if rule is not None:
        session.delete(rule)
    session.flush()


def refresh_manual_rules(session: Session, rules: list[RecurringRule], *, now: datetime) -> None:
    """Regras manuais que a detecção não encontra: média e datas seguem o histórico da contraparte."""
    by_key: dict[str, list[RecurringRule]] = defaultdict(list)
    for rule in rules:
        if rule.kind == "fixo":
            by_key[rule.counterparty_key].append(rule)
    for key, items in by_key.items():
        history = counterparty_history(session, key)
        if not history:
            continue
        for rule in items:
            values = {
                k: history[k]
                for k in ("avg_monthly_cents", "months_count", "median_interval_days", "first_date", "last_date")
            }
            if any(getattr(rule, k) != v for k, v in values.items()):
                for k, v in values.items():
                    setattr(rule, k, v)
                rule.updated_at = now
