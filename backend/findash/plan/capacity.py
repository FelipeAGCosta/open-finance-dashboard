"""Capacidade de aporte do mês e quanto já foi aportado em cada lugar (Reserva ou Patrimônio).

Mês em andamento (sobra projetada):
    sobra projetada = receitas já recebidas (inclui rendimentos pagos na conta)
                    + salário ainda esperado (segundas que ainda não chegaram)
                    − despesas já feitas (líquidas de estornos e reembolsos)
                    − fixos ATIVOS que ainda não caíram no mês
                    − estimativa de variáveis do DIA A DIA dos dias restantes
                      (média diária das variáveis do dia a dia dos 3 últimos meses fechados × dias restantes;
                      gastos extraordinários ficam fora da média: não se repetem todo mês)
    capacidade      = sobra projetada − aportes líquidos já feitos no mês (aportes − resgates)
Checagem de caixa: saldo da conta agora − fatura em aberto − colchão mínimo = disponível hoje. Se a
capacidade passar do disponível e ainda houver salário por cair, parte dela depende de salários futuros.
Mês fechado: sobra real (receitas + renda − despesas) e quanto dela foi aportado.
Empréstimos, devoluções e transferências próprias são neutros e não entram em nenhuma parcela.

Aportado por lugar: cada aporte/resgate da conta vai para o lugar do ativo ligado a ele (compra casada
ou origem do resgate); sem ligação, "Compra de renda variável" conta no Patrimônio e as aplicações de
renda fixa no destino automático da renda fixa (Reserva enquanto abaixo do valor; depois, o Patrimônio).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.classify.fixed import fixed_month
from findash.classify.summary import month_bounds, month_summary
from findash.db.models import (
    STATE_ACTIVE,
    Account,
    Investment,
    InvestmentTransaction,
    RedemptionOrigin,
    Transaction,
    TransactionClassification,
    TransactionLink,
)
from findash.invest.wealth import account_balances
from findash.plan.base import shift_month
from findash.plan.places import PATRIMONY

VARIABLE_MONTHS = 3
RV_HINTS = ("RENDA VARIAVEL",)


@dataclass
class MonthCapacity:
    month: str
    closed: bool
    income_cents: int = 0
    salary_remaining_cents: int = 0
    salary_remaining_paydays: list[date] = field(default_factory=list)
    expenses_cents: int = 0
    fixed_pending_cents: int = 0
    variable_months: list[tuple[str, int, int]] = field(default_factory=list)  # (mês, variáveis, dias)
    days_remaining: int = 0
    contributions_cents: int = 0  # aportes (positivo)
    redemptions_cents: int = 0  # resgates (positivo)
    bank_cents: int | None = None
    card_bill_cents: int | None = None
    balance_date: date | None = None
    cushion_cents: int = 0

    @property
    def variable_daily_cents(self) -> int | None:
        days = sum(d for _, _, d in self.variable_months)
        return round(sum(v for _, v, _ in self.variable_months) / days) if days else None

    @property
    def variable_estimate_cents(self) -> int:
        daily = self.variable_daily_cents
        return 0 if self.closed or daily is None else daily * self.days_remaining

    @property
    def contributions_net_cents(self) -> int:
        return self.contributions_cents - self.redemptions_cents

    @property
    def projected_surplus_cents(self) -> int:
        return (
            self.income_cents
            + self.salary_remaining_cents
            - self.expenses_cents
            - self.fixed_pending_cents
            - self.variable_estimate_cents
        )

    @property
    def capacity_cents(self) -> int:
        return self.projected_surplus_cents - self.contributions_net_cents

    @property
    def cash_available_cents(self) -> int | None:
        if self.bank_cents is None:
            return None
        return self.bank_cents - (self.card_bill_cents or 0) - self.cushion_cents

    @property
    def depends_on_future_salary(self) -> bool:
        cash = self.cash_available_cents
        return (
            not self.closed
            and self.salary_remaining_cents > 0
            and cash is not None
            and self.capacity_cents > max(cash, 0)
        )


def month_capacity(session: Session, month: str, *, today: date, cushion_cents: int) -> MonthCapacity:
    current = f"{today:%Y-%m}"
    start, end = month_bounds(month)
    summary = month_summary(session, month)
    cap = MonthCapacity(month, closed=month < current, cushion_cents=cushion_cents)
    cap.income_cents = summary.income_cents + summary.investment_income_cents
    cap.expenses_cents = summary.expenses_total_cents
    cap.contributions_cents = summary.contributions_cents
    cap.redemptions_cents = summary.redemptions_cents
    if not cap.closed:
        cap.fixed_pending_cents = fixed_month(session, month, today=today).pending_cents
        last_day = end - timedelta(days=1)
        cap.days_remaining = max(0, (last_day - max(today, start - timedelta(days=1))).days)
        for back in range(VARIABLE_MONTHS, 0, -1):
            m = shift_month(month, -back)
            days = calendar.monthrange(*(int(p) for p in m.split("-")))[1]
            cap.variable_months.append((m, month_summary(session, m).everyday_variable_cents, days))
        for salary in summary.salaries:
            future = [
                d
                for d in salary.paydays
                if d not in salary.due_paydays and d + timedelta(days=salary.schedule.grace_days) >= today
            ]
            cap.salary_remaining_paydays += future
            cap.salary_remaining_cents += salary.paycheck_cents * len(future)
        balances = account_balances(session)
        if balances:
            cap.bank_cents, cap.card_bill_cents, cap.balance_date = (
                balances.bank_cents,
                balances.card_bill_cents,
                balances.day,
            )
        else:
            accounts = session.scalars(select(Account)).all()
            if accounts:
                cap.bank_cents = sum(a.balance_cents or 0 for a in accounts if a.type == "BANK")
                cap.card_bill_cents = sum(a.balance_cents or 0 for a in accounts if a.type == "CREDIT")
    return cap


# ------------------------------------------------------------------ aportado por lugar e por ativo


UNLINKED_FIXED, UNLINKED_VARIABLE = "rf", "rv"


def contributions_by_place(
    session: Session, month: str, place_of: Callable[[Investment], str], fixed_income_place: str
) -> dict[str, int]:
    """Aportes − resgates da conta no mês, por lugar (ver docstring do módulo)."""
    out: dict[str, int] = defaultdict(int)
    for (place, _), cents in contributions_by_asset(
        session, month, place_of, fixed_income_place, lambda inv: ""
    ).items():
        out[place] += cents
    return dict(out)


def contributions_by_asset(
    session: Session,
    month: str,
    place_of: Callable[[Investment], str],
    fixed_income_place: str,
    key_of: Callable[[Investment], str],
) -> dict[tuple[str, str], int]:
    """O mesmo, por (lugar, ativo): `key_of` dá a chave do ativo ligado (ex.: o código de negociação).

    Sem ativo ligado, a chave é "rv" (compra de renda variável) ou "rf" (aplicação de renda fixa).
    """
    start, end = month_bounds(month)
    rows = session.execute(
        select(Transaction, TransactionClassification.movement_type)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Account.type == "BANK",
            Transaction.date >= start,
            Transaction.date < end,
            TransactionClassification.movement_type.in_(("aporte", "resgate")),
        )
    ).all()
    ids = [tx.id for tx, _ in rows]
    bought = dict(
        session.execute(
            select(TransactionLink.transaction_id, InvestmentTransaction.investment_id)
            .join(InvestmentTransaction, InvestmentTransaction.id == TransactionLink.investment_transaction_id)
            .where(TransactionLink.kind == "investimento", TransactionLink.transaction_id.in_(ids or ["-"]))
        ).all()
    )
    origins: dict[str, list[tuple[str | None, int]]] = defaultdict(list)
    for tx_id, investment_id, gross in session.execute(
        select(RedemptionOrigin.transaction_id, RedemptionOrigin.investment_id, RedemptionOrigin.gross_cents).where(
            RedemptionOrigin.transaction_id.in_(ids or ["-"])
        )
    ):
        origins[tx_id].append((investment_id, gross))
    investments = {i.id: i for i in session.scalars(select(Investment))}
    out: dict[tuple[str, str], int] = defaultdict(int)
    for tx, kind in rows:
        cents = -tx.amount_normalized_cents  # aporte: + ; resgate: −
        linked = bought.get(tx.id) if kind == "aporte" else None
        if linked and linked in investments:
            out[place_of(investments[linked]), key_of(investments[linked])] += cents
            continue
        parts = [(investments.get(i), g) for i, g in origins.get(tx.id, []) if i]
        if parts and all(inv is not None for inv, _ in parts):
            total = sum(g for _, g in parts) or 1
            for inv, gross in parts:
                out[place_of(inv), key_of(inv)] += round(cents * gross / total)
            continue
        text = (tx.description or "").upper()
        if any(h in _plain(text) for h in RV_HINTS):
            out[PATRIMONY, UNLINKED_VARIABLE] += cents
        else:
            out[fixed_income_place, UNLINKED_FIXED] += cents
    return dict(out)


def _plain(text: str) -> str:
    from findash.classify.text import normalize_text

    return normalize_text(text)
