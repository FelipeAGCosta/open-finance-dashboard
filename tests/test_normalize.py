"""Normalização de sinal (conta × cartão), centavos e datas."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from findash.pluggy.models import PluggyTransaction
from findash.sync.normalize import credit_limits, normalized_amount_cents, pluggy_date, to_cents


def tx(**fields) -> PluggyTransaction:
    base = {"id": "t", "date": "2026-01-05T13:00:00.000Z", "amount": 0}
    return PluggyTransaction.model_validate({**base, **fields})


@pytest.mark.parametrize(
    ("account_type", "fields", "expected"),
    [
        ("BANK", {"amount": -50.0, "type": "DEBIT"}, -5000),  # saída da conta: negativa
        ("BANK", {"amount": 1500.0, "type": "CREDIT"}, 150000),  # entrada na conta: positiva
        ("CREDIT", {"amount": 89.9, "type": "DEBIT"}, -8990),  # compra no cartão vem positiva -> negativa
        ("CREDIT", {"amount": -500.0, "type": "CREDIT"}, 50000),  # pagamento da fatura vem negativo -> positivo
        ("CREDIT", {"amount": -15.0, "type": "CREDIT"}, 1500),  # estorno no cartão: entrada
    ],
)
def test_sign_convention_bank_vs_card(account_type, fields, expected):
    assert normalized_amount_cents(tx(**fields), account_type) == expected


def test_foreign_currency_uses_amount_in_account_currency():
    purchase = tx(amount=10.0, currencyCode="USD", amountInAccountCurrency=55.2, type="DEBIT")
    assert normalized_amount_cents(purchase, "CREDIT") == -5520


@pytest.mark.parametrize(
    ("account_type", "amount", "expected"),
    [("BANK", -20.0, -2000), ("BANK", 20.0, 2000), ("CREDIT", 20.0, -2000), ("CREDIT", -20.0, 2000)],
)
def test_sign_fallback_without_type(account_type, amount, expected):
    assert normalized_amount_cents(tx(amount=amount), account_type) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (0.1, 10), (12.345, 1235), (-12.345, -1235), (Decimal("1234.56"), 123456), (100, 10000)],
)
def test_to_cents(value, expected):
    assert to_cents(value) == expected


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-01-07T02:38:26.000Z", date(2026, 1, 6)),  # 23:38 em Brasília: dia anterior
        ("2026-01-07T13:00:00.000Z", date(2026, 1, 7)),
        ("2026-01-07T03:00:00.000Z", date(2026, 1, 7)),  # meia-noite de Brasília
        ("2026-01-07T00:00:00.000Z", date(2026, 1, 7)),  # data de calendário (meia-noite UTC)
    ],
)
def test_pluggy_date(iso, expected):
    assert pluggy_date(datetime.fromisoformat(iso.replace("Z", "+00:00"))) == expected


def test_pluggy_date_none_and_naive():
    assert pluggy_date(None) is None
    assert pluggy_date(datetime(2026, 1, 7, 2, 0)) == date(2026, 1, 6)
    assert pluggy_date(datetime(2026, 1, 7, 2, 0, tzinfo=UTC)) == date(2026, 1, 6)


def test_credit_limits():
    assert credit_limits({"creditLimit": 5000, "availableCreditLimit": 4567.9}) == (500000, 456790)
    assert credit_limits(None) == (None, None)
