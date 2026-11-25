"""Backup diário com a API do sqlite3 e retenção das 7 cópias mais recentes."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta

from findash.sync.backup import backup_database


def make_db(path, value: str) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("DELETE FROM t")
        conn.execute("INSERT INTO t VALUES (?)", (value,))
        conn.commit()


def read_value(path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT v FROM t").fetchone()[0]


def test_no_backup_before_database_exists(tmp_path):
    assert backup_database(tmp_path / "findash.db", tmp_path / "backups", date(2026, 1, 10)) is None


def test_backup_is_a_consistent_copy_even_with_open_connection(tmp_path):
    db = tmp_path / "findash.db"
    make_db(db, "original")
    with closing(sqlite3.connect(db)) as open_conn:  # banco aberto durante o backup
        open_conn.execute("SELECT 1")
        target = backup_database(db, tmp_path / "backups", date(2026, 1, 10))
    assert target.name == "findash-2026-01-10.db"
    assert read_value(target) == "original"
    assert not list((tmp_path / "backups").glob("*.tmp"))


def test_one_backup_per_day_keeps_first_copy_of_the_day(tmp_path):
    db = tmp_path / "findash.db"
    make_db(db, "manhã")
    backup_database(db, tmp_path / "backups", date(2026, 1, 10))
    make_db(db, "noite")
    target = backup_database(db, tmp_path / "backups", date(2026, 1, 10))
    assert read_value(target) == "manhã"
    assert len(list((tmp_path / "backups").glob("findash-*.db"))) == 1


def test_keeps_only_seven_most_recent(tmp_path):
    db = tmp_path / "findash.db"
    backups = tmp_path / "backups"
    make_db(db, "x")
    start = date(2026, 1, 1)
    for offset in range(10):
        backup_database(db, backups, start + timedelta(days=offset))
    names = sorted(p.name for p in backups.glob("findash-*.db"))
    assert names == [f"findash-{start + timedelta(days=o):%Y-%m-%d}.db" for o in range(3, 10)]


def test_retention_ignores_unrelated_files(tmp_path):
    db = tmp_path / "findash.db"
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "anotacoes.txt").write_text("não mexer", encoding="utf-8")
    make_db(db, "x")
    for offset in range(9):
        backup_database(db, backups, date(2026, 1, 1) + timedelta(days=offset))
    assert (backups / "anotacoes.txt").exists()
