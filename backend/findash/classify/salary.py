"""Salário com agenda (semanal, quinzenal ou mensal): valor esperado por mês e conferência com o recebido.

- A agenda vem de config/settings.yaml (bloco `salario`) e fica gravada na regra de salário detectada.
- Cada pagamento é atribuído ao seu dia de pagamento de referência: o próprio dia ou até `grace_days`
  depois (feriado, fim de semana). Fora disso, o crédito fica "fora do padrão".
- Esperado no mês = valor de cada pagamento × dias de pagamento do mês (semanal: 4 ou 5; quinzenal: 2 ou 3).
- Média mensal ao longo do ano = valor × pagamentos por ano ÷ 12.
- A conferência olha o dia de REFERÊNCIA, e não o dia do crédito, para que um pagamento atrasado que cai
  no mês seguinte não gere alarme falso. No mês em andamento só contam os dias cujo prazo já passou na data
  do dado mais recente.
- O primeiro pagamento marca o início do salário: dias anteriores não contam no esperado.
"""

from __future__ import annotations

import calendar
import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import RULE_NO, STATE_ACTIVE, RecurringRule, Transaction, TransactionClassification

WEEKLY, BIWEEKLY, MONTHLY = "weekly", "biweekly", "monthly"
FREQUENCIES = (WEEKLY, BIWEEKLY, MONTHLY)
PERIODS_PER_YEAR = {WEEKLY: 52, BIWEEKLY: 26, MONTHLY: 12}
REGULAR_PER_MONTH = {WEEKLY: 4, BIWEEKLY: 2, MONTHLY: 1}
# Intervalo mediano entre pagamentos consecutivos aceito para cada frequência (dias).
INTERVALS = {WEEKLY: (5, 9), BIWEEKLY: (12, 16), MONTHLY: (25, 35)}
MIN_ON_SCHEDULE = Decimal("0.8")  # parcela mínima de pagamentos dentro da agenda
WEEKDAY_NAMES = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


@dataclass(frozen=True)
class SalarySchedule:
    frequency: str = MONTHLY
    payday: int = 5  # dia do mês (mensal) ou dia da semana, 0 = segunda (semanal e quinzenal)
    grace_days: int = 3

    def __post_init__(self) -> None:
        if self.frequency not in FREQUENCIES:
            raise ValueError(f"frequência inválida: {self.frequency}")
        if self.frequency == MONTHLY and not 1 <= self.payday <= 31:
            raise ValueError("salário mensal: o dia precisa estar entre 1 e 31")
        if self.frequency != MONTHLY and not 0 <= self.payday <= 6:
            raise ValueError("salário semanal/quinzenal: o dia precisa ser um dia da semana")
        if not 0 <= self.grace_days <= (3 if self.frequency == WEEKLY else 6):
            raise ValueError("tolerância de atraso fora do intervalo aceito")

    @classmethod
    def from_rule(cls, rule: RecurringRule) -> SalarySchedule | None:
        if rule.pay_frequency is None or rule.payday is None:
            return None
        return cls(rule.pay_frequency, rule.payday, rule.grace_days or 0)

    @property
    def label(self) -> str:
        if self.frequency == MONTHLY:
            return f"todo dia {self.payday}"
        weekday = WEEKDAY_NAMES[self.payday]
        return f"toda {weekday}" if self.frequency == WEEKLY else f"a cada 2 semanas, na {weekday}"

    def scheduled_in_month(self, year: int, month: int) -> date:
        return date(year, month, min(self.payday, calendar.monthrange(year, month)[1]))

    def reference_payday(self, day: date, anchor: date | None = None) -> date | None:
        """Dia de pagamento a que o crédito se refere (0 a grace_days de atraso); None fora da agenda."""
        for delay in range(self.grace_days + 1):
            candidate = day - timedelta(days=delay)
            if self._is_payday(candidate, anchor):
                return candidate
        return None

    def _is_payday(self, day: date, anchor: date | None) -> bool:
        if self.frequency == MONTHLY:
            return day == self.scheduled_in_month(day.year, day.month)
        if day.weekday() != self.payday:
            return False
        return self.frequency == WEEKLY or anchor is None or (day - anchor).days % 14 == 0

    def paydays_in_month(self, month: str, anchor: date | None = None) -> list[date]:
        year, mon = (int(part) for part in month.split("-"))
        if self.frequency == MONTHLY:
            return [self.scheduled_in_month(year, mon)]
        day = date(year, mon, 1)
        day += timedelta(days=(self.payday - day.weekday()) % 7)
        result = []
        while day.month == mon:
            if self._is_payday(day, anchor):
                result.append(day)
            day += timedelta(days=7)
        return result

    def matches(self, days: list[date]) -> bool:
        """Os pagamentos seguem esta agenda? (intervalo típico e >= 80% dentro da tolerância)."""
        if len(days) < 2:
            return False
        days = sorted(days)
        low, high = INTERVALS[self.frequency]
        if not low <= median((b - a).days for a, b in itertools.pairwise(days)) <= high:
            return False
        on_schedule = sum(self.reference_payday(d) is not None for d in days)
        return Decimal(on_schedule) / len(days) >= MIN_ON_SCHEDULE

    def monthly_average_cents(self, paycheck_cents: int) -> int:
        per_year = Decimal(paycheck_cents) * PERIODS_PER_YEAR[self.frequency]
        return int((per_year / 12).quantize(Decimal(1), ROUND_HALF_UP))

    def extra_paychecks(self, month: str, anchor: date | None = None) -> int:
        """Pagamentos além do normal no mês (ex.: a 5ª segunda de um salário semanal)."""
        return max(0, len(self.paydays_in_month(month, anchor)) - REGULAR_PER_MONTH[self.frequency])


