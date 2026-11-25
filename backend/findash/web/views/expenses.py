"""Gastos do mês: categorias, dia a dia × extraordinários, fixo × variável, essencial × não essencial e a lista."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.classify.actions import kind_options
from findash.classify.fixed import fixed_month
from findash.classify.loans import open_loans
from findash.classify.personal_rules import RULE_NAME
from findash.classify.summary import month_bounds, month_summary
from findash.db.models import STATE_ACTIVE, Account, ClassificationOverride, Transaction, TransactionClassification
from findash.web.views.common import iso

ACCOUNT_KIND = {"BANK": "conta", "CREDIT": "cartao"}
CATEGORY_TYPES = ("despesa", "estorno")
_PATTERN = re.compile(r"(?:contém|contraparte) '([^']+)'")


def source_of(cls: TransactionClassification, override: ClassificationOverride | None) -> str:
    """De onde veio a classificação, em termos de tela: 'manual', 'regra_pessoal' ou 'automatico'."""
    if override is not None and any(
        v is not None for v in (override.movement_type, override.category, override.fixed, override.extraordinary)
    ):
        return "manual"
    if (cls.movement_rule or "").startswith("pessoal") or cls.rule_level == "pessoal":
        return "regra_pessoal"
    return "automatico"


def rule_pattern(cls: TransactionClassification) -> str | None:
    """O texto que a regra reconheceu (sem número nem nome interno da regra)."""
    for text in (cls.rule_detail, cls.movement_rule):
        match = _PATTERN.search(text or "")
        if match:
            return match.group(1).split(" [")[0]
    return None


def transaction_json(
    tx: Transaction, cls: TransactionClassification, account: Account, override: ClassificationOverride | None
) -> dict:
    installment = None
    if tx.installment_number and tx.total_installments and tx.total_installments > 1:
        installment = f"{tx.installment_number}/{tx.total_installments}"
    return {
        "id": tx.id,
        "date": iso(tx.date),
        "description": tx.description,
        "counterparty": cls.counterparty,
        "amount": tx.amount_normalized_cents,
        "account": ACCOUNT_KIND.get(account.type, account.type.lower()),
        "status": tx.status,
        "movement_type": cls.movement_type,
        "movement_rule": cls.movement_rule,
        "category": cls.category,
        "essential": cls.essential,
        "is_fixed": cls.is_fixed,
        "extraordinary": cls.extraordinary,
        "fixed_source": (
            "transacao"
            if override is not None and override.fixed is not None
            else "regra"
            if cls.recurring_rule_id
            else None
        ),
        "rule_level": cls.rule_level,
        "rule_pattern": rule_pattern(cls),
        "installment": installment,
        "source": source_of(cls, override),
        "from_interface_rule": RULE_NAME in (cls.rule_detail or "") or RULE_NAME in (cls.movement_rule or ""),
        "category_editable": cls.movement_type in CATEGORY_TYPES,
        "kind_options": list(kind_options(account.type, tx.amount_normalized_cents)),
        "counterparty_kind": cls.counterparty_kind,
        "has_counterparty": bool(cls.counterparty_key),
        "override": None
        if override is None
        else {
            "category": override.category,
            "fixed": override.fixed,
            "movement_type": override.movement_type,
            "extraordinary": override.extraordinary,
        },
    }


def month_transactions(session: Session, month: str) -> list[dict]:
    start, end = month_bounds(month)
    rows = session.execute(
        select(Transaction, TransactionClassification, Account)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.state == STATE_ACTIVE, Transaction.date >= start, Transaction.date < end)
        .order_by(Transaction.date.desc(), Transaction.occurred_at.desc(), Transaction.id)
    )
    rows = rows.all()
    overrides = {
        o.transaction_id: o
        for o in session.scalars(
            select(ClassificationOverride).where(ClassificationOverride.transaction_id.in_([t.id for t, _, _ in rows]))
        )
    }
    return [transaction_json(tx, cls, acc, overrides.get(tx.id)) for tx, cls, acc in rows]


def single_transaction(session: Session, transaction_id: str) -> dict | None:
    row = session.execute(
        select(Transaction, TransactionClassification, Account)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.id == transaction_id)
    ).first()
    if row is None:
        return None
    tx, cls, acc = row
    return transaction_json(tx, cls, acc, session.get(ClassificationOverride, transaction_id))


def expenses(session: Session, month: str, *, today: date) -> dict:
    s = month_summary(session, month)
    fixed = fixed_month(session, month, today=today)
    transactions = month_transactions(session, month)
    counts: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t["movement_type"] == "despesa":
            counts[t["category"] or "A classificar"] += 1
    return {
        "month": month,
        "total": s.expenses_total_cents,
        "count": s.expenses_count,
        "by_category": [{"name": k, "cents": v, "count": counts.get(k, 0)} for k, v in s.expenses_by_category.items()],
        "fixed": {
            "fixed": fixed.paid_cents,
            "variable": s.expenses_total_cents - fixed.paid_cents,
            "pending": fixed.pending_cents,
        },
        "everyday": s.everyday_cents,
        "extraordinary": {"cents": s.extraordinary_cents, "count": s.extraordinary_count},
        "paid_with_redemptions": s.paid_with_redemptions_cents,
        "income": s.income_cents + s.investment_income_cents,
        "result": s.result_cents,
        "result_everyday": s.result_everyday_cents,
        "savings_rate": s.savings_rate,
        "savings_rate_everyday": s.savings_rate_everyday,
        "flows": {
            "contributions": s.contributions_cents,
            "redemptions": s.redemptions_cents,
            "net": s.contributions_cents - s.redemptions_cents,
        },
        "reimbursements": s.reimbursements_cents,
        "reimbursements_uncategorized": s.reimbursements_uncategorized_cents,
        "refunds_without_origin": s.refunds_without_origin_cents,
        "neutral": {
            "loans_out": s.loans_out_cents,
            "loans_in": s.loans_in_cents,
            "own_transfers": s.own_transfers_in_cents,
        },
        "loans": [
            {
                "key": loan.key,
                "counterparty": loan.label,
                "lent": loan.lent_cents,
                "returned": loan.returned_cents,
                "open": loan.open_cents,
                "last_date": iso(loan.last_date),
            }
            for loan in open_loans(session)
        ],
        "essential": {
            "essential": s.essential_cents,
            "non_essential": s.non_essential_cents,
            "no_flag": s.no_flag_cents,
        },
        "transactions": transactions,
    }
