"""Fixos e compromissos: regras de recorrência (gasto fixo e salário) e parcelas futuras."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.classify.fixed import FixedItem, data_date, fixed_month, inactive_after_days, rule_state
from findash.classify.installments import commitments_after
from findash.classify.salary import SalarySchedule
from findash.db.models import RULE_NO, STATE_ACTIVE, RecurringRule, Transaction, TransactionClassification
from findash.web.views.common import iso

MODE_TO_STATUS = {"auto": "automatico", "sim": "manual_sim", "nao": "manual_nao"}


def rule_json(session: Session, rule: RecurringRule) -> dict:
    last = session.execute(
        select(Transaction.date, Transaction.amount_normalized_cents)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(TransactionClassification.recurring_rule_id == rule.id, Transaction.state == STATE_ACTIVE)
        .order_by(Transaction.date.desc())
        .limit(1)
    ).first()
    first = session.scalar(
        select(func.min(Transaction.date))
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(TransactionClassification.recurring_rule_id == rule.id, Transaction.state == STATE_ACTIVE)
    )
    state, stale = rule_state(rule, last[0] if last else None, data_date(session))
    schedule = SalarySchedule.from_rule(rule) if rule.paycheck_cents else None
    return {
        "id": rule.id,
        "kind": rule.kind,
        "counterparty": rule.counterparty,
        "category": rule.category,
        "status": rule.status,
        "manual": rule.status != "automatico",
        "active": rule.status != RULE_NO,
        "state": state if rule.kind == "fixo" else ("desmarcado" if rule.status == RULE_NO else "ativo"),
        "stale": stale,
        "inactive_after_days": inactive_after_days(rule),
        "avg_monthly": rule.avg_monthly_cents,
        "months_count": rule.months_count,
        "detected": rule.detected,
        "interval_days": rule.median_interval_days,
        "paycheck": rule.paycheck_cents,
        "schedule": schedule.label if schedule else None,
        "annual_average": schedule.monthly_average_cents(rule.paycheck_cents) if schedule else None,
        "last_payment": {"date": iso(last[0]), "cents": abs(last[1])} if last else None,
        "first_payment": iso(first),
    }


def _item_json(item: FixedItem) -> dict:
    return {
        "key": item.key,
        "counterparty": item.label,
        "category": item.category,
        "rule_id": item.rule_id,
        "state": item.state,
        "paid": item.paid_cents,
        "pending": item.pending_cents,
        "expected": item.expected_cents,
        "count": item.count,
        "last_payment": iso(item.last_payment),
    }


def fixed(session: Session, *, today: date) -> dict:
    rules = session.scalars(
        select(RecurringRule).order_by(RecurringRule.kind, RecurringRule.avg_monthly_cents.desc(), RecurringRule.id)
    ).all()
    items = [rule_json(session, r) for r in rules]
    month = f"{today:%Y-%m}"
    current = fixed_month(session, month, today=today)
    by_rule = {i.rule_id: i for i in current.items if i.rule_id is not None}
    for r in items:
        if r["kind"] == "fixo":
            item = by_rule.get(r["id"])
            r["this_month"] = {"paid": item.paid_cents if item else 0, "pending": item.pending_cents if item else 0}
    order = {"ativo": 0, "inativo": 1, "desmarcado": 2}
    fixed_rules = sorted(
        (r for r in items if r["kind"] == "fixo"), key=lambda r: (order[r["state"]], -(r["avg_monthly"] or 0), r["id"])
    )
    commitments = commitments_after(session, month)
    return {
        "fixed": fixed_rules,
        "salary": [r for r in items if r["kind"] == "salario"],
        "fixed_monthly": current.monthly_cents,
        "month": {
            "month": month,
            "paid": current.paid_cents,
            "pending": current.pending_cents,
            "singles": [_item_json(i) for i in current.items if i.rule_id is None],
        },
        "commitments": {
            "months": [{"month": m, "cents": c} for m, c in commitments.items()],
            "total": sum(commitments.values()),
        },
    }
