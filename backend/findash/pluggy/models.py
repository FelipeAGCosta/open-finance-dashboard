"""Modelos dos recursos da Pluggy usados pela sincronização.

Só os campos que viram colunas são tipados; o JSON completo é guardado à parte (raw_json).
Contrato conferido em https://docs.pluggy.ai/openapi/pluggy-api.json (2026-11-23).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _PluggyModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class PluggyItem(_PluggyModel):
    id: str
    status: str | None = None
    execution_status: str | None = None
    last_updated_at: datetime | None = None
    consent_expires_at: datetime | None = None
    next_auto_sync_at: datetime | None = None
    connector: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class PluggyAccount(_PluggyModel):
    id: str
    type: str
    subtype: str | None = None
    name: str | None = None
    marketing_name: str | None = None
    number: str | None = None
    balance: Decimal | None = None
    currency_code: str | None = None
    credit_data: dict[str, Any] | None = None
    updated_at: datetime | None = None


class PluggyTransaction(_PluggyModel):
    id: str
    account_id: str | None = None
    date: datetime
    description: str | None = None
    description_raw: str | None = None
    amount: Decimal
    amount_in_account_currency: Decimal | None = None
    currency_code: str | None = None
    type: str | None = None  # DEBIT | CREDIT, do ponto de vista do titular
    status: str | None = None  # POSTED | PENDING
    category: str | None = None
    category_id: str | None = None
    operation_type: str | None = None
    merchant: dict[str, Any] | None = None
    payment_data: dict[str, Any] | None = None
    credit_card_metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PluggyInvestment(_PluggyModel):
    id: str
    name: str | None = None
    code: str | None = None
    isin: str | None = None
    type: str | None = None
    subtype: str | None = None
    status: str | None = None
    currency_code: str | None = None
    balance: Decimal | None = None
    amount: Decimal | None = None
    amount_original: Decimal | None = None
    amount_profit: Decimal | None = None
    amount_withdrawal: Decimal | None = None
    quantity: Decimal | None = None
    value: Decimal | None = None
    date: datetime | None = None
    issuer: str | None = None
    issuer_cnpj: str | None = Field(default=None, alias="issuerCNPJ")
    purchase_date: datetime | None = None
    issue_date: datetime | None = None
    due_date: datetime | None = None
    rate: Decimal | None = None
    rate_type: str | None = None
    fixed_annual_rate: Decimal | None = None
    updated_at: datetime | None = None


class PluggyInvestmentTransaction(_PluggyModel):
    id: str
    type: str | None = None  # BUY | SELL | TAX | TRANSFER | INTEREST | AMORTIZATION
    movement_type: str | None = None
    quantity: Decimal | None = None
    value: Decimal | None = None
    amount: Decimal | None = None
    net_amount: Decimal | None = None
    date: datetime
    trade_date: datetime | None = None
    description: str | None = None
