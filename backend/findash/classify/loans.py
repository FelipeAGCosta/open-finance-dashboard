"""Empréstimos em aberto: emprestado − devolvido, por contraparte (todo o histórico)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import LOAN_IN, LOAN_OUT, STATE_ACTIVE, Transaction, TransactionClassification


@dataclass
class Loan:
    key: str
    label: str | None
    lent_cents: int = 0
    returned_cents: int = 0
    last_date: date | None = None

    @property
    def open_cents(self) -> int:
        return self.lent_cents - self.returned_cents


def open_loans(session: Session) -> list[Loan]:
    rows = session.execute(
        select(
            TransactionClassification.counterparty_key,
            TransactionClassification.counterparty,
            TransactionClassification.movement_type,
            Transaction.amount_normalized_cents,
            Transaction.date,
        )
        .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
        .where(Transaction.state == STATE_ACTIVE, TransactionClassification.movement_type.in_((LOAN_OUT, LOAN_IN)))
        .order_by(Transaction.date)
    )
    loans: dict[str, Loan] = {}
    labels: dict[str, str | None] = defaultdict(lambda: None)
    for key, label, kind, cents, day in rows:
        key = key or "?"
        loan = loans.setdefault(key, Loan(key, label))
        labels[key] = labels[key] or label
        if kind == LOAN_OUT:
            loan.lent_cents += -cents
        else:
            loan.returned_cents += cents
        loan.last_date = day
    return sorted(loans.values(), key=lambda loan: (-loan.open_cents, loan.label or ""))
