"""Infraestrutura de testes: banco temporário migrado pelo Alembic e uma Pluggy falsa.

Todos os dados vêm de tests/fixtures/ e são sintéticos.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, select

from findash.config import ItemConfig
from findash.db.base import make_engine, make_session_factory
from findash.db.migrate import upgrade_to_head
from findash.security import Redactor

FIXTURES = Path(__file__).parent / "fixtures"
ITEM_ID = "00000000-0000-4000-8000-000000000001"
ITEMS = (ItemConfig(ITEM_ID, "nubank"),)
BANK_ID = "00000000-0000-4000-8000-0000000000a1"
CARD_ID = "00000000-0000-4000-8000-0000000000c1"
PENDING_REPLACED_ID = "00000000-0000-4000-8000-0000000000e1"
PENDING_REMOVED_ID = "00000000-0000-4000-8000-0000000000e2"
REPLACEMENT_ID = "00000000-0000-4000-8000-0000000000d5"

DAY1 = datetime(2026, 1, 10, 12, 0, 0)  # UTC sem tzinfo, como no banco
DAY2 = datetime(2026, 1, 11, 12, 0, 0)


def load(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def scenario(day: int) -> dict[str, Any]:
    folder = f"day{day}"
    return {
        "item": load("common/item.json"),
        "accounts": load("common/accounts.json"),
        "transactions": {
            BANK_ID: load("common/transactions_bank.json"),
            CARD_ID: load("common/transactions_card_posted.json") + load(f"{folder}/transactions_card_extra.json"),
        },
        "investments": load(f"{folder}/investments.json"),
        "investment_transactions": load("common/investment_transactions.json"),
    }


class FakeSource:
    """Imita o PluggyClient: devolve cópias do cenário e aplica os filtros de data como a API."""

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.calls: list[tuple[str, str, date | None]] = []
        self.closed = False

    def get_item(self, item_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.data["item"])

    def list_accounts(self, item_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["accounts"])

    def list_transactions(self, account_id: str, date_from: date | None = None) -> list[dict[str, Any]]:
        self.calls.append(("transactions", account_id, date_from))
        return _filter(self.data["transactions"].get(account_id, []), date_from)

    def list_investments(self, item_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["investments"])

    def list_investment_transactions(self, investment_id: str, date_from: date | None = None) -> list[dict[str, Any]]:
        self.calls.append(("investment_transactions", investment_id, date_from))
        return _filter(self.data["investment_transactions"].get(investment_id, []), date_from)

    def close(self) -> None:
        self.closed = True


def _filter(rows: list[dict[str, Any]], date_from: date | None) -> list[dict[str, Any]]:
    rows = copy.deepcopy(rows)
    if date_from is None:
        return rows
    return [row for row in rows if row["date"][:10] >= date_from.isoformat()]


@pytest.fixture
def engine(tmp_path: Path):
    engine = make_engine(tmp_path / "findash-teste.db")
    upgrade_to_head(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def redactor() -> Redactor:
    return Redactor()


VOLATILE_COLUMNS = {"last_seen_at", "captured_at", "checked_at", "computed_at", "created_at"}


def dump_tables(session_factory, *, skip: tuple[str, ...] = ("sync_runs",)) -> dict[str, list[tuple]]:
    """Conteúdo de todas as tabelas de dados, sem colunas que mudam a cada execução."""
    from findash.db.base import Base

    result: dict[str, list[tuple]] = {}
    with session_factory() as session:
        for table in Base.metadata.sorted_tables:
            if table.name in skip:
                continue
            columns = [c for c in table.columns if c.name not in VOLATILE_COLUMNS]
            rows = session.execute(select(*columns).order_by(*table.primary_key.columns)).all()
            result[table.name] = [tuple(row) for row in rows]
    return result


def table_names(engine) -> set[str]:
    return set(inspect(engine).get_table_names())
