"""Ambiente do Alembic. Usa a conexão recebida (CLI/testes) ou o banco padrão do projeto."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from findash.config import Paths
from findash.db import models  # noqa: F401  (registra as tabelas no metadata)
from findash.db.base import Base, make_engine

config = context.config
target_metadata = Base.metadata

# Só configura logging quando chamado pela linha de comando do alembic (com alembic.ini).
if config.config_file_name is not None and not config.attributes.get("connection"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # ALTER TABLE no SQLite via recriação da tabela
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url") or f"sqlite:///{Paths.default().db_path.as_posix()}"
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return
    url = config.get_main_option("sqlalchemy.url")
    if url:
        from sqlalchemy import create_engine

        engine = create_engine(url)
    else:
        engine = make_engine(Paths.default().db_path)
    with engine.connect() as conn:
        _configure_and_run(conn)
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
