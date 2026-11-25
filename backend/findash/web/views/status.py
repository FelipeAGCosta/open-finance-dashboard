"""Status: última sincronização, item da Pluggy, consentimento e fotos acumuladas."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db import queries
from findash.db.models import InvestmentSnapshot, SyncRun
from findash.sync.service import consent_warning, stale_hours
from findash.web.views.common import iso


def _utc(value: datetime | None) -> str | None:
    """DateTime do banco (UTC sem tzinfo) com o sufixo Z, para o navegador converter ao fuso local."""
    return f"{value.isoformat()}Z" if value else None


def run_json(run: SyncRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "started_at": _utc(run.started_at),
        "finished_at": _utc(run.finished_at),
        "full": run.full_sync,
        "new": run.transactions_new,
        "updated": run.transactions_updated,
        "snapshots": run.snapshots_created + run.snapshots_updated,
        "error": run.error_message,
    }


def status(session: Session, *, now: datetime, demo: bool) -> dict:
    items = []
    for item in queries.item_statuses(session):
        expires = item.consent_expires_at
        items.append(
            {
                "connector": item.connector_name,
                "status": item.status,
                "execution_status": item.execution_status,
                "last_updated": _utc(item.pluggy_last_updated_at),
                "next_auto_sync": _utc(item.next_auto_sync_at),
                "consent_expires_at": _utc(expires),
                "consent_days": (expires - now).days if expires else None,
                "consent_warning": consent_warning(expires, now),
                "checked_at": _utc(item.checked_at),
                "stale_hours": stale_hours(item.pluggy_last_updated_at, now),
            }
        )
    first, last, days = session.execute(
        select(
            func.min(InvestmentSnapshot.snapshot_date),
            func.max(InvestmentSnapshot.snapshot_date),
            func.count(func.distinct(InvestmentSnapshot.snapshot_date)),
        )
    ).one()
    first_tx, last_tx = queries.transaction_date_range(session)
    return {
        "demo": demo,
        "last_run": run_json(queries.last_sync_run(session)),
        "last_success": run_json(queries.last_successful_sync_run(session)),
        "items": items,
        "snapshots": {"days": days, "first": iso(first), "last": iso(last)},
        "transactions": {"first": iso(first_tx), "last": iso(last_tx)},
        "counts": queries.table_counts(session),
    }
