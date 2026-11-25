"""Escolha manual sobre uma compra "em trânsito": "já chegou (é o ativo X)" ou "ignorar".

A escolha vence o pareamento automático e persiste. Fica na tabela plan_settings (chave própria, uma linha
por transação, sem migração); trocar a escolha substitui a linha e "automático" (None) a apaga.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import Investment, PlanSetting, Transaction

KEY = "transito_manual"
ARRIVED, IGNORED = "chegou", "ignorar"
ACTIONS = (ARRIVED, IGNORED)


@dataclass(frozen=True)
class Choice:
    action: str
    investment_id: str | None = None

    def as_dict(self) -> dict:
        return {"action": self.action, "investment_id": self.investment_id}


def _rows(session: Session) -> list[PlanSetting]:
    return list(session.scalars(select(PlanSetting).where(PlanSetting.key == KEY).order_by(PlanSetting.id)))


def load(session: Session) -> dict[str, Choice]:
    out: dict[str, Choice] = {}
    for row in _rows(session):
        value = row.value_json or {}
        tx_id, action = value.get("transaction_id"), value.get("action")
        if isinstance(tx_id, str) and action in ACTIONS:
            out[tx_id] = Choice(action, value.get("investment_id"))
    return out


def set_choice(
    session: Session, transaction_id: str, action: str | None, investment_id: str | None, *, now: datetime
) -> Choice | None:
    """Grava (ou apaga, com action=None) a escolha; devolve a anterior, para desfazer."""
    if session.get(Transaction, transaction_id) is None:
        raise LookupError("Transação não encontrada.")
    if action is not None and action not in ACTIONS:
        raise ValueError("Escolha inválida: use 'chegou', 'ignorar' ou nada (automático).")
    if action == ARRIVED and (not investment_id or session.get(Investment, investment_id) is None):
        raise ValueError("Diga qual ativo chegou.")
    previous = load(session).get(transaction_id)
    for row in _rows(session):
        if (row.value_json or {}).get("transaction_id") == transaction_id:
            session.delete(row)
    if action is not None:
        session.add(
            PlanSetting(
                key=KEY,
                effective_month=f"{now:%Y-%m}",
                created_at=now,
                value_json={
                    "transaction_id": transaction_id,
                    "action": action,
                    "investment_id": investment_id if action == ARRIVED else None,
                },
            )
        )
    session.flush()
    return previous
