"""Ações da lista de transações com escopo ("só esta" ou "esta e todas desta contraparte") e desfazer.

- Só esta: grava em classification_overrides (vence todas as regras).
- Toda a contraparte (passadas e futuras):
    categoria / tipo / extraordinário -> regra em data/regras_pessoais.yaml (bloco da interface);
    fixo                          -> regra de recorrência manual (aparece na tela Fixos e no total).
  O ajuste "só esta" do mesmo campo nesta transação é removido, para a linha seguir a regra nova.
Toda ação devolve um pacote `undo` com o estado anterior; `undo()` restaura exatamente esse estado.
Depois de gravar, a classificação inteira é recalculada (histórico incluído).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.classify.fixed import remove_rule, set_counterparty_fixed
from findash.classify.personal_rules import restore_counterparty_rule, set_counterparty_rule
from findash.db.models import (
    LOAN_IN,
    LOAN_OUT,
    OWN_TRANSFER,
    REIMBURSEMENT,
    RULE_STATUSES,
    Account,
    ClassificationOverride,
    RecurringRule,
    Transaction,
    TransactionClassification,
)

OVERRIDE_FIELDS = ("movement_type", "category", "essential", "fixed", "extraordinary", "note")
# Tipos que a tela oferece: entradas na conta e saídas Pix (o resto segue a detecção automática).
INCOMING_KINDS = ("receita", REIMBURSEMENT, LOAN_IN, OWN_TRANSFER)
OUTGOING_KINDS = ("despesa", LOAN_OUT)


class ActionError(ValueError):
    """Pedido inválido para esta transação (mensagem pronta para a tela)."""


@dataclass
class Change:
    scope: str  # one | counterparty
    category: str | None = None
    fixed: bool | None = None
    kind: str | None = None
    fields: frozenset[str] = frozenset()  # quais de category/fixed/kind/extraordinary vieram no pedido
    extraordinary: bool | None = None


def kind_options(account_type: str, amount: int) -> tuple[str, ...]:
    if account_type != "BANK":
        return ()
    return INCOMING_KINDS if amount > 0 else OUTGOING_KINDS


def _override_state(override: ClassificationOverride | None) -> dict[str, Any] | None:
    return None if override is None else {f: getattr(override, f) for f in OVERRIDE_FIELDS}


def _set_override(session: Session, tx_id: str, now: datetime, **values: Any) -> None:
    override = session.get(ClassificationOverride, tx_id)
    if override is None:
        override = ClassificationOverride(transaction_id=tx_id, created_at=now, updated_at=now)
        session.add(override)
    for field, value in values.items():
        setattr(override, field, value)
    override.updated_at = now
    if all(getattr(override, f) in (None, "") for f in OVERRIDE_FIELDS):
        session.delete(override)  # nada sobrou: volta a seguir as regras
    session.flush()


def apply_change(
    session: Session,
    personal_rules_path,
    tx_id: str,
    change: Change,
    *,
    categories: dict[str, bool | None],
    now: datetime,
) -> dict[str, Any]:
    """Grava a mudança (sem recalcular) e devolve o pacote de desfazer."""
    row = session.execute(
        select(Transaction, TransactionClassification, Account)
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.id == tx_id)
    ).first()
    if row is None:
        raise LookupError("Transação não encontrada.")
    tx, cls, account = row
    if change.scope not in ("one", "counterparty"):
        raise ActionError("Escolha 'só esta' ou 'toda a contraparte'.")
    if "category" in change.fields and change.category is not None and change.category not in categories:
        raise ActionError(f"Categoria '{change.category}' não existe.")
    if "kind" in change.fields:
        allowed = kind_options(account.type, tx.amount_normalized_cents)
        if change.kind not in allowed:
            raise ActionError("Esse tipo não se aplica a esta transação.")
    if "extraordinary" in change.fields:
        if cls.movement_type not in ("despesa", "estorno", REIMBURSEMENT):
            raise ActionError("Só gastos podem ser marcados como extraordinários.")
        if change.extraordinary is None and change.scope == "counterparty":
            raise ActionError("Escolha se os gastos desta contraparte são extraordinários ou não.")
    if change.scope == "counterparty" and not cls.counterparty_key:
        raise ActionError("Esta transação não tem contraparte identificada: use 'só esta'.")

    undo: dict[str, Any] = {
        "transaction_id": tx_id,
        "override": _override_state(session.get(ClassificationOverride, tx_id)),
        "rules": [],
        "recurring": None,
    }
    direction = "entrada" if tx.amount_normalized_cents > 0 else "saida"

    if change.scope == "one":
        values: dict[str, Any] = {}
        if "category" in change.fields:
            values["category"] = change.category
        if "fixed" in change.fields:
            values["fixed"] = change.fixed
        if "kind" in change.fields:
            values["movement_type"] = change.kind
            if change.kind == REIMBURSEMENT and "category" not in change.fields:
                values["category"] = None
        if "extraordinary" in change.fields:
            values["extraordinary"] = change.extraordinary
        _set_override(session, tx_id, now, **values)
        return undo

    name = cls.counterparty or cls.counterparty_key
    clear: dict[str, Any] = {}
    if "extraordinary" in change.fields:
        before = set_counterparty_rule(personal_rules_path, name, "saida", extraordinario=bool(change.extraordinary))
        undo["rules"].append({"counterparty": name, "direction": "saida", "before": before})
        clear["extraordinary"] = None
    if "category" in change.fields or "kind" in change.fields:
        rule_values: dict[str, Any] = {}
        rule_direction = direction
        if "kind" in change.fields:
            rule_values["tipo"] = change.kind
            if change.kind == REIMBURSEMENT:
                rule_values["categoria"] = change.category if "category" in change.fields else None
            clear["movement_type"] = None
        elif "category" in change.fields:
            rule_direction = "saida"  # categoria vale para as compras; estornos herdam da compra
            rule_values["categoria"] = change.category
            rule_values["essencial"] = None
        if "category" in change.fields:
            clear["category"] = None
        before = set_counterparty_rule(personal_rules_path, name, rule_direction, **rule_values)
        undo["rules"].append({"counterparty": name, "direction": rule_direction, "before": before})
    if "fixed" in change.fields:
        if change.fixed is None:
            raise ActionError("Escolha se a contraparte é fixa ou não.")
        rule, previous = set_counterparty_fixed(
            session, cls.counterparty_key, bool(change.fixed), now=now, label=cls.counterparty, category=cls.category
        )
        undo["recurring"] = {"key": cls.counterparty_key, "rule_id": rule.id, "before_status": previous}
        clear["fixed"] = None
    if clear and session.get(ClassificationOverride, tx_id) is not None:
        _set_override(session, tx_id, now, **clear)
    return undo


def undo_change(session: Session, personal_rules_path, undo: dict[str, Any], *, now: datetime) -> None:
    tx_id = str(undo.get("transaction_id") or "")
    if session.get(Transaction, tx_id) is None:
        raise LookupError("Transação não encontrada.")
    before = undo.get("override")
    if before is not None and not isinstance(before, dict):
        raise ActionError("Pacote de desfazer inválido.")
    for rule in reversed(undo.get("rules") or []):  # desfaz na ordem inversa (mesma regra pode mudar duas vezes)
        if not isinstance(rule, dict) or rule.get("direction") not in ("saida", "entrada"):
            raise ActionError("Pacote de desfazer inválido.")
        restore_counterparty_rule(
            personal_rules_path, str(rule.get("counterparty") or ""), rule["direction"], rule.get("before")
        )
    recurring = undo.get("recurring")
    if recurring:
        rule = session.get(RecurringRule, int(recurring.get("rule_id") or 0))
        status = recurring.get("before_status")
        if rule is not None:
            if status is None:
                remove_rule(session, rule.id)
            elif status in RULE_STATUSES:
                rule.status, rule.updated_at, rule.status_changed_at = status, now, now
    override = session.get(ClassificationOverride, tx_id)
    if before is None:
        if override is not None:
            session.delete(override)
    else:
        values = {f: before.get(f) for f in OVERRIDE_FIELDS}
        if override is None:
            session.add(ClassificationOverride(transaction_id=tx_id, created_at=now, updated_at=now, **values))
        else:
            for field, value in values.items():
                setattr(override, field, value)
            override.updated_at = now
    session.flush()


def counterparty_count(session: Session, key: str | None, direction: str) -> int:
    if not key:
        return 0
    sign = (
        Transaction.amount_normalized_cents > 0 if direction == "entrada" else Transaction.amount_normalized_cents < 0
    )
    return (
        session.scalar(
            select(func.count())
            .select_from(TransactionClassification)
            .join(Transaction, Transaction.id == TransactionClassification.transaction_id)
            .where(TransactionClassification.counterparty_key == key, sign)
        )
        or 0
    )
