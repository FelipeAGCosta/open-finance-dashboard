"""As migrações do Alembic produzem exatamente o esquema dos modelos."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from conftest import table_names
from findash.db.base import Base
from findash.db.migrate import upgrade_to_head


def test_migrations_match_models(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "render_as_batch": True})
        assert compare_metadata(context, Base.metadata) == []


def test_expected_tables(engine):
    assert table_names(engine) >= {
        "accounts",
        "transactions",
        "investments",
        "investment_snapshots",
        "investment_transactions",
        "item_status",
        "sync_runs",
        "alembic_version",
    }


def test_upgrade_is_idempotent(engine):
    upgrade_to_head(engine)
    upgrade_to_head(engine)
