"""Conversões de valores e sinais vindos da Pluggy.

Convenção única do banco (amount_normalized_cents), na moeda da conta:
NEGATIVO = dinheiro saindo / compra; POSITIVO = entrada / pagamento recebido.

Como a Pluggy entrega (conferido nos dados reais no spike):
- conta corrente: DEBIT vem negativo, CREDIT vem positivo;
- cartão de crédito: compra (DEBIT) vem positiva, pagamento/estorno (CREDIT) vem negativo.
O campo `type` é consistente nos dois casos, então ele decide o sinal; o sinal do
`amount` só é usado quando `type` não vier.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from findash.config import local_date
from findash.pluggy.models import PluggyTransaction

_CENT = Decimal("0.01")


def to_cents(value: Decimal | float | int | str | None) -> int | None:
    if value is None:
        return None
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((amount.quantize(_CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


def normalized_amount_cents(tx: PluggyTransaction, account_type: str) -> int:
    """Valor na moeda da conta com o sinal da convenção única."""
    base = tx.amount_in_account_currency if tx.amount_in_account_currency is not None else tx.amount
    cents = abs(to_cents(base) or 0)
    if tx.type == "DEBIT":
        return -cents
    if tx.type == "CREDIT":
        return cents
    signed = to_cents(base) or 0
    return -signed if account_type == "CREDIT" else signed


def pluggy_date(value: datetime | None) -> date | None:
    """Data de calendário de um campo de data da Pluggy.

    A Pluggy mistura dois formatos: datas de calendário gravadas à meia-noite UTC
    (ex.: transações de investimentos, 'T00:00:00.000Z') e instantes reais (ex.: transações
    da conta, 'T13:08:50.000Z'). Meia-noite UTC exata mantém o dia informado; o resto é
    convertido para o horário de Brasília (03:00Z vira 00:00 do mesmo dia; 02:38Z vira o dia anterior).
    """
    if value is None:
        return None
    utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if (utc.hour, utc.minute, utc.second, utc.microsecond) == (0, 0, 0, 0):
        return utc.date()
    return local_date(utc)


def credit_limits(credit_data: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not credit_data:
        return None, None
    return to_cents(credit_data.get("creditLimit")), to_cents(credit_data.get("availableCreditLimit"))