@dataclass
class SalaryMonth:
    rule_id: int
    counterparty: str | None
    status: str
    schedule: SalarySchedule
    paycheck_cents: int
    paydays: list[date]  # dias de pagamento do mês a partir do início do salário
    started_on: date | None  # dia de referência do primeiro pagamento
    due_paydays: list[date] = field(default_factory=list)  # dias cujo pagamento já deveria ter chegado
    received_cash_cents: int = 0  # pelo dia do crédito na conta
    received_reference_cents: int = 0  # pelo dia de pagamento de referência
    missing_paydays: list[date] = field(default_factory=list)
    shifted: list[tuple[date, date]] = field(default_factory=list)  # (crédito, referência) em meses diferentes
    off_schedule: list[date] = field(default_factory=list)
    unexpected_amounts: list[tuple[date, int]] = field(default_factory=list)

    @property
    def expected_cents(self) -> int:
        return self.paycheck_cents * len(self.paydays)

    @property
    def expected_due_cents(self) -> int:
        return self.paycheck_cents * len(self.due_paydays)

    @property
    def monthly_average_cents(self) -> int:
        return self.schedule.monthly_average_cents(self.paycheck_cents)

    @property
    def in_progress(self) -> bool:
        return len(self.due_paydays) < len(self.paydays)

    @property
    def difference_cents(self) -> int:
        return self.received_reference_cents - self.expected_due_cents

    @property
    def divergent(self) -> bool:
        return self.difference_cents != 0 or bool(self.off_schedule)


def scheduled_salary_rules(session: Session) -> list[RecurringRule]:
    return list(
        session.scalars(
            select(RecurringRule)
            .where(
                RecurringRule.kind == "salario",
                RecurringRule.status != RULE_NO,
                RecurringRule.paycheck_cents.is_not(None),
            )
            .order_by(RecurringRule.id)
        )
    )


def first_payment(session: Session, rule_id: int) -> date | None:
    return session.scalar(
        select(func.min(Transaction.date))
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(TransactionClassification.recurring_rule_id == rule_id, Transaction.state == STATE_ACTIVE)
    )


def salary_months(session: Session, month: str) -> list[SalaryMonth]:
    """Conferência do mês para cada salário com agenda que não foi desmarcado."""
    from findash.classify.summary import month_bounds  # import local: summary importa este módulo

    start, end = month_bounds(month)
    as_of = session.scalar(select(func.max(Transaction.date)).where(Transaction.state == STATE_ACTIVE))
    result = []
    for rule in scheduled_salary_rules(session):
        schedule = SalarySchedule.from_rule(rule)
        if schedule is None:
            continue
        rows = session.execute(
            select(Transaction.date, Transaction.amount_normalized_cents)
            .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
            .where(
                TransactionClassification.recurring_rule_id == rule.id,
                Transaction.state == STATE_ACTIVE,
                Transaction.date >= start,
                Transaction.date < end + timedelta(days=schedule.grace_days),
            )
            .order_by(Transaction.date)
        ).all()
        first = first_payment(session, rule.id)
        started_on = (schedule.reference_payday(first) or first) if first else None
        paydays = [d for d in schedule.paydays_in_month(month, started_on) if started_on is None or d >= started_on]
        item = SalaryMonth(rule.id, rule.counterparty, rule.status, schedule, rule.paycheck_cents, paydays, started_on)
        paid: set[date] = set()
        for day, cents in rows:
            reference = schedule.reference_payday(day, started_on)
            credited_in_month = day < end
            belongs_to_month = reference is not None and start <= reference < end
            if credited_in_month:
                item.received_cash_cents += cents
                if reference is None:
                    item.off_schedule.append(day)
            if belongs_to_month:
                item.received_reference_cents += cents
                paid.add(reference)
            if reference is not None and credited_in_month != belongs_to_month:
                item.shifted.append((day, reference))
            if (belongs_to_month or (credited_in_month and reference is None)) and cents != rule.paycheck_cents:
                item.unexpected_amounts.append((day, cents))
        item.due_paydays = [
            d for d in paydays if d in paid or (as_of is not None and d + timedelta(days=schedule.grace_days) <= as_of)
        ]
        item.missing_paydays = [d for d in item.due_paydays if d not in paid]
        result.append(item)
    return result
