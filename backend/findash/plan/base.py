"""Bases do Plano: contas de calendário, média dos gastos essenciais e pagamentos extras do salário."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.classify.salary import SalarySchedule, first_payment, scheduled_salary_rules
from findash.classify.summary import month_bounds
from findash.db.models import REIMBURSEMENT, STATE_ACTIVE, Transaction, TransactionClassification

ESSENTIAL_MONTHS = 6


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(p) for p in month.split("-"))
    index = year * 12 + mon - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass
class EssentialAverage:
    months: list[tuple[str, int]]

    @property
    def average_cents(self) -> int | None:
        return round(sum(v for _, v in self.months) / len(self.months)) if self.months else None


def essential_average(
    session: Session, today: date, *, months: int = ESSENTIAL_MONTHS, first_month: str | None = None
) -> EssentialAverage:
    """Média das despesas essenciais nos últimos `months` meses FECHADOS (que tenham dados)."""
    current = f"{today:%Y-%m}"
    wanted = [
        m for m in (shift_month(current, -back) for back in range(months, 0, -1)) if not first_month or m >= first_month
    ]
    if not wanted:
        return EssentialAverage([])
    # Mesma conta de month_summary().essential_cents (despesas − estornos − reembolsos essenciais), numa consulta só.
    start, _ = month_bounds(wanted[0])
    _, end = month_bounds(wanted[-1])
    totals: dict[str, int] = {m: 0 for m in wanted}
    rows = session.execute(
        select(Transaction.date, Transaction.amount_normalized_cents)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Transaction.date >= start,
            Transaction.date < end,
            TransactionClassification.essential.is_(True),
            TransactionClassification.movement_type.in_(("despesa", "estorno", REIMBURSEMENT)),
        )
    )
    for day, cents in rows:
        totals[f"{day:%Y-%m}"] += -cents
    return EssentialAverage([(m, max(0, totals[m])) for m in wanted])


@dataclass
class ExtraPaycheck:
    paycheck_cents: int  # soma de UM pagamento de cada salário com agenda
    count: int  # pagamentos além do normal no mês
    cents: int


def extra_paycheck(session: Session, month: str) -> ExtraPaycheck:
    """Pagamentos além do normal no mês (ex.: 5ª segunda num salário semanal, 3ª sexta num quinzenal)."""
    paycheck = count = cents = 0
    for rule in scheduled_salary_rules(session):
        schedule = SalarySchedule.from_rule(rule)
        if schedule is None:
            continue
        first = first_payment(session, rule.id)
        anchor = (schedule.reference_payday(first) or first) if first else None
        extra = schedule.extra_paychecks(month, anchor)
        paycheck += rule.paycheck_cents
        count = max(count, extra)
        cents += rule.paycheck_cents * extra
    return ExtraPaycheck(paycheck, count, cents)
