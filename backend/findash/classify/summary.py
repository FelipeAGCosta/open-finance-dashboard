"""Resumo mensal a partir da camada derivada.

Convenções do resumo (valores positivos para gastos):
- despesas líquidas = despesas - estornos (o estorno abate a categoria da compra original;
  estorno sem origem identificada aparece numa linha própria e abate o total);
- pagamento de fatura e transferência interna não entram em receita nem em despesa: a compra
  no cartão já é a despesa, então pagar a fatura não conta de novo;
- aporte, resgate e renda de investimento ficam separados; renda de investimento NUNCA é receita
  de trabalho;
- reembolso (alguém devolve a parte de um gasto) abate despesa: a categoria escolhida ou, sem ela,
  o total (linha própria); empréstimo concedido, devolução de empréstimo e transferência própria são
  neutros (não entram em receita nem em despesa);
- resultado do mês = receitas + renda de investimentos - despesas líquidas;
- taxa de poupança = resultado / (receitas + renda de investimentos);
- gasto EXTRAORDINÁRIO (marcado pelo usuário: fora do dia a dia, como uma viagem ou um conserto) continua
  em despesas; "dia a dia" = despesas − extraordinários, e sobra/taxa de poupança também saem sem eles;
- pagos com resgates = parte das despesas que a renda do mês não cobriu e que saiu dos investimentos:
  min(max(0, despesas − receitas − renda de investimentos), max(0, resgates − aportes)).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.classify.installments import commitments_after
from findash.classify.rules import UNCLASSIFIED
from findash.classify.salary import SalaryMonth, salary_months
from findash.db.models import (
    LOAN_IN,
    LOAN_OUT,
    OWN_TRANSFER,
    REIMBURSEMENT,
    RULE_NO,
    STATE_ACTIVE,
    RecurringRule,
    Transaction,
    TransactionClassification,
)


@dataclass
class MonthSummary:
    month: str
    income_cents: int = 0
    income_salary_cents: int = 0
    income_by_rule_status: dict[str, int] = field(default_factory=dict)
    salary_payments: int = 0
    salaries: list[SalaryMonth] = field(default_factory=list)  # salário com agenda: esperado × recebido
    expenses_by_category: dict[str, int] = field(default_factory=dict)  # líquidas (positivas)
    refunds_without_origin_cents: int = 0
    reimbursements_cents: int = 0  # reembolsos recebidos (positivo); já abatidos das despesas
    reimbursements_uncategorized_cents: int = 0  # parte sem categoria (abate só o total)
    loans_out_cents: int = 0  # empréstimos concedidos no mês (positivo; neutro)
    loans_in_cents: int = 0  # devoluções de empréstimo no mês (positivo; neutro)
    own_transfers_in_cents: int = 0  # dinheiro meu vindo de outra conta (neutro)
    expenses_total_cents: int = 0
    expenses_count: int = 0
    fixed_cents: int = 0
    variable_cents: int = 0
    essential_cents: int = 0
    non_essential_cents: int = 0
    no_flag_cents: int = 0
    extraordinary_cents: int = 0  # gastos extraordinários (líquidos de estornos); já incluídos nas despesas
    extraordinary_count: int = 0
    everyday_variable_cents: int = 0  # variáveis do dia a dia (não fixas e não extraordinárias)
    unclassified_cents: int = 0
    unclassified_count: int = 0
    contributions_cents: int = 0  # aportes (positivo)
    redemptions_cents: int = 0
    investment_income_cents: int = 0
    bill_payments_cents: int = 0  # informativo
    internal_transfers_out_cents: int = 0
    internal_transfers_in_cents: int = 0
    commitments: dict[str, int] = field(default_factory=dict)

    @property
    def result_cents(self) -> int:
        return self.income_cents + self.investment_income_cents - self.expenses_total_cents

    @property
    def savings_rate(self) -> float | None:
        base = self.income_cents + self.investment_income_cents
        return self.result_cents / base if base > 0 else None

    @property
    def everyday_cents(self) -> int:
        return self.expenses_total_cents - self.extraordinary_cents

    @property
    def result_everyday_cents(self) -> int:
        return self.income_cents + self.investment_income_cents - self.everyday_cents

    @property
    def savings_rate_everyday(self) -> float | None:
        base = self.income_cents + self.investment_income_cents
        return self.result_everyday_cents / base if base > 0 else None

    @property
    def paid_with_redemptions_cents(self) -> int:
        uncovered = max(0, self.expenses_total_cents - self.income_cents - self.investment_income_cents)
        return min(uncovered, max(0, self.redemptions_cents - self.contributions_cents))

    @property
    def unclassified_share(self) -> float | None:
        return self.unclassified_cents / self.expenses_total_cents if self.expenses_total_cents > 0 else None


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(part) for part in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start, end


def month_summary(session: Session, month: str) -> MonthSummary:
    start, end = month_bounds(month)
    summary = MonthSummary(month=month)
    rules = {r.id: r for r in session.scalars(select(RecurringRule))}
    rows = session.execute(
        select(TransactionClassification, Transaction)
        .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
        .where(Transaction.state == STATE_ACTIVE, Transaction.date >= start, Transaction.date < end)
    ).all()
    by_category: dict[str, int] = defaultdict(int)
    income_status: dict[str, int] = defaultdict(int)
    for cls, tx in rows:
        amount = tx.amount_normalized_cents
        kind = cls.movement_type
        if kind == "receita":
            summary.income_cents += amount
            rule = rules.get(cls.recurring_rule_id) if cls.recurring_rule_id else None
            if rule is not None and rule.kind == "salario" and rule.status != RULE_NO:
                summary.income_salary_cents += amount
                summary.salary_payments += 1
                income_status[rule.status] += amount
        elif kind in ("despesa", "estorno", REIMBURSEMENT):
            spent = -amount  # despesa vira positivo; estorno e reembolso viram negativo (abate)
            if kind == REIMBURSEMENT:
                summary.reimbursements_cents += amount
            if kind == "estorno" and cls.category is None:
                summary.refunds_without_origin_cents += amount
            elif kind == REIMBURSEMENT and cls.category is None:
                summary.reimbursements_uncategorized_cents += amount
            else:
                by_category[cls.category or UNCLASSIFIED] += spent
            summary.expenses_total_cents += spent
            if kind == "despesa":
                summary.expenses_count += 1
            if cls.is_fixed:
                summary.fixed_cents += spent
            else:
                summary.variable_cents += spent
            if cls.extraordinary:
                summary.extraordinary_cents += spent
                summary.extraordinary_count += kind == "despesa"
            elif not cls.is_fixed:
                summary.everyday_variable_cents += spent
            if cls.essential is True:
                summary.essential_cents += spent
            elif cls.essential is False:
                summary.non_essential_cents += spent
            else:
                summary.no_flag_cents += spent
            if cls.category == UNCLASSIFIED:
                summary.unclassified_cents += spent
                summary.unclassified_count += kind == "despesa"
        elif kind == "aporte":
            summary.contributions_cents += -amount
        elif kind == "resgate":
            summary.redemptions_cents += amount
        elif kind == "renda_investimento":
            summary.investment_income_cents += amount
        elif kind == "pagamento_fatura":
            if amount < 0:
                summary.bill_payments_cents += -amount
        elif kind == LOAN_OUT:
            summary.loans_out_cents += -amount
        elif kind == LOAN_IN:
            summary.loans_in_cents += amount
        elif kind == OWN_TRANSFER:
            summary.own_transfers_in_cents += max(amount, 0)
            summary.internal_transfers_out_cents += max(-amount, 0)
        elif kind == "transferencia_interna":
            if amount < 0:
                summary.internal_transfers_out_cents += -amount
            else:
                summary.internal_transfers_in_cents += amount
    summary.expenses_by_category = dict(sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0])))
    summary.income_by_rule_status = dict(income_status)
    summary.commitments = commitments_after(session, month)
    summary.salaries = salary_months(session, month)
    return summary


@dataclass
class UnclassifiedGroup:
    key: str
    label: str | None
    kind: str | None
    count: int
    total_cents: int  # positivo
    sample_ids: list[str]


def unclassified_groups(session: Session, month: str | None = None) -> list[UnclassifiedGroup]:
    query = (
        select(TransactionClassification, Transaction)
        .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
        .where(TransactionClassification.movement_type == "despesa", TransactionClassification.category == UNCLASSIFIED)
        .order_by(Transaction.date.desc(), Transaction.id)
    )
    if month:
        start, end = month_bounds(month)
        query = query.where(Transaction.date >= start, Transaction.date < end)
    groups: dict[str, UnclassifiedGroup] = {}
    for cls, tx in session.execute(query):
        key = cls.counterparty_key or f"?{tx.description}"
        group = groups.setdefault(
            key, UnclassifiedGroup(key, cls.counterparty or tx.description, cls.counterparty_kind, 0, 0, [])
        )
        group.count += 1
        group.total_cents += -tx.amount_normalized_cents
        if len(group.sample_ids) < 3:
            group.sample_ids.append(tx.id)
    return sorted(groups.values(), key=lambda g: (-g.total_cents, g.key))
