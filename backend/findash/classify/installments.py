"""Compromissos de parcelas: o que já está comprometido nos meses seguintes.

Parcelas não são gastos fixos. Cada compra parcelada é identificada por (cartão, contraparte,
data da compra, total de parcelas). O valor da parcela NÃO entra na identificação: a primeira
parcela costuma ter centavos de arredondamento a mais. A partir da parcela mais recente (n/N),
as N - n restantes são projetadas uma por mês.

O mês de cada parcela é o MESMO critério do resumo (mês da data da transação), para que uma
parcela nunca conte como despesa de um mês e, de novo, como compromisso do mês seguinte.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.classify.text import counterparty_key, normalize_counterparty
from findash.db.models import STATE_ACTIVE, Transaction, TransactionClassification


@dataclass
class Purchase:
    label: str
    total_installments: int
    known: dict[int, tuple[str, int]] = field(default_factory=dict)  # n -> (mês AAAA-MM, centavos)

    @property
    def latest(self) -> tuple[int, str, int]:
        n = max(self.known)
        month, cents = self.known[n]
        return n, month, cents

    def schedule(self) -> dict[int, tuple[str, int]]:
        """Mês e valor de cada parcela conhecida ou projetada."""
        months = dict(self.known)
        n, month, cents = self.latest
        for k in range(n + 1, self.total_installments + 1):
            months[k] = (add_months(month, k - n), cents)
        return months


def purchases(session: Session) -> list[Purchase]:
    rows = session.scalars(
        select(Transaction)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Transaction.total_installments > 1,
            TransactionClassification.movement_type == "despesa",
        )
        .order_by(Transaction.date, Transaction.id)
    )
    groups: dict[tuple, Purchase] = {}
    for tx in rows:
        name = normalize_counterparty(tx.description)
        key = (tx.account_id, counterparty_key(name), tx.purchase_date, tx.total_installments)
        purchase = groups.setdefault(key, Purchase(name, tx.total_installments))
        if tx.installment_number:
            purchase.known[tx.installment_number] = (f"{tx.date:%Y-%m}", abs(tx.amount_normalized_cents))
    return [p for p in groups.values() if p.known]


def commitments_after(session: Session, month: str) -> dict[str, int]:
    """Total de parcelas (centavos, positivo) por mês POSTERIOR a `month` (AAAA-MM)."""
    totals: dict[str, int] = defaultdict(int)
    for purchase in purchases(session):
        for installment_month, cents in purchase.schedule().values():
            if installment_month > month:
                totals[installment_month] += cents
    return dict(sorted(totals.items()))


def add_months(month: str, count: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + (mon - 1) + count
    return f"{index // 12:04d}-{index % 12 + 1:02d}"
