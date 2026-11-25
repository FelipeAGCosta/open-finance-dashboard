"""Comandos de linha de comando da classificação (classificar, fixos, resumo, override, a-classificar)."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from findash.classify.engine import CATEGORY_LEVELS, ClassificationStats, classify_all
from findash.classify.recurrence import apply_fixed_flags, set_status
from findash.classify.rules import RulesError, ensure_personal_rules_file, load_rulebook
from findash.classify.salary import SalaryMonth, SalarySchedule
from findash.classify.summary import month_summary, unclassified_groups
from findash.config import Paths, local_date, utcnow
from findash.db.models import (
    MOVEMENT_TYPES,
    RULE_AUTO,
    RULE_NO,
    RULE_YES,
    ClassificationOverride,
    RecurringRule,
    Transaction,
)
from findash.settings import SettingsError, load_app_settings

log = logging.getLogger("findash.classify")

EXIT_OK, EXIT_ERROR = 0, 1

LEVEL_LABELS = {
    "override": "override manual",
    "pessoal": "regras pessoais",
    "base": "regras base",
    "pessoa_fisica": "Pix/TED a pessoa física",
    "mcc": "MCC",
    "pluggy": "categoria da Pluggy",
    "a_classificar": "A classificar",
}
FIXED_ACTIONS = {"sim": RULE_YES, "nao": RULE_NO, "auto": RULE_AUTO}
STATUS_LABELS = {RULE_AUTO: "automático", RULE_YES: "manual: sim", RULE_NO: "manual: não"}
SOURCE_LABELS = {"foto": "pela foto diária", "transacao": "pela venda registrada"}


def run_classification(
    paths: Paths, session_factory: sessionmaker, *, now: datetime | None = None
) -> ClassificationStats:
    """Carrega as regras e recalcula a camada derivada inteira numa transação.

    Levanta RulesError ou SettingsError quando a configuração é inválida.
    """
    ensure_personal_rules_file(paths.personal_rules_path)
    book = load_rulebook(paths.config_dir, paths.personal_rules_path)
    salary = load_app_settings(paths).salary
    with session_factory() as session:
        stats = classify_all(session, book, now=now or utcnow(), salary=salary)
        session.commit()
    log.info("Classificação: %s transações; %s", stats.transactions, dict(stats.movements))
    return stats


def cmd_classificar(paths: Paths, session_factory: sessionmaker) -> int:
    try:
        stats = run_classification(paths, session_factory)
    except (RulesError, SettingsError) as exc:
        print(f"ERRO na configuração: {exc}")
        return EXIT_ERROR
    print("\n".join(classification_lines(stats)))
    return EXIT_OK


def classification_lines(stats: ClassificationStats) -> list[str]:
    out = [f"Classificadas {stats.transactions} transações ativas."]
    out.append("Tipos de movimento: " + ", ".join(f"{k} {v}" for k, v in sorted(stats.movements.items())))
    total = sum(stats.expense_level_sums.values())
    out.append("Despesas por nível de regra (% do valor):")
    for level in CATEGORY_LEVELS:
        cents = stats.expense_level_sums.get(level, 0)
        count = stats.expense_levels.get(level, 0)
        if count:
            out.append(f"  {LEVEL_LABELS[level]:<26}{count:>5} transações {_brl(cents):>15}  {_pct(cents, total)}")
    out.append(
        f"Faturas: {stats.bill_pairs} pares; sem par: {len(stats.bill_unpaired_bank)} na conta, "
        f"{len(stats.bill_unpaired_card)} no cartão"
    )
    if stats.investment_matches:
        out.append("Créditos de investimento: " + ", ".join(f"{k} {v}" for k, v in stats.investment_matches.items()))
    linked = sum(stats.redemptions_linked.values())
    if linked or stats.redemptions_unlinked:
        sources = ", ".join(f"{SOURCE_LABELS.get(k, k)} {v}" for k, v in sorted(stats.redemptions_linked.items()))
        out.append(
            f"Resgates/vendas na conta: {linked} ligados ao ativo de origem ({sources or 'nenhum'}); "
            f"{stats.redemptions_unlinked} de origem não identificada ({_brl(stats.redemptions_unlinked_cents)})"
        )
    out.append(f"Estornos: {stats.refunds_linked} ligados à compra original, {stats.refunds_unlinked} sem origem")
    out.append(
        f"Recorrência: {stats.fixed_detected} gastos fixos e {stats.salary_detected} salário(s) detectados "
        "(veja: findash fixos)"
    )
    return out


# ---------------------------------------------------------------- fixos


def cmd_fixos(session_factory: sessionmaker, action: str | None, rule_id: int | None) -> int:
    with session_factory() as session:
        if action:
            rule = set_status(session, rule_id, FIXED_ACTIONS[action], now=utcnow())
            if rule is None:
                print(f"Regra {rule_id} não existe.")
                return EXIT_ERROR
            apply_fixed_flags(session)
            session.commit()
            print(
                f"Regra {rule.id} ({rule.counterparty}) agora está '{STATUS_LABELS[rule.status]}'. "
                "O resumo já considera a escolha."
            )
            return EXIT_OK
        rules = list(
            session.scalars(
                select(RecurringRule).order_by(
                    RecurringRule.kind, RecurringRule.status, RecurringRule.avg_monthly_cents.desc()
                )
            )
        )
    if not rules:
        print("Nenhum gasto fixo ou salário detectado. Rode: findash classificar")
        return EXIT_OK
    print(
        f"{'ID':>4}  {'tipo':<8}{'estado':<13}{'contraparte':<34}{'categoria':<30}{'média/mês':>13}  meses  intervalo"
    )
    total_fixed = 0
    for r in rules:
        flag = "" if r.detected else "  (não detectado no último recálculo)"
        print(
            f"{r.id:>4}  {r.kind:<8}{STATUS_LABELS[r.status]:<13}"
            f"{(r.counterparty or '')[:33]:<34}{(r.category or '—')[:29]:<30}"
            f"{_brl(r.avg_monthly_cents):>13}  {r.months_count or 0:>5}  {r.median_interval_days or 0:>5} d{flag}"
        )
        schedule = SalarySchedule.from_rule(r) if r.kind == "salario" and r.paycheck_cents else None
        if schedule is not None:
            print(
                f"{'':>6}pagamento de {_brl(r.paycheck_cents)} {schedule.label} (até {schedule.grace_days} dias de "
                f"atraso) | média ao longo do ano {_brl(schedule.monthly_average_cents(r.paycheck_cents))}/mês"
            )
        if r.kind == "fixo" and r.status != RULE_NO:
            total_fixed += r.avg_monthly_cents or 0
    print(f"\nGastos fixos (automáticos + manuais): {_brl(total_fixed)} por mês")
    print("A escolha manual vence a detecção: findash fixos sim|nao|auto ID")
    return EXIT_OK


# ---------------------------------------------------------------- override


def cmd_override(
    paths: Paths,
    session_factory: sessionmaker,
    transaction_id: str,
    *,
    category: str | None,
    movement_type: str | None,
    essential: str | None,
    note: str | None,
    remove: bool,
    fixed: str | None = None,
) -> int:
    try:
        book = load_rulebook(paths.config_dir, paths.personal_rules_path)
    except RulesError as exc:
        print(f"ERRO na configuração: {exc}")
        return EXIT_ERROR
    if category is not None and category not in book.categories:
        print(f"Categoria '{category}' não existe. Opções: {', '.join(book.categories)}")
        return EXIT_ERROR
    if movement_type is not None and movement_type not in MOVEMENT_TYPES:
        print(f"Tipo '{movement_type}' inválido. Opções: {', '.join(MOVEMENT_TYPES)}")
        return EXIT_ERROR
    now = utcnow()
    with session_factory() as session:
        if session.get(Transaction, transaction_id) is None:
            print(f"Transação {transaction_id} não existe.")
            return EXIT_ERROR
        override = session.get(ClassificationOverride, transaction_id)
        if remove:
            if override is not None:
                session.delete(override)
            session.commit()
            print(f"Override de {transaction_id} removido.")
        else:
            if category is None and movement_type is None and essential is None and fixed is None:
                print("Informe --categoria, --tipo, --essencial e/ou --fixo (ou --remover).")
                return EXIT_ERROR
            if override is None:
                override = ClassificationOverride(transaction_id=transaction_id, created_at=now, updated_at=now)
                session.add(override)
            if category is not None:
                override.category = category
            if movement_type is not None:
                override.movement_type = movement_type
            if essential is not None:
                override.essential = essential.lower() in ("s", "sim", "true", "1")
            if fixed is not None:
                override.fixed = fixed.lower() in ("s", "sim", "true", "1")
            if note is not None:
                override.note = note
            override.updated_at = now
            session.commit()
            print(f"Override gravado para {transaction_id}.")
    return cmd_classificar(paths, session_factory)


# ---------------------------------------------------------------- relatórios


def cmd_a_classificar(session_factory: sessionmaker, month: str | None, limit: int) -> int:
    with session_factory() as session:
        groups = unclassified_groups(session, month)
    if not groups:
        print("Nada em 'A classificar'.")
        return EXIT_OK
    total = sum(g.total_cents for g in groups)
    print(
        f"Despesas 'A classificar'{' em ' + month if month else ''}: {sum(g.count for g in groups)} transações, "
        f"{_brl(total)}"
    )
    print(f"{'contraparte':<40}{'tipo':<5}{'qtd':>5}{'soma':>15}  exemplo de id (para override)")
    for g in groups[:limit]:
        print(
            f"{(g.label or g.key)[:39]:<40}{g.kind or '?':<5}{g.count:>5}{_brl(g.total_cents):>15}  {g.sample_ids[0]}"
        )
    print('Para corrigir: crie uma regra em data/regras_pessoais.yaml ou use findash override ID --categoria "..."')
    return EXIT_OK


def cmd_resumo(session_factory: sessionmaker, month: str | None) -> int:
    month = month or f"{local_date(utcnow()):%Y-%m}"
    with session_factory() as session:
        print("\n".join(summary_lines(session, month)))
    return EXIT_OK


def summary_lines(session: Session, month: str) -> list[str]:
    s = month_summary(session, month)
    out = [f"Resumo de {month}", "=" * 40]
    out.append(f"Receitas .............................. {_brl(s.income_cents):>15}")
    if s.income_salary_cents:
        status = ", ".join(f"{STATUS_LABELS.get(k, k)}: {_brl(v)}" for k, v in s.income_by_rule_status.items())
        out.append(f"  das quais salário ({status}), em {s.salary_payments} pagamento(s)")
    for salary in s.salaries:
        out += _salary_lines(salary)
    out.append(f"Renda de investimentos ................ {_brl(s.investment_income_cents):>15}")
    out.append(
        f"Despesas líquidas (despesas - estornos) {_brl(s.expenses_total_cents):>15}   ({s.expenses_count} despesas)"
    )
    out.append(f"Resultado do mês ...................... {_brl(s.result_cents):>15}")
    rate = f"{s.savings_rate:.1%}" if s.savings_rate is not None else "—"
    out.append(f"Taxa de poupança ...................... {rate:>15}")
    out.append("")
    out.append("Despesas por categoria")
    for category, cents in s.expenses_by_category.items():
        out.append(f"  {category:<36}{_brl(cents):>15}  {_pct(cents, s.expenses_total_cents)}")
    if s.refunds_without_origin_cents:
        out.append(f"  {'(estornos sem compra identificada)':<36}{_brl(-s.refunds_without_origin_cents):>15}")
    out.append("")
    out.append("Fixo × variável")
    out.append(f"  fixo {_brl(s.fixed_cents):>15} | variável {_brl(s.variable_cents):>13}")
    out.append("Essencial × não essencial")
    out.append(
        f"  essencial {_brl(s.essential_cents):>15} | não essencial {_brl(s.non_essential_cents):>13}"
        f" | sem flag {_brl(s.no_flag_cents):>13}"
    )
    share = f"{s.unclassified_share:.1%}" if s.unclassified_share is not None else "—"
    out.append(
        f"'A classificar': {_brl(s.unclassified_cents)} ({share} das despesas, {s.unclassified_count} transações)"
    )
    out.append("")
    out.append("Investimentos")
    out.append(
        f"  aportes {_brl(s.contributions_cents):>15} | resgates {_brl(s.redemptions_cents):>13}"
        f" | renda {_brl(s.investment_income_cents):>13}"
    )
    out.append("Fora de receita/despesa (informativo)")
    out.append(
        f"  pagamentos de fatura {_brl(s.bill_payments_cents):>13} | transferências internas: saída "
        f"{_brl(s.internal_transfers_out_cents)}, entrada {_brl(s.internal_transfers_in_cents)}"
    )
    out.append("")
    if s.commitments:
        out.append(f"Parcelas comprometidas após {month}: {_brl(sum(s.commitments.values()))}")
        for installment_month, cents in s.commitments.items():
            out.append(f"  {installment_month}: {_brl(cents)}")
    else:
        out.append(f"Parcelas comprometidas após {month}: nenhuma")
    return out


def _salary_lines(w: SalaryMonth) -> list[str]:
    since = f", desde {w.started_on:%d/%m/%Y}" if w.started_on else ""
    out = [
        f"  salário {_brl(w.paycheck_cents)} {w.schedule.label} ({w.counterparty}, "
        f"{STATUS_LABELS.get(w.status, w.status)}{since}):",
        f"    esperado no mês {_brl(w.expected_cents)} ({len(w.paydays)} pagamento(s)) | recebido "
        f"{_brl(w.received_reference_cents)} | média ao longo do ano {_brl(w.monthly_average_cents)}/mês",
    ]
    if w.in_progress:
        out.append(
            f"    mês em andamento: esperado até agora {_brl(w.expected_due_cents)} "
            f"({len(w.due_paydays)} de {len(w.paydays)} pagamentos)"
        )
    if w.received_cash_cents != w.received_reference_cents or w.shifted:
        moves = ", ".join(f"{day:%d/%m} (referente a {reference:%d/%m})" for day, reference in w.shifted)
        out.append(
            f"    pelo dia do crédito na conta: {_brl(w.received_cash_cents)}"
            + (f"; créditos em mês diferente do dia de referência: {moves}" if moves else "")
        )
    if w.divergent:
        detail = []
        if w.missing_paydays:
            detail.append("dias sem pagamento: " + ", ".join(f"{d:%d/%m}" for d in w.missing_paydays))
        if w.off_schedule:
            detail.append("créditos fora da agenda: " + ", ".join(f"{d:%d/%m}" for d in w.off_schedule))
        if w.unexpected_amounts:
            detail.append(
                "valores diferentes do habitual: " + ", ".join(f"{d:%d/%m} {_brl(c)}" for d, c in w.unexpected_amounts)
            )
        out.append(
            f"    ⚠ recebido difere do esperado em {_brl(w.difference_cents)}"
            + (f" ({'; '.join(detail)})" if detail else "")
        )
    return out


def _brl(cents: int | None) -> str:
    if cents is None:
        return "—"
    text = f"{cents / 100:,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(part: int, total: int) -> str:
    return f"{part / total:6.1%}" if total else "     —"
