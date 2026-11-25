"""Construtor de extratos SINTÉTICOS para os testes de classificação (nomes e valores inventados)."""

from __future__ import annotations

import itertools
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from findash.classify.engine import classify_all
from findash.classify.rules import load_rulebook
from findash.classify.salary import WEEKLY, SalarySchedule
from findash.config import PROJECT_ROOT
from findash.db.models import (
    Account,
    AccountSnapshot,
    Investment,
    InvestmentSnapshot,
    InvestmentTransaction,
    Transaction,
)

CONFIG_DIR = PROJECT_ROOT / "config"
NOW = datetime(2026, 11, 20, 12, 0)
OWNER_NAME = "Pessoa Titular Exemplo"
OWNER_CPF = "111.222.333-44"
BANK = "00000000-0000-4000-8000-00000000ba01"
CARD = "00000000-0000-4000-8000-00000000ca01"
INVESTMENT = "00000000-0000-4000-8000-00000000fe01"


def person(name: str, cpf: str = "999.888.777-66") -> dict:
    return {"name": name, "documentNumber": {"type": "CPF", "value": cpf}}


def company(name: str, cnpj: str = "00.000.000/0001-91") -> dict:
    return {"name": name, "documentNumber": {"type": "CNPJ", "value": cnpj}}


class Ledger:
    def __init__(self, session_factory, personal_rules_path: Path):
        self.salary = SalarySchedule(WEEKLY, payday=0, grace_days=2)  # os cenários usam salário semanal às segundas
        self.session_factory = session_factory
        self.personal_rules_path = personal_rules_path
        self.personal_rules_path.write_text("regras: []\n", encoding="utf-8")
        self._ids = itertools.count(1)
        with session_factory() as session:
            for account_id, kind, subtype in ((BANK, "BANK", "CHECKING_ACCOUNT"), (CARD, "CREDIT", "CREDIT_CARD")):
                raw = {"owner": OWNER_NAME, "taxNumber": OWNER_CPF if kind == "BANK" else None}
                session.add(
                    Account(
                        id=account_id,
                        item_id="item",
                        institution="nubank",
                        type=kind,
                        subtype=subtype,
                        name=f"Conta {kind}",
                        raw_json=json.dumps(raw),
                        first_seen_at=NOW,
                        last_seen_at=NOW,
                    )
                )
            session.add(
                Investment(
                    id=INVESTMENT,
                    item_id="item",
                    institution="nubank",
                    name="FICT11",
                    code="FICT11",
                    type="EQUITY",
                    subtype="REAL_ESTATE_FUND",
                    raw_json="{}",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
            session.commit()

    def personal_rules(self, text: str) -> None:
        self.personal_rules_path.write_text(text, encoding="utf-8")

    def tx(
        self,
        account: str,
        day: date,
        amount: float,
        description: str,
        *,
        status: str = "POSTED",
        mcc: int | None = None,
        category: str | None = None,
        payment_data: dict | None = None,
        merchant: str | None = None,
        installment: tuple[int, int] | None = None,
        purchase_date: date | None = None,
        bill_month: str | None = None,
        tx_id: str | None = None,
    ) -> str:
        """`amount` já na convenção única (negativo = saída/compra; positivo = entrada)."""
        tx_id = tx_id or f"00000000-0000-4000-8000-{next(self._ids):012d}"
        cents = round(amount * 100)
        original = cents if account == BANK else -cents
        raw = {"id": tx_id, "description": description}
        if bill_month:
            raw["creditCardMetadata"] = {"billForecastDate": bill_month}
        with self.session_factory() as session:
            session.add(
                Transaction(
                    id=tx_id,
                    account_id=account,
                    date=day,
                    occurred_at=datetime(day.year, day.month, day.day, 15),
                    description=description,
                    amount_original_cents=original,
                    currency_code="BRL",
                    amount_normalized_cents=cents,
                    type="DEBIT" if cents < 0 else "CREDIT",
                    status=status,
                    merchant_name=merchant,
                    payment_data_json=payment_data,
                    mcc=mcc,
                    installment_number=installment[0] if installment else None,
                    total_installments=installment[1] if installment else None,
                    purchase_date=purchase_date,
                    category_pluggy=category,
                    raw_json=json.dumps(raw),
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
            session.commit()
        return tx_id

    def investment_tx(
        self,
        day: date,
        kind: str,
        amount: float,
        *,
        investment: str = INVESTMENT,
        net: float | None = None,
        quantity: float | None = None,
    ) -> str:
        tx_id = f"00000000-0000-4000-8000-{next(self._ids):012d}"
        with self.session_factory() as session:
            session.add(
                InvestmentTransaction(
                    id=tx_id,
                    investment_id=investment,
                    date=day,
                    type=kind,
                    amount_cents=round(amount * 100),
                    net_amount_cents=round((amount if net is None else net) * 100),
                    quantity=Decimal(str(quantity)) if quantity is not None else None,
                    raw_json="{}",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
            session.commit()
        return tx_id

    def investment(self, code: str | None, kind: str, subtype: str, *, name: str | None = None) -> str:
        inv_id = f"00000000-0000-4000-8000-{next(self._ids):012d}"
        with self.session_factory() as session:
            session.add(
                Investment(
                    id=inv_id,
                    item_id="item",
                    institution="nubank",
                    name=name or code,
                    code=code,
                    type=kind,
                    subtype=subtype,
                    raw_json="{}",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
            session.commit()
        return inv_id

    def snapshot(
        self,
        day: date,
        investment: str,
        *,
        quantity: float | None,
        unit_value: float | None,
        balance: float,
        amount: float | None = None,
        original: float | None = None,
    ) -> None:
        with self.session_factory() as session:
            session.add(
                InvestmentSnapshot(
                    snapshot_date=day,
                    investment_id=investment,
                    quantity=Decimal(str(quantity)) if quantity is not None else None,
                    unit_value=Decimal(str(unit_value)) if unit_value is not None else None,
                    balance_cents=round(balance * 100),
                    amount_cents=round((balance if amount is None else amount) * 100),
                    amount_original_cents=round(original * 100) if original is not None else None,
                    captured_at=NOW,
                )
            )
            session.commit()

    def account_snapshot(self, day: date, account: str, balance: float) -> None:
        with self.session_factory() as session:
            session.add(
                AccountSnapshot(
                    snapshot_date=day, account_id=account, balance_cents=round(balance * 100), captured_at=NOW
                )
            )
            session.commit()

    def classify(self, now: datetime = NOW):
        book = load_rulebook(CONFIG_DIR, self.personal_rules_path)
        with self.session_factory() as session:
            stats = classify_all(session, book, now=now, salary=self.salary)
            session.commit()
        return stats
