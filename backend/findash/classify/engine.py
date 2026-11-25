"""Motor de classificação: recalcula do zero, sempre com o mesmo resultado para os mesmos dados.

Para cada transação ATIVA:
1. tipo de movimento (exatamente um), por esta ordem:
   override manual > regra pessoal/base com `tipo` > pagamento de fatura > aporte > resgate >
   crédito de investimento (cruzado com investment_transactions) > crédito na conta via cartão >
   transferência para a própria pessoa > crédito no cartão (estorno) > reembolso na conta (estorno) >
   saída (despesa) > entrada (receita);
2. categoria (só despesas e estornos), por esta ordem:
   override > regras pessoais > regras base > Pix/TED a pessoa física > MCC > categoria da Pluggy >
   "A classificar". Estorno herda a categoria da compra original quando ela é identificada.
3. vínculos: pagamento de fatura (conta <-> cartão), estorno -> compra, crédito <-> investimento;
   créditos de resgate/venda -> ativo(s) de origem (redemption_origins; ver findash/invest/origins.py).
4. recorrência (gastos fixos e salário): ver findash/classify/recurrence.py.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from findash.classify.recurrence import apply_recurrence
from findash.classify.rules import TRANSFER_TO_PEOPLE, UNCLASSIFIED, RuleBook
from findash.classify.salary import SalarySchedule
from findash.classify.text import (
    counterparty_document,
    counterparty_key,
    counterparty_kind,
    normalize_counterparty,
    normalize_text,
    raw_counterparty,
)
from findash.db.models import (
    REIMBURSEMENT,
    STATE_ACTIVE,
    Account,
    ClassificationOverride,
    InvestmentTransaction,
    RedemptionOrigin,
    Transaction,
    TransactionClassification,
    TransactionLink,
)
from findash.institutions import InstitutionProfile, get_profile
from findash.invest.origins import Credit, match_credits, sale_events, snapshot_drop_events

# Os padrões de descrição (pagamento de fatura, aporte, resgate...) vêm do perfil da instituição de cada
# conta: ver findash/institutions.

# Fatura paga na conta e o crédito no cartão podem cair em dias diferentes (compensação, fim de semana).
BILL_PAIR_MAX_DAYS = 5
INVESTMENT_MATCH_MAX_DAYS = 5
REFUND_LOOKBACK_DAYS = 120
EXPENSE_LIKE = ("despesa", "estorno", REIMBURSEMENT)  # movimentos que entram nas despesas (e podem ser extraordinários)
UNMATCHED_INCOME_MAX_CENTS = 10_000  # crédito de investimento sem par: até R$ 100 = rendimento; acima = venda

LEVEL_OVERRIDE = "override"
LEVEL_PERSONAL = "pessoal"
LEVEL_BASE = "base"
LEVEL_PERSON = "pessoa_fisica"
LEVEL_MCC = "mcc"
LEVEL_PLUGGY = "pluggy"
LEVEL_UNCLASSIFIED = "a_classificar"
LEVEL_REFUND_ORIGIN = "estorno_da_compra"
LEVEL_REFUND_NO_ORIGIN = "estorno_sem_origem"
CATEGORY_LEVELS = (
    LEVEL_OVERRIDE,
    LEVEL_PERSONAL,
    LEVEL_BASE,
    LEVEL_PERSON,
    LEVEL_MCC,
    LEVEL_PLUGGY,
    LEVEL_UNCLASSIFIED,
)


@dataclass
class _View:
    tx: Transaction
    account_type: str
    profile: InstitutionProfile
    direction: str  # "in" | "out"
    amount: int  # normalizado (centavos)
    desc: str  # descrição normalizada
    text: str  # descrição + contraparte (texto principal das regras)
    merchant_text: str  # estabelecimento informado pela Pluggy (só se o texto principal não casar)
    counterparty: str | None
    key: str | None
    kind: str | None
    doc_digits: str | None


@dataclass
class _Result:
    movement_type: str
    movement_rule: str
    category: str | None = None
    essential: bool | None = None
    rule_level: str | None = None
    rule_detail: str | None = None
    extraordinary: bool = False


@dataclass
class ClassificationStats:
    transactions: int = 0
    movements: Counter = field(default_factory=Counter)  # tipo -> qtd
    movement_sums: Counter = field(default_factory=Counter)  # tipo -> centavos
    expense_levels: Counter = field(default_factory=Counter)  # nível -> qtd de despesas
    expense_level_sums: Counter = field(default_factory=Counter)  # nível -> centavos (positivos)
    bill_pairs: int = 0
    bill_unpaired_bank: list[str] = field(default_factory=list)
    bill_unpaired_card: list[str] = field(default_factory=list)
    investment_matches: Counter = field(default_factory=Counter)  # como cada crédito de investimento foi decidido
    redemptions_linked: Counter = field(default_factory=Counter)  # fonte (foto|transacao) -> créditos ligados à origem
    redemptions_unlinked: int = 0
    redemptions_unlinked_cents: int = 0
    refunds_linked: int = 0
    refunds_unlinked: int = 0
    fixed_detected: int = 0
    salary_detected: int = 0


def classify_all(
    session: Session, book: RuleBook, *, now: datetime, salary: SalarySchedule | None = None
) -> ClassificationStats:
    """Apaga a camada derivada e recalcula tudo dentro da transação da sessão (o chamador faz commit)."""
    session.execute(delete(TransactionLink))
    session.execute(delete(RedemptionOrigin))
    session.execute(delete(TransactionClassification))
    session.flush()

    stats = ClassificationStats()
    accounts = {a.id: a for a in session.scalars(select(Account))}
    owner_digits, owner_name = _owner_identity(accounts.values())
    overrides = {o.transaction_id: o for o in session.scalars(select(ClassificationOverride))}
    transactions = list(
        session.scalars(
            select(Transaction).where(Transaction.state == STATE_ACTIVE).order_by(Transaction.date, Transaction.id)
        )
    )
    views = [_view(tx, accounts[tx.account_id]) for tx in transactions]
    results: dict[str, _Result] = {}
    links: list[TransactionLink] = []

    # 1) tipo de movimento
    investment_received: list[_View] = []
    for view in views:
        result = _movement(view, overrides.get(view.tx.id), book, owner_digits, owner_name)
        if result is None:
            investment_received.append(view)
        else:
            results[view.tx.id] = result
    _cross_match_investments(session, views, investment_received, results, links, stats, now)
    origins = _link_redemption_origins(session, views, investment_received, results, stats, now)

    # 2) pagamento de fatura: pares conta <-> cartão
    _pair_bill_payments(views, results, links, stats, now)

    # 3) categorias das despesas
    for view in views:
        result = results[view.tx.id]
        if result.movement_type == "despesa":
            _categorize(view, result, overrides.get(view.tx.id), book, allow_person_default=True)
            result.extraordinary = _extraordinary_rule(view, book)

    # 4) estornos: herdam a categoria da compra original quando dá para identificar
    expenses_by_key: dict[str, list[_View]] = defaultdict(list)
    for view in views:
        if results[view.tx.id].movement_type == "despesa" and view.key:
            expenses_by_key[view.key].append(view)
    for view in views:
        result = results[view.tx.id]
        if result.movement_type == "estorno":
            _categorize_refund(
                view, result, overrides.get(view.tx.id), book, expenses_by_key, results, links, stats, now
            )

    # 4b) reembolso (escolhido pelo usuário): abate a categoria do gasto reembolsado, se ele disser qual
    for view in views:
        result = results[view.tx.id]
        if result.movement_type == REIMBURSEMENT:
            _categorize_reimbursement(view, result, overrides.get(view.tx.id), book)
            result.extraordinary = _extraordinary_rule(view, book)

    # 4c) extraordinário: a escolha "só esta" vence a regra e o que o estorno herdou da compra
    for view in views:
        result = results[view.tx.id]
        override = overrides.get(view.tx.id)
        if result.movement_type not in EXPENSE_LIKE:
            result.extraordinary = False
        elif override is not None and override.extraordinary is not None:
            result.extraordinary = override.extraordinary

    # 5) grava
    for view in views:
        result = results[view.tx.id]
        session.add(
            TransactionClassification(
                transaction_id=view.tx.id,
                movement_type=result.movement_type,
                movement_rule=result.movement_rule,
                category=result.category,
                essential=result.essential,
                rule_level=result.rule_level,
                rule_detail=result.rule_detail,
                counterparty=view.counterparty,
                counterparty_key=view.key,
                counterparty_kind=view.kind,
                extraordinary=result.extraordinary,
                computed_at=now,
            )
        )
        stats.movements[result.movement_type] += 1
        stats.movement_sums[result.movement_type] += view.amount
        if result.movement_type == "despesa":
            stats.expense_levels[result.rule_level] += 1
            stats.expense_level_sums[result.rule_level] += -view.amount
    session.add_all(links)
    session.flush()
    session.add_all(origins)
    session.flush()
    stats.transactions = len(views)

    # 6) recorrência (gastos fixos e salário), preservando o status escolhido pelo usuário
    fixed, salaries = apply_recurrence(session, now=now, salary=salary or SalarySchedule())
    stats.fixed_detected, stats.salary_detected = fixed, salaries
    session.flush()
    return stats


# ====================================================================== tipo de movimento


def _movement(
    view: _View,
    override: ClassificationOverride | None,
    book: RuleBook,
    owner_digits: str | None,
    owner_name: str | None,
) -> _Result | None:
    """Tipo de movimento; None = crédito de investimento que depende do cruzamento com investment_transactions."""
    if override is not None and override.movement_type:
        return _Result(override.movement_type, "override manual")
    for rules in (book.personal, book.base):
        found = _match([r for r in rules if r.movement_type], view)
        if found:
            rule, pattern = found
            return _Result(rule.movement_type, rule.describe(pattern))

    bank, card = view.account_type == "BANK", view.account_type == "CREDIT"
    out, inn = view.direction == "out", view.direction == "in"
    patterns = view.profile.patterns
    if bank and out and _starts(view.desc, patterns.bill_payment_bank):
        return _Result("pagamento_fatura", "conta: descrição de pagamento de fatura")
    if card and inn and _starts(view.desc, patterns.bill_payment_card):
        return _Result("pagamento_fatura", "cartão: pagamento recebido")
    if bank and out and _starts(view.desc, patterns.investment_out):
        return _Result("aporte", f"conta: '{_first(view.desc, patterns.investment_out)}'")
    if bank and inn and _starts(view.desc, patterns.investment_in):
        return _Result("resgate", f"conta: '{_first(view.desc, patterns.investment_in)}'")
    if bank and inn and _starts(view.desc, patterns.investment_received):
        return None
    if bank and inn and _starts(view.desc, patterns.account_topup_from_card):
        return _Result("transferencia_interna", "conta: valor adicionado com o próprio cartão")
    if bank and _is_self(view, owner_digits, owner_name):
        return _Result("transferencia_interna", "contraparte é o próprio titular (CPF/nome)")
    if card and inn:
        return _Result("estorno", "cartão: crédito que não é pagamento de fatura")
    if bank and inn and _starts(view.desc, patterns.refund_in_account):
        return _Result("estorno", f"conta: '{_first(view.desc, patterns.refund_in_account)}'")
    if out:
        return _Result("despesa", "saída")
    return _Result("receita", "entrada")


def _cross_match_investments(
    session: Session,
    views: list[_View],
    received: list[_View],
    results: dict[str, _Result],
    links: list[TransactionLink],
    stats: ClassificationStats,
    now: datetime,
) -> None:
    """'Valor recebido de Investimentos' que casa com um rendimento (INTEREST) de mesmo valor = renda.

    Os demais créditos ficam sem resultado aqui e são decididos em _link_redemption_origins. Também liga
    aportes da conta à compra (BUY) de mesmo valor, quando houver.
    """
    inv_txs = list(
        session.scalars(select(InvestmentTransaction).order_by(InvestmentTransaction.date, InvestmentTransaction.id))
    )
    by_amount: dict[int, list[InvestmentTransaction]] = defaultdict(list)
    for inv in inv_txs:
        for value in {inv.amount_cents, inv.net_amount_cents} - {None}:
            by_amount[abs(value)].append(inv)
    used: set[str] = set()

    def find(view: _View, types: tuple[str, ...]) -> InvestmentTransaction | None:
        candidates = [
            inv
            for inv in by_amount.get(abs(view.amount), [])
            if inv.id not in used
            and inv.type in types
            and abs((inv.date - view.tx.date).days) <= INVESTMENT_MATCH_MAX_DAYS
        ]
        return min(candidates, key=lambda inv: (abs((inv.date - view.tx.date).days), inv.id)) if candidates else None

    def link(view: _View, inv: InvestmentTransaction, detail: str) -> None:
        used.add(inv.id)
        links.append(
            TransactionLink(
                kind="investimento",
                transaction_id=view.tx.id,
                investment_transaction_id=inv.id,
                detail=detail,
                created_at=now,
            )
        )

    for view in received:
        interest = find(view, ("INTEREST",))
        if interest is not None:
            link(view, interest, "rendimento (INTEREST)")
            results[view.tx.id] = _Result("renda_investimento", "crédito de investimento = rendimento (INTEREST)")
            stats.investment_matches["rendimento: casou com INTEREST"] += 1

    for view in views:
        result = results.get(view.tx.id)
        if result is not None and view.account_type == "BANK" and result.movement_type == "aporte":
            inv = find(view, ("BUY",))
            if inv is not None:
                link(view, inv, "aporte (BUY)")


def _link_redemption_origins(
    session: Session,
    views: list[_View],
    received: list[_View],
    results: dict[str, _Result],
    stats: ClassificationStats,
    now: datetime,
) -> list[RedemptionOrigin]:
    """Liga créditos de resgate/venda ao(s) ativo(s) de origem e decide os créditos de investimento restantes."""
    pending_received = [v for v in received if v.tx.id not in results]
    credit_views = pending_received + [
        v
        for v in views
        if v.account_type == "BANK"
        and v.direction == "in"
        and v.tx.id in results
        and results[v.tx.id].movement_type == "resgate"
        and results[v.tx.id].movement_rule.startswith("conta:")
    ]
    credits = [Credit(v.tx.id, v.tx.date, abs(v.amount)) for v in credit_views]
    matches = match_credits(credits, snapshot_drop_events(session), sale_events(session))

    origins: list[RedemptionOrigin] = []
    for view in credit_views:
        events = matches.get(view.tx.id)
        if events:
            source = events[0].source
            stats.redemptions_linked[source] += 1
            for event in events:
                origins.append(
                    RedemptionOrigin(
                        transaction_id=view.tx.id,
                        source=event.source,
                        investment_id=event.investment_id,
                        investment_transaction_id=event.investment_transaction_id,
                        event_date=event.event_date,
                        gross_cents=event.gross_cents,
                        net_cents=event.net_cents,
                        created_at=now,
                    )
                )
            if view.tx.id not in results:
                label = "queda na foto diária" if source == "foto" else "venda (SELL)"
                results[view.tx.id] = _Result("resgate", f"crédito de investimento ligado à origem: {label}")
                stats.investment_matches[f"resgate: ligado à origem ({label})"] += 1
            continue
        if view.tx.id in results:  # 'Resgate ...' da conta: continua resgate, só que sem origem
            stats.redemptions_unlinked += 1
            stats.redemptions_unlinked_cents += abs(view.amount)
        elif abs(view.amount) <= UNMATCHED_INCOME_MAX_CENTS:
            results[view.tx.id] = _Result(
                "renda_investimento", "crédito de investimento sem par, até R$ 100 (heurística)"
            )
            stats.investment_matches["rendimento: sem par, até R$ 100"] += 1
        else:
            results[view.tx.id] = _Result("resgate", "resgate de origem não identificada (acima de R$ 100)")
            stats.investment_matches["resgate: origem não identificada"] += 1
            stats.redemptions_unlinked += 1
            stats.redemptions_unlinked_cents += abs(view.amount)
    return origins


def _pair_bill_payments(
    views: list[_View],
    results: dict[str, _Result],
    links: list[TransactionLink],
    stats: ClassificationStats,
    now: datetime,
) -> None:
    bank = [v for v in views if v.account_type == "BANK" and results[v.tx.id].movement_type == "pagamento_fatura"]
    card = [v for v in views if v.account_type == "CREDIT" and results[v.tx.id].movement_type == "pagamento_fatura"]
    used: set[str] = set()
    for payment in bank:
        candidates = [
            c
            for c in card
            if c.tx.id not in used
            and c.amount == -payment.amount
            and abs((c.tx.date - payment.tx.date).days) <= BILL_PAIR_MAX_DAYS
        ]
        if not candidates:
            stats.bill_unpaired_bank.append(payment.tx.id)
            continue
        match = min(candidates, key=lambda c: (abs((c.tx.date - payment.tx.date).days), c.tx.id))
        used.add(match.tx.id)
        links.append(
            TransactionLink(
                kind="pagamento_fatura",
                transaction_id=payment.tx.id,
                other_transaction_id=match.tx.id,
                created_at=now,
                detail=f"{(match.tx.date - payment.tx.date).days:+d} dia(s)",
            )
        )
        stats.bill_pairs += 1
    stats.bill_unpaired_card = [c.tx.id for c in card if c.tx.id not in used]


# ====================================================================== categoria


def _categorize(
    view: _View, result: _Result, override: ClassificationOverride | None, book: RuleBook, *, allow_person_default: bool
) -> None:
    category, essential, level, detail = _category_for(view, override, book, allow_person_default)
    result.category, result.rule_level, result.rule_detail = category, level, detail
    if override is not None and override.essential is not None:
        result.essential = override.essential
    elif essential is not None:
        result.essential = essential
    else:
        result.essential = book.default_essential(category)


def _category_for(
    view: _View, override: ClassificationOverride | None, book: RuleBook, allow_person_default: bool
) -> tuple[str, bool | None, str, str]:
    if override is not None and override.category:
        return (
            override.category,
            None,
            LEVEL_OVERRIDE,
            f"override manual{': ' + override.note if override.note else ''}",
        )
    for level, rules in ((LEVEL_PERSONAL, book.personal), (LEVEL_BASE, book.base)):
        found = _match([r for r in rules if r.category], view)
        if found:
            rule, pattern = found
            return rule.category, rule.essential, level, rule.describe(pattern)
    if allow_person_default and view.account_type == "BANK" and view.kind == "PF":
        return TRANSFER_TO_PEOPLE, False, LEVEL_PERSON, "saída para pessoa física (CPF ou nome de pessoa)"
    mcc = view.tx.mcc
    if mcc is not None and mcc in book.mcc:
        return book.mcc[mcc], None, LEVEL_MCC, f"MCC {mcc}"
    pluggy = (view.tx.category_pluggy or "").strip().casefold()
    if pluggy and pluggy in book.pluggy:
        return book.pluggy[pluggy], None, LEVEL_PLUGGY, f"categoria da Pluggy '{view.tx.category_pluggy}'"
    return UNCLASSIFIED, None, LEVEL_UNCLASSIFIED, "nenhuma regra casou"


def _categorize_refund(
    view: _View,
    result: _Result,
    override: ClassificationOverride | None,
    book: RuleBook,
    expenses_by_key: dict[str, list[_View]],
    results: dict[str, _Result],
    links: list[TransactionLink],
    stats: ClassificationStats,
    now: datetime,
) -> None:
    if override is not None and override.category:
        _categorize(view, result, override, book, allow_person_default=False)
        return
    origin = None
    if view.key:
        candidates = [
            e
            for e in expenses_by_key.get(view.key, [])
            if e.tx.date <= view.tx.date
            and (view.tx.date - e.tx.date).days <= REFUND_LOOKBACK_DAYS
            and -e.amount >= view.amount
        ]
        if candidates:
            origin = max(candidates, key=lambda e: (e.tx.date, e.tx.id))
    if origin is not None:
        original = results[origin.tx.id]
        result.category, result.essential = original.category, original.essential
        result.extraordinary = original.extraordinary
        result.rule_level, result.rule_detail = LEVEL_REFUND_ORIGIN, f"estorno da compra {origin.tx.id}"
        links.append(
            TransactionLink(
                kind="estorno",
                transaction_id=view.tx.id,
                other_transaction_id=origin.tx.id,
                detail="mesma contraparte, valor <= compra, até 120 dias antes",
                created_at=now,
            )
        )
        stats.refunds_linked += 1
        return
    category, essential, level, detail = _category_for(view, None, book, allow_person_default=False)
    result.extraordinary = _extraordinary_rule(view, book)
    stats.refunds_unlinked += 1
    if level == LEVEL_UNCLASSIFIED:
        result.category, result.rule_level, result.rule_detail = (
            None,
            LEVEL_REFUND_NO_ORIGIN,
            "compra original não identificada",
        )
        return
    result.category, result.rule_level, result.rule_detail = category, level, detail
    result.essential = essential if essential is not None else book.default_essential(category)


def _categorize_reimbursement(
    view: _View, result: _Result, override: ClassificationOverride | None, book: RuleBook
) -> None:
    """Categoria do gasto reembolsado: override > regra pessoal/base com categoria > nenhuma (abate o total)."""
    if override is not None and override.category:
        result.category, result.rule_level = override.category, LEVEL_OVERRIDE
        result.rule_detail = "reembolso: categoria escolhida"
        result.essential = (
            override.essential if override.essential is not None else book.default_essential(override.category)
        )
        return
    for level, rules in ((LEVEL_PERSONAL, book.personal), (LEVEL_BASE, book.base)):
        found = _match([r for r in rules if r.category], view)
        if found:
            rule, pattern = found
            result.category, result.rule_level, result.rule_detail = rule.category, level, rule.describe(pattern)
            result.essential = rule.essential if rule.essential is not None else book.default_essential(rule.category)
            return
    result.category, result.essential = None, False
    result.rule_level, result.rule_detail = None, "reembolso sem categoria: abate o total de despesas"


def _extraordinary_rule(view: _View, book: RuleBook) -> bool:
    """'extraordinario' da primeira regra pessoal/base que casa e define o campo (padrão: dia a dia)."""
    for rules in (book.personal, book.base):
        found = _match([r for r in rules if r.extraordinary is not None], view)
        if found:
            return bool(found[0].extraordinary)
    return False


# ====================================================================== utilidades


def _view(tx: Transaction, account: Account) -> _View:
    account_type, profile = account.type, get_profile(account.institution)
    payment_data = tx.payment_data_json if isinstance(tx.payment_data_json, dict) else None
    embedded = profile.counterparty_from_description((tx.description or "").strip())
    raw_name = raw_counterparty(tx.description, payment_data, tx.merchant_name, tx.type, account_type, embedded)
    name = normalize_counterparty(raw_name) or None
    doc_type, doc_digits = counterparty_document(payment_data, tx.type)
    desc = normalize_text(tx.description)
    text = " | ".join(filter(None, (desc, name)))
    return _View(
        tx=tx,
        account_type=account_type,
        profile=profile,
        direction="in" if tx.amount_normalized_cents > 0 else "out",
        amount=tx.amount_normalized_cents,
        desc=desc,
        text=text,
        merchant_text=normalize_text(tx.merchant_name),
        counterparty=name,
        key=counterparty_key(name) or None,
        kind=counterparty_kind(name, doc_type, account_type),
        doc_digits=doc_digits,
    )


def _match(rules: list, view: _View) -> tuple[Any, str] | None:
    """Primeira regra que casa no texto principal; só então tenta o nome do estabelecimento da Pluggy
    (o enriquecimento da Pluggy às vezes erra, ex.: atribuir 'Uber do Brasil' a um bar)."""
    for text, suffix in ((view.text, ""), (view.merchant_text, " [estabelecimento da Pluggy]")):
        if not text:
            continue
        for rule in rules:
            if suffix and rule.counterparty_key:
                continue  # regra por contraparte já foi testada na primeira passada
            pattern = rule.matches(text, direction=view.direction, account_type=view.account_type, key=view.key)
            if pattern:
                return rule, pattern + suffix
    return None


def _owner_identity(accounts) -> tuple[str | None, str | None]:
    digits = name = None
    for account in accounts:
        try:
            raw: dict[str, Any] = json.loads(account.raw_json)
        except (TypeError, ValueError):
            continue
        tax = "".join(ch for ch in str(raw.get("taxNumber") or "") if ch.isdigit())
        if len(tax) == 11:
            digits = digits or tax
        name = name or (normalize_counterparty(raw.get("owner")) or None)
    return digits, name


def _is_self(view: _View, owner_digits: str | None, owner_name: str | None) -> bool:
    if owner_digits and view.doc_digits and view.doc_digits == owner_digits:
        return True
    return bool(owner_name and view.counterparty and view.counterparty == owner_name)


def _starts(text: str, prefixes: tuple[str, ...]) -> bool:
    return any(text.startswith(prefix) for prefix in prefixes)


def _first(text: str, prefixes: tuple[str, ...]) -> str:
    return next(prefix for prefix in prefixes if text.startswith(prefix))
