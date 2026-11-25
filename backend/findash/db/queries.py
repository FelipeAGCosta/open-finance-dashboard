"""Consultas de leitura usadas pelo `status` (e, depois, pela interface).

Totais de transações consideram só state='ativa': PENDING substituídas ou removidas
continuam no banco como histórico, mas não entram em somas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import (
    STATE_ACTIVE,
    Account,
    Investment,
    InvestmentSnapshot,
    InvestmentTransaction,
    ItemStatus,
    SyncRun,
    Transaction,
)


@dataclass
class AccountBalance:
    label: str
    type: str
    subtype: str | None
    balance_cents: int | None
    credit_limit_cents: int | None
    available_credit_limit_cents: int | None
    currency_code: str | None


@dataclass
class PortfolioGroup:
    type: str | None
    subtype: str | None
    positions: int
    balance_cents: int


SUBTYPE_LABELS = {
    "CHECKING_ACCOUNT": "Conta corrente",
    "SAVINGS_ACCOUNT": "Poupança",
    "CREDIT_CARD": "Cartão de crédito",
}


def last_sync_run(session: Session) -> SyncRun | None:
    return session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))


def last_successful_sync_run(session: Session) -> SyncRun | None:
    return session.scalar(select(SyncRun).where(SyncRun.status == "success").order_by(SyncRun.id.desc()).limit(1))


def item_statuses(session: Session) -> list[ItemStatus]:
    return list(session.scalars(select(ItemStatus)))


def table_counts(session: Session) -> dict[str, int]:
    def count(stmt) -> int:
        return int(session.scalar(stmt) or 0)

    return {
        "contas": count(select(func.count()).select_from(Account)),
        "transações (total)": count(select(func.count()).select_from(Transaction)),
        "  ativas": count(select(func.count()).where(Transaction.state == STATE_ACTIVE)),
        "  ativas PENDING": count(
            select(func.count()).where(Transaction.state == STATE_ACTIVE, Transaction.status == "PENDING")
        ),
        "  substituídas": count(select(func.count()).where(Transaction.state == "substituida")),
        "  removidas": count(select(func.count()).where(Transaction.state == "removida")),
        "investimentos": count(select(func.count()).select_from(Investment)),
        "fotos da carteira (linhas)": count(select(func.count()).select_from(InvestmentSnapshot)),
        "fotos da carteira (dias)": count(select(func.count(func.distinct(InvestmentSnapshot.snapshot_date)))),
        "transações de investimentos": count(select(func.count()).select_from(InvestmentTransaction)),
        "execuções de sync": count(select(func.count()).select_from(SyncRun)),
    }


def transaction_date_range(session: Session) -> tuple[date | None, date | None]:
    row = session.execute(select(func.min(Transaction.date), func.max(Transaction.date))).one()
    return row[0], row[1]


def account_label(account: Account, max_name: int = 20) -> str:
    kind = SUBTYPE_LABELS.get(account.subtype or "", account.type)
    name = (account.marketing_name or account.name or "").strip()
    if len(name) > max_name:
        name = name[: max_name - 1].rstrip() + "…"
    return f"{kind} ({name})" if name else kind


def account_balances(session: Session) -> list[AccountBalance]:
    accounts = session.scalars(select(Account).order_by(Account.type, Account.subtype))
    return [
        AccountBalance(
            label=account_label(a),
            type=a.type,
            subtype=a.subtype,
            balance_cents=a.balance_cents,
            credit_limit_cents=a.credit_limit_cents,
            available_credit_limit_cents=a.available_credit_limit_cents,
            currency_code=a.currency_code,
        )
        for a in accounts
    ]


def active_total_cents(session: Session, account_id: str, date_from: date, date_to: date) -> int:
    """Soma normalizada das transações ATIVAS de uma conta num período (inclusive)."""
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_normalized_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.state == STATE_ACTIVE,
                Transaction.date >= date_from,
                Transaction.date <= date_to,
            )
        )
        or 0
    )


def monthly_flow(session: Session, date_from: date, date_to: date) -> list[tuple[str, int, int]]:
    """(conta, entradas, saídas) das transações ativas no período."""
    rows = []
    for account in session.scalars(select(Account).order_by(Account.type, Account.subtype)):
        base = select(func.coalesce(func.sum(Transaction.amount_normalized_cents), 0)).where(
            Transaction.account_id == account.id,
            Transaction.state == STATE_ACTIVE,
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
        inflow = int(session.scalar(base.where(Transaction.amount_normalized_cents > 0)) or 0)
        outflow = int(session.scalar(base.where(Transaction.amount_normalized_cents < 0)) or 0)
        rows.append((account_label(account), inflow, outflow))
    return rows


def latest_snapshot_date(session: Session) -> date | None:
    return session.scalar(select(func.max(InvestmentSnapshot.snapshot_date)))


def portfolio_by_class(session: Session, snapshot_date: date) -> list[PortfolioGroup]:
    rows = session.execute(
        select(
            Investment.type,
            Investment.subtype,
            func.count(),
            func.coalesce(func.sum(InvestmentSnapshot.balance_cents), 0),
        )
        .join(Investment, Investment.id == InvestmentSnapshot.investment_id)
        .where(InvestmentSnapshot.snapshot_date == snapshot_date, InvestmentSnapshot.balance_cents > 0)
        .group_by(Investment.type, Investment.subtype)
        .order_by(Investment.type, Investment.subtype)
    )
    return [PortfolioGroup(type=t, subtype=s, positions=int(n), balance_cents=int(b)) for t, s, n, b in rows]
