"""Visão geral: patrimônio total (só investimentos), mês atual, salário, histórico de 12 meses, categorias,
resumo do aporte e alertas.

Variação dos investimentos no mês: valor no fim − valor no início = (aportes − resgates) + rendimento;
rendimento = o que sobra da variação depois do dinheiro novo (proventos pagos na conta ficam à parte).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from findash.classify.salary import SalaryMonth
from findash.classify.summary import month_summary
from findash.db import queries
from findash.invest.performance import monthly_returns, portfolio_series
from findash.invest.wealth import account_balances, wealth
from findash.sync.service import consent_warning, stale_hours
from findash.web.views.common import iso, last_months, wealth_json


def salary_json(w: SalaryMonth) -> dict:
    return {
        "rule_id": w.rule_id,
        "counterparty": w.counterparty,
        "status": w.status,
        "paycheck": w.paycheck_cents,
        "schedule": w.schedule.label,
        "frequency": w.schedule.frequency,
        "started_on": iso(w.started_on),
        "paydays": len(w.paydays),
        "due_paydays": len(w.due_paydays),
        "expected": w.expected_cents,
        "expected_due": w.expected_due_cents,
        "received": w.received_reference_cents,
        "received_cash": w.received_cash_cents,
        "annual_average": w.monthly_average_cents,
        "in_progress": w.in_progress,
        "divergent": w.divergent,
        "difference": w.difference_cents,
        "missing_paydays": [iso(d) for d in w.missing_paydays],
        "off_schedule": [iso(d) for d in w.off_schedule],
        "shifted": [{"credited": iso(d), "reference": iso(r)} for d, r in w.shifted],
    }


def month_json(session: Session, month: str) -> dict:
    s = month_summary(session, month)
    return {
        "month": month,
        "income": s.income_cents,
        "salary": s.income_salary_cents,
        "investment_income": s.investment_income_cents,
        "expenses": s.expenses_total_cents,
        "expenses_count": s.expenses_count,
        "result": s.result_cents,
        "savings_rate": s.savings_rate,
        "unclassified": {"cents": s.unclassified_cents, "count": s.unclassified_count},
        "fixed": s.fixed_cents,
        "variable": s.variable_cents,
        "extraordinary": {"cents": s.extraordinary_cents, "count": s.extraordinary_count},
        "everyday": s.everyday_cents,
        "result_everyday": s.result_everyday_cents,
        "savings_rate_everyday": s.savings_rate_everyday,
        "paid_with_redemptions": s.paid_with_redemptions_cents,
        "flows": {
            "contributions": s.contributions_cents,
            "redemptions": s.redemptions_cents,
            "net": s.contributions_cents - s.redemptions_cents,
            "shrinking": s.redemptions_cents > s.contributions_cents,
        },
        "essential": s.essential_cents,
        "non_essential": s.non_essential_cents,
        "no_flag": s.no_flag_cents,
        "contributions": s.contributions_cents,
        "redemptions": s.redemptions_cents,
        "reimbursements": s.reimbursements_cents,
        "neutral": {
            "loans_out": s.loans_out_cents,
            "loans_in": s.loans_in_cents,
            "own_transfers": s.own_transfers_in_cents,
        },
        "bill_payments": s.bill_payments_cents,
        "categories": [{"name": k, "cents": v} for k, v in s.expenses_by_category.items() if v > 0],
        "refunds_without_origin": s.refunds_without_origin_cents,
        "salaries": [salary_json(w) for w in s.salaries],
    }


def overview(
    session: Session,
    *,
    today: date,
    now: datetime,
    month: str | None = None,
    plan_summary: dict | None = None,
    data_as_of: str | None = None,
) -> dict:
    current = month or f"{today:%Y-%m}"
    worth = wealth_json(wealth(session, today))
    balances = account_balances(session)
    accounts = (
        None
        if balances is None
        else {"date": iso(balances.day), "bank": balances.bank_cents, "card_bill": balances.card_bill_cents}
    )
    history = []
    for m in last_months(current, 12):
        s = month_summary(session, m)
        history.append(
            {
                "month": m,
                "income": s.income_cents,
                "expenses": s.expenses_total_cents,
                "investment_income": s.investment_income_cents,
            }
        )
    month_data = month_json(session, current)
    return {
        "month": month_data,
        "wealth": worth,
        "accounts": accounts,
        "history": history,
        "plan": plan_summary,
        "investments_month": investments_month(session, current, today),
        "data_as_of": data_as_of,
        "alerts": alerts(session, now=now, month_data=month_data),
    }


def investments_month(session: Session, month: str, today: date) -> dict | None:
    """B2: quanto os investimentos variaram no mês e de onde veio (dinheiro novo × rendimento)."""
    row = next((r for r in monthly_returns(portfolio_series(session), today) if r.month == month), None)
    if row is None:
        return None
    return {
        "start": iso(row.start),
        "end": iso(row.end),
        "start_value": row.start_value,
        "end_value": row.end_value,
        "change": row.end_value - row.start_value,
        "contributions": row.contributions,
        "redemptions": row.redemptions,
        "net_flows": row.contributions - row.redemptions,
        "income": row.income,
        "growth": row.end_value - row.start_value - (row.contributions - row.redemptions),
        "gain": row.gain,
        "partial_since": iso(row.partial_since),
        "in_progress": row.in_progress,
    }


def alerts(session: Session, *, now: datetime, month_data: dict) -> list[dict]:
    out: list[dict] = []
    run = queries.last_sync_run(session)
    if run is not None and run.status == "error":
        out.append(
            {
                "level": "critical",
                "title": "A última sincronização falhou",
                "detail": run.error_message or "Veja a tela Status.",
                "target": "status",
            }
        )
    for item in queries.item_statuses(session):
        warning = consent_warning(item.consent_expires_at, now)
        if warning:
            out.append(
                {
                    "level": "warning",
                    "title": "Consentimento do Open Finance perto de expirar",
                    "detail": warning.removeprefix("AVISO: "),
                    "target": "status",
                }
            )
        hours = stale_hours(item.pluggy_last_updated_at, now)
        if hours is not None:
            out.append(
                {
                    "level": "warning",
                    "title": "Dados da Pluggy desatualizados",
                    "detail": f"A última atualização do banco foi há {hours} horas. Sincronize na tela Status.",
                    "target": "status",
                }
            )
    for salary in month_data["salaries"]:
        if salary["divergent"]:
            out.append(
                {
                    "level": "warning",
                    "title": "Salário diferente do esperado",
                    "detail": f"Recebido {salary['received']} de {salary['expected_due']} esperados.",
                    "cents": salary["difference"],
                    "target": "overview",
                }
            )
    flows = month_data["flows"]
    if flows["shrinking"]:
        out.append(
            {
                "level": "warning",
                "title": "Patrimônio encolhendo",
                "detail": "Neste mês você resgatou mais do que aportou.",
                "cents": -flows["net"],
                "target": "plan",
            }
        )
    pending = month_data["unclassified"]
    if pending["count"]:
        out.append(
            {
                "level": "info",
                "title": f"{pending['count']} gasto(s) para classificar",
                "detail": "Escolha a categoria direto na lista de gastos.",
                "cents": pending["cents"],
                "target": "expenses",
            }
        )
    return out
