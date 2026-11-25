"""Detecção de gastos fixos e de salário (recorrência mensal da mesma contraparte).

Gasto fixo candidato (despesa, sem parcelas):
- mesma contraparte normalizada em >= 3 meses distintos dos últimos 6 (contados a partir do mês
  da transação mais recente do banco); para "Assinaturas e serviços digitais" bastam 2 meses
  SEGUIDOS (cobrança mensal de serviço digital raramente é coincidência);
- intervalo típico de 25 a 35 dias: mediana dos intervalos entre a PRIMEIRA ocorrência de cada mês;
- no máximo 2 ocorrências por mês em média;
- variação de valor (máx - mín) / média <= 15%; para "Contas da casa" e "Moradia", <= 60%.
Salário candidato (receita na conta): mesmas regras de meses e intervalo (sem limite de
ocorrências por mês: pagamento semanal estável também conta), cada crédito >= R$ 500 e
variação <= 30%. Quando os pagamentos seguem a agenda configurada (semanal, quinzenal ou mensal; ver
findash/classify/salary.py), a regra guarda o valor de cada pagamento e a agenda: é dela que saem o
esperado de cada mês e a conferência.

Tudo o que é detectado vale imediatamente ('automatico'). O usuário pode fixar a escolha
('manual_sim' / 'manual_nao'); a escolha manual vence o algoritmo, persiste entre recálculos e
syncs, e um item desmarcado nunca volta a valer sozinho. Regras automáticas que deixam de ser
detectadas somem; as manuais ficam (com detected = false) e acompanham o histórico da contraparte.
A tela pode criar uma regra manual direto ("esta contraparte é fixa"): ver findash/classify/fixed.py,
onde também ficam o estado ativo/inativo e o total do mês.

Por transação: classification_overrides.fixed (sim/não) vence a regra. O resultado final fica em
transaction_classifications.is_fixed.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.classify.salary import MONTHLY, SalarySchedule
from findash.db.models import (
    RULE_AUTO,
    RULE_NO,
    RULE_STATUSES,
    STATE_ACTIVE,
    ClassificationOverride,
    RecurringRule,
    Transaction,
    TransactionClassification,
)

WINDOW_MONTHS = 6
MIN_MONTHS = 3
SUBSCRIPTIONS = "Assinaturas e serviços digitais"
MIN_MONTHS_SUBSCRIPTION = 2  # desde que sejam meses seguidos
MIN_INTERVAL_DAYS, MAX_INTERVAL_DAYS = 25, 35
MAX_VARIATION = Decimal("0.15")
FLEXIBLE_CATEGORIES = {"Contas da casa", "Moradia"}
MAX_VARIATION_FLEXIBLE = Decimal("0.60")
MAX_PER_MONTH_FIXED = 2  # média de ocorrências por mês acima disso = compra frequente, não fixo
SALARY_MIN_CENTS = 50_000
SALARY_MAX_VARIATION = Decimal("0.30")


@dataclass
class Candidate:
    kind: str
    key: str
    label: str | None
    category: str | None
    avg_monthly_cents: int
    months_count: int
    median_interval_days: int
    variation: Decimal
    first_date: date
    last_date: date
    payment_interval_days: int | None = None
    paycheck_cents: int | None = None
    schedule: SalarySchedule | None = None


@dataclass
class _Occurrence:
    date: date
    amount: int  # centavos, positivo
    label: str | None
    category: str | None


def apply_recurrence(session: Session, *, now: datetime, salary: SalarySchedule) -> tuple[int, int]:
    """Detecta, atualiza recurring_rules e liga as classificações às regras não rejeitadas."""
    latest = session.scalar(select(func.max(Transaction.date)).where(Transaction.state == STATE_ACTIVE))
    if latest is None:
        return 0, 0
    window_start = _month_start(latest, back=WINDOW_MONTHS - 1)

    rows = session.execute(
        select(TransactionClassification, Transaction)
        .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
        .where(TransactionClassification.movement_type.in_(("despesa", "receita")))
        .order_by(Transaction.date, Transaction.id)
    ).all()
    expenses: dict[str, list[_Occurrence]] = defaultdict(list)
    incomes: dict[str, list[_Occurrence]] = defaultdict(list)
    for cls, tx in rows:
        if not cls.counterparty_key or tx.date < window_start:
            continue
        occurrence = _Occurrence(tx.date, abs(tx.amount_normalized_cents), cls.counterparty, cls.category)
        if cls.movement_type == "despesa" and (tx.total_installments or 0) <= 1:
            expenses[cls.counterparty_key].append(occurrence)
        elif cls.movement_type == "receita" and tx.amount_normalized_cents >= SALARY_MIN_CENTS:
            incomes[cls.counterparty_key].append(occurrence)  # receita só existe na conta corrente

    fixed = [c for key, occ in sorted(expenses.items()) if (c := _candidate("fixo", key, occ))]
    salaries = [c for key, occ in sorted(incomes.items()) if (c := _candidate("salario", key, occ, salary))]
    rule_ids = _upsert(session, fixed + salaries, now=now)

    for cls, tx in rows:
        rule_id = None
        if cls.movement_type == "despesa" and (tx.total_installments or 0) <= 1:
            rule_id = rule_ids.get(("fixo", cls.counterparty_key))
        elif cls.movement_type == "receita":
            rule_id = rule_ids.get(("salario", cls.counterparty_key))
        if cls.recurring_rule_id != rule_id:
            cls.recurring_rule_id = rule_id
    apply_fixed_flags(session)
    return len(fixed), len(salaries)


def apply_fixed_flags(session: Session) -> None:
    """is_fixed = override da transação > regra de gasto fixo não desmarcada > variável."""
    session.flush()
    overrides = dict(
        session.execute(
            select(ClassificationOverride.transaction_id, ClassificationOverride.fixed).where(
                ClassificationOverride.fixed.is_not(None)
            )
        ).all()
    )
    rules = {r.id: r for r in session.scalars(select(RecurringRule))}
    for cls in session.scalars(select(TransactionClassification)):
        if cls.movement_type not in ("despesa", "estorno"):
            value = False
        elif cls.transaction_id in overrides:
            value = bool(overrides[cls.transaction_id])
        else:
            rule = rules.get(cls.recurring_rule_id) if cls.recurring_rule_id else None
            value = bool(rule and rule.kind == "fixo" and rule.status != RULE_NO)
        if cls.is_fixed != value:
            cls.is_fixed = value


def _candidate(
    kind: str, key: str, occurrences: list[_Occurrence], schedule: SalarySchedule | None = None
) -> Candidate | None:
    months = {(o.date.year, o.date.month) for o in occurrences}
    category = Counter(o.category for o in occurrences).most_common(1)[0][0]
    if len(months) < MIN_MONTHS and not (
        kind == "fixo"
        and category == SUBSCRIPTIONS
        and len(months) >= MIN_MONTHS_SUBSCRIPTION
        and _has_consecutive(months)
    ):
        return None
    if kind == "fixo" and len(occurrences) > MAX_PER_MONTH_FIXED * len(months):
        return None  # compra frequente (café, mercado), não conta fixa
    # Intervalo entre a primeira ocorrência de cada mês: uma cobrança extra no mês não descaracteriza
    # a recorrência mensal, e um pagador semanal estável continua aparecendo todo mês.
    first_per_month: dict[tuple[int, int], date] = {}
    for o in occurrences:
        month = (o.date.year, o.date.month)
        first_per_month[month] = min(first_per_month.get(month, o.date), o.date)
    days = sorted(first_per_month.values())
    interval = median((b - a).days for a, b in itertools.pairwise(days))
    payment_dates = sorted(o.date for o in occurrences)
    gaps = [(b - a).days for a, b in itertools.pairwise(payment_dates)]
    payment_interval = int(median(gaps)) if gaps else None
    on_schedule = kind == "salario" and schedule is not None and schedule.matches(payment_dates)
    # Pagamentos que seguem a agenda já provam a regularidade; num salário semanal, o intervalo entre a 1ª
    # ocorrência de cada mês falharia quando o emprego começa no meio do mês (1º pagamento dia 19, o seguinte dia 7).
    if not (on_schedule and schedule.frequency != MONTHLY) and not MIN_INTERVAL_DAYS <= interval <= MAX_INTERVAL_DAYS:
        return None
    amounts = [o.amount for o in occurrences]
    mean = Decimal(sum(amounts)) / len(amounts)
    variation = (
        (Decimal(max(amounts) - min(amounts)) / mean).quantize(Decimal("0.0001"), ROUND_HALF_UP) if mean else Decimal(0)
    )
    if kind == "fixo":
        limit = MAX_VARIATION_FLEXIBLE if category in FLEXIBLE_CATEGORIES else MAX_VARIATION
    else:
        limit = SALARY_MAX_VARIATION
    if variation > limit:
        return None
    label = Counter(o.label for o in occurrences).most_common(1)[0][0]
    avg_monthly = int((Decimal(sum(amounts)) / len(months)).quantize(Decimal(1), ROUND_HALF_UP))
    paycheck = None
    if on_schedule:
        # Valor de cada pagamento = mediana; a média mensal sai dele (× pagamentos por ano ÷ 12), e não da
        # soma dos meses observados (o primeiro e o último mês da janela costumam estar incompletos).
        paycheck = int(Decimal(median(amounts)).quantize(Decimal(1), ROUND_HALF_UP))
        avg_monthly = schedule.monthly_average_cents(paycheck)
    return Candidate(
        kind=kind,
        key=key,
        label=label,
        category=category if kind == "fixo" else None,
        avg_monthly_cents=avg_monthly,
        months_count=len(months),
        median_interval_days=int(interval),
        variation=variation,
        first_date=days[0],
        last_date=days[-1],
        payment_interval_days=payment_interval,
        paycheck_cents=paycheck,
        schedule=schedule if on_schedule else None,
    )


def _has_consecutive(months: set[tuple[int, int]]) -> bool:
    index = {year * 12 + month for year, month in months}
    return any(i + 1 in index for i in index)


def _upsert(session: Session, candidates: list[Candidate], *, now: datetime) -> dict[tuple[str, str], int]:
    existing = {(r.kind, r.counterparty_key): r for r in session.scalars(select(RecurringRule))}
    seen: set[tuple[str, str]] = set()
    for c in candidates:
        key = (c.kind, c.key)
        seen.add(key)
        values = {
            "counterparty": c.label,
            "category": c.category,
            "avg_monthly_cents": c.avg_monthly_cents,
            "months_count": c.months_count,
            "median_interval_days": c.median_interval_days,
            "amount_variation": c.variation,
            "first_date": c.first_date,
            "last_date": c.last_date,
            "detected": True,
            "payment_interval_days": c.payment_interval_days,
            "paycheck_cents": c.paycheck_cents,
            "pay_frequency": c.schedule.frequency if c.schedule else None,
            "payday": c.schedule.payday if c.schedule else None,
            "grace_days": c.schedule.grace_days if c.schedule else None,
        }
        rule = existing.get(key)
        if rule is None:
            rule = RecurringRule(
                kind=c.kind, counterparty_key=c.key, status=RULE_AUTO, created_at=now, updated_at=now, **values
            )
            session.add(rule)
            existing[key] = rule
        elif any(getattr(rule, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(rule, name, value)
            rule.updated_at = now
    manual_unseen = []
    for key, rule in list(existing.items()):
        if key in seen:
            continue
        if rule.status == RULE_AUTO:
            session.delete(rule)
            del existing[key]
            continue
        manual_unseen.append(rule)
        if rule.detected:
            rule.detected = False
            rule.updated_at = now
    session.flush()
    from findash.classify.fixed import refresh_manual_rules  # import local: fixed importa summary

    refresh_manual_rules(session, manual_unseen, now=now)
    return {key: rule.id for key, rule in existing.items()}  # 'manual_nao' também liga: a tela mostra o controle


def set_status(session: Session, rule_id: int, status: str, *, now: datetime) -> RecurringRule | None:
    if status not in RULE_STATUSES:
        raise ValueError(f"status inválido: {status}")
    rule = session.get(RecurringRule, rule_id)
    if rule is None:
        return None
    if rule.status != status:
        rule.status = status
        rule.status_changed_at = now
        rule.updated_at = now
    return rule


def _month_start(day: date, back: int) -> date:
    index = day.year * 12 + (day.month - 1) - back
    return date(index // 12, index % 12 + 1, 1)
