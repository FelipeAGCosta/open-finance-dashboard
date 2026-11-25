"""Backup diário do banco com a API de backup do sqlite3 (consistente mesmo com o banco aberto)."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

BACKUP_PREFIX = "findash-"
KEEP_BACKUPS = 7

log = logging.getLogger(__name__)


def backup_database(db_path: Path, backups_dir: Path, today: date, keep: int = KEEP_BACKUPS) -> Path | None:
    """Cria data/backups/findash-AAAA-MM-DD.db e mantém só as `keep` cópias mais recentes.

    Uma cópia por dia: se a do dia já existe, ela é preservada (guarda o estado anterior à
    primeira sincronização do dia, que é o ponto de restauração mais útil).
    """
    if not db_path.exists():
        log.info("Banco ainda não existe; backup ignorado (primeira execução).")
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"{BACKUP_PREFIX}{today.isoformat()}.db"
    if target.exists():
        log.info("Backup do dia já existe: %s", target.name)
    else:
        temporary = target.with_name(target.name + ".tmp")
        temporary.unlink(missing_ok=True)
        with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(temporary)) as destination:
            source.backup(destination)
        os.replace(temporary, target)
        log.info("Backup criado: %s", target.name)
    prune_backups(backups_dir, keep)
    return target


def prune_backups(backups_dir: Path, keep: int = KEEP_BACKUPS) -> list[Path]:
    backups = sorted(p for p in backups_dir.glob(f"{BACKUP_PREFIX}????-??-??.db") if p.is_file())
    removed = backups[:-keep] if keep > 0 else backups
    for old in removed:
        old.unlink()
        log.info("Backup antigo removido: %s", old.name)
    return removed
