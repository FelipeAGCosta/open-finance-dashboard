"""Esquema inicial do banco local.

Revision ID: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("institution", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("subtype", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("marketing_name", sa.String(length=200), nullable=True),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("currency_code", sa.String(length=8), nullable=True),
        sa.Column("balance_cents", sa.BigInteger(), nullable=True),
        sa.Column("credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("available_credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("pluggy_updated_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_accounts_item_id"), ["item_id"], unique=False)

    op.create_table(
        "investments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("institution", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("isin", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=True),
        sa.Column("subtype", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("currency_code", sa.String(length=8), nullable=True),
        sa.Column("issuer", sa.String(length=200), nullable=True),
        sa.Column("issuer_cnpj", sa.String(length=32), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("rate", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("rate_type", sa.String(length=32), nullable=True),
        sa.Column("fixed_annual_rate", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("pluggy_updated_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investments")),
    )
    with op.batch_alter_table("investments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_investments_item_id"), ["item_id"], unique=False)

    op.create_table(
        "item_status",
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("connector_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("execution_status", sa.String(length=64), nullable=True),
        sa.Column("pluggy_last_updated_at", sa.DateTime(), nullable=True),
        sa.Column("next_auto_sync_at", sa.DateTime(), nullable=True),
        sa.Column("consent_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_item_status")),
    )
    op.create_table(
        "market_series",
        sa.Column("series_code", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("series_code", "date", name=op.f("pk_market_series")),
    )
    op.create_table(
        "plan_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("effective_month", sa.String(length=7), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_settings")),
    )
    with op.batch_alter_table("plan_settings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plan_settings_key"), ["key"], unique=False)

    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("counterparty_key", sa.String(length=200), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("avg_monthly_cents", sa.BigInteger(), nullable=True),
        sa.Column("months_count", sa.Integer(), nullable=True),
        sa.Column("median_interval_days", sa.Integer(), nullable=True),
        sa.Column("amount_variation", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("payment_interval_days", sa.Integer(), nullable=True),
        sa.Column("paycheck_cents", sa.BigInteger(), nullable=True),
        sa.Column("pay_frequency", sa.String(length=16), nullable=True),
        sa.Column("payday", sa.Integer(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=True),
        sa.Column("detected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('automatico', 'manual_sim', 'manual_nao')", name=op.f("ck_recurring_rules_status_valido")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_rules")),
        sa.UniqueConstraint("kind", "counterparty_key", name=op.f("uq_recurring_rules_kind_counterparty_key")),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("full_sync", sa.Boolean(), nullable=False),
        sa.Column("accounts_seen", sa.Integer(), nullable=False),
        sa.Column("transactions_new", sa.Integer(), nullable=False),
        sa.Column("transactions_updated", sa.Integer(), nullable=False),
        sa.Column("transactions_replaced", sa.Integer(), nullable=False),
        sa.Column("transactions_removed", sa.Integer(), nullable=False),
        sa.Column("investments_new", sa.Integer(), nullable=False),
        sa.Column("investments_updated", sa.Integer(), nullable=False),
        sa.Column("snapshots_created", sa.Integer(), nullable=False),
        sa.Column("snapshots_updated", sa.Integer(), nullable=False),
        sa.Column("investment_transactions_new", sa.Integer(), nullable=False),
        sa.Column("investment_transactions_updated", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("balance_cents", sa.BigInteger(), nullable=True),
        sa.Column("credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("available_credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_account_snapshots_account_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_snapshots")),
        sa.UniqueConstraint("snapshot_date", "account_id", name=op.f("uq_account_snapshots_snapshot_date_account_id")),
    )
    with op.batch_alter_table("account_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_account_snapshots_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_account_snapshots_snapshot_date"), ["snapshot_date"], unique=False)

    op.create_table(
        "investment_places",
        sa.Column("investment_id", sa.String(length=64), nullable=False),
        sa.Column("place", sa.String(length=12), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("place IN ('reserva', 'patrimonio')", name=op.f("ck_investment_places_place_valido")),
        sa.ForeignKeyConstraint(
            ["investment_id"], ["investments.id"], name=op.f("fk_investment_places_investment_id_investments")
        ),
        sa.PrimaryKeyConstraint("investment_id", name=op.f("pk_investment_places")),
    )
    op.create_table(
        "investment_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("investment_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("unit_value", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("balance_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_original_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_profit_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_withdrawal_cents", sa.BigInteger(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["investment_id"], ["investments.id"], name=op.f("fk_investment_snapshots_investment_id_investments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investment_snapshots")),
        sa.UniqueConstraint(
            "snapshot_date", "investment_id", name=op.f("uq_investment_snapshots_snapshot_date_investment_id")
        ),
    )
    with op.batch_alter_table("investment_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_investment_snapshots_investment_id"), ["investment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_investment_snapshots_snapshot_date"), ["snapshot_date"], unique=False)

    op.create_table(
        "investment_transactions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("investment_id", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=True),
        sa.Column("movement_type", sa.String(length=16), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("unit_value", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("net_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["investment_id"], ["investments.id"], name=op.f("fk_investment_transactions_investment_id_investments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investment_transactions")),
    )
    with op.batch_alter_table("investment_transactions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_investment_transactions_date"), ["date"], unique=False)
        batch_op.create_index(batch_op.f("ix_investment_transactions_investment_id"), ["investment_id"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=True),
        sa.Column("amount_original_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(length=8), nullable=True),
        sa.Column("amount_in_account_currency_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_normalized_cents", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=True),
        sa.Column("merchant_name", sa.String(length=200), nullable=True),
        sa.Column("merchant_cnpj", sa.String(length=32), nullable=True),
        sa.Column("merchant_json", sa.JSON(), nullable=True),
        sa.Column("payment_data_json", sa.JSON(), nullable=True),
        sa.Column("mcc", sa.Integer(), nullable=True),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("total_installments", sa.Integer(), nullable=True),
        sa.Column("bill_id", sa.String(length=64), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("category_pluggy", sa.String(length=120), nullable=True),
        sa.Column("category_id_pluggy", sa.String(length=32), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("replaced_by_id", sa.String(length=64), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(), nullable=True),
        sa.Column("pluggy_created_at", sa.DateTime(), nullable=True),
        sa.Column("pluggy_updated_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("state IN ('ativa', 'substituida', 'removida')", name=op.f("ck_transactions_state_valido")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_transactions_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"], ["transactions.id"], name=op.f("fk_transactions_replaced_by_id_transactions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index("ix_transactions_account_date", ["account_id", "date"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_date"), ["date"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_state"), ["state"], unique=False)
        batch_op.create_index(batch_op.f("ix_transactions_status"), ["status"], unique=False)

    op.create_table(
        "classification_overrides",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("movement_type", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("essential", sa.Boolean(), nullable=True),
        sa.Column("fixed", sa.Boolean(), nullable=True),
        sa.Column("extraordinary", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_classification_overrides_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_classification_overrides")),
    )
    op.create_table(
        "redemption_origins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("investment_id", sa.String(length=64), nullable=True),
        sa.Column("investment_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("gross_cents", sa.BigInteger(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["investment_id"], ["investments.id"], name=op.f("fk_redemption_origins_investment_id_investments")
        ),
        sa.ForeignKeyConstraint(
            ["investment_transaction_id"],
            ["investment_transactions.id"],
            name=op.f("fk_redemption_origins_investment_transaction_id_investment_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], name=op.f("fk_redemption_origins_transaction_id_transactions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_redemption_origins")),
    )
    with op.batch_alter_table("redemption_origins", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_redemption_origins_investment_id"), ["investment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_redemption_origins_transaction_id"), ["transaction_id"], unique=False)

    op.create_table(
        "transaction_classifications",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("movement_rule", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("essential", sa.Boolean(), nullable=True),
        sa.Column("rule_level", sa.String(length=32), nullable=True),
        sa.Column("rule_detail", sa.Text(), nullable=True),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("counterparty_key", sa.String(length=200), nullable=True),
        sa.Column("counterparty_kind", sa.String(length=4), nullable=True),
        sa.Column("recurring_rule_id", sa.Integer(), nullable=True),
        sa.Column("is_fixed", sa.Boolean(), nullable=False),
        sa.Column("extraordinary", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "movement_type IN ('receita', 'despesa', 'pagamento_fatura', 'transferencia_interna', 'aporte', 'resgate', 'renda_investimento', 'estorno', 'reembolso', 'emprestimo_concedido', 'devolucao_emprestimo', 'transferencia_propria')",
            name=op.f("ck_transaction_classifications_movement_type_valido"),
        ),
        sa.ForeignKeyConstraint(
            ["recurring_rule_id"],
            ["recurring_rules.id"],
            name=op.f("fk_transaction_classifications_recurring_rule_id_recurring_rules"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transaction_classifications_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_transaction_classifications")),
    )
    with op.batch_alter_table("transaction_classifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_transaction_classifications_category"), ["category"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_transaction_classifications_counterparty_key"), ["counterparty_key"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_transaction_classifications_movement_type"), ["movement_type"], unique=False
        )

    op.create_table(
        "transaction_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("other_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("investment_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["investment_transaction_id"],
            ["investment_transactions.id"],
            name=op.f("fk_transaction_links_investment_transaction_id_investment_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["other_transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transaction_links_other_transaction_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], name=op.f("fk_transaction_links_transaction_id_transactions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_links")),
        sa.UniqueConstraint("kind", "transaction_id", name=op.f("uq_transaction_links_kind_transaction_id")),
    )
    with op.batch_alter_table("transaction_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transaction_links_other_transaction_id"), ["other_transaction_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_transaction_links_transaction_id"), ["transaction_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("transaction_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transaction_links_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_transaction_links_other_transaction_id"))

    op.drop_table("transaction_links")
    with op.batch_alter_table("transaction_classifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transaction_classifications_movement_type"))
        batch_op.drop_index(batch_op.f("ix_transaction_classifications_counterparty_key"))
        batch_op.drop_index(batch_op.f("ix_transaction_classifications_category"))

    op.drop_table("transaction_classifications")
    with op.batch_alter_table("redemption_origins", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_redemption_origins_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_redemption_origins_investment_id"))

    op.drop_table("redemption_origins")
    op.drop_table("classification_overrides")
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transactions_status"))
        batch_op.drop_index(batch_op.f("ix_transactions_state"))
        batch_op.drop_index(batch_op.f("ix_transactions_date"))
        batch_op.drop_index("ix_transactions_account_date")

    op.drop_table("transactions")
    with op.batch_alter_table("investment_transactions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_investment_transactions_investment_id"))
        batch_op.drop_index(batch_op.f("ix_investment_transactions_date"))

    op.drop_table("investment_transactions")
    with op.batch_alter_table("investment_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_investment_snapshots_snapshot_date"))
        batch_op.drop_index(batch_op.f("ix_investment_snapshots_investment_id"))

    op.drop_table("investment_snapshots")
    op.drop_table("investment_places")
    with op.batch_alter_table("account_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_account_snapshots_snapshot_date"))
        batch_op.drop_index(batch_op.f("ix_account_snapshots_account_id"))

    op.drop_table("account_snapshots")
    op.drop_table("sync_runs")
    op.drop_table("recurring_rules")
    with op.batch_alter_table("plan_settings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plan_settings_key"))

    op.drop_table("plan_settings")
    op.drop_table("market_series")
    op.drop_table("item_status")
    with op.batch_alter_table("investments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_investments_item_id"))

    op.drop_table("investments")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_accounts_item_id"))

    op.drop_table("accounts")
