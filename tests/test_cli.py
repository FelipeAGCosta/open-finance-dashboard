"""CLI de ponta a ponta com a Pluggy falsa e pastas temporárias."""

from __future__ import annotations

import pytest

import findash.cli as cli
from conftest import DAY1, FakeSource, scenario
from findash.config import Paths
from findash.pluggy.errors import PluggyAuthError
from findash.security import Redactor
from findash.sync.service import EXIT_AUTH, EXIT_ERROR, EXIT_OK

CREDENTIALS = (
    "PLUGGY_CLIENT_ID=client-ficticio\n"
    "PLUGGY_CLIENT_SECRET=segredo-ficticio-cli-123\n"
    "PLUGGY_ITEM_ID=00000000-0000-4000-8000-000000000001\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS", "PLUGGY_ITEM_ID"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(CREDENTIALS, encoding="utf-8")
    monkeypatch.setattr(cli, "utcnow", lambda: DAY1)
    return Paths(tmp_path)


def test_sync_then_status(project, capsys):
    sources: list[FakeSource] = []

    def factory(settings, redactor):
        assert settings.client_secret.get_secret_value() == "segredo-ficticio-cli-123"
        sources.append(FakeSource(scenario(1)))
        return sources[-1]

    assert cli.cmd_sync(project, source_factory=factory, redactor=Redactor()) == EXIT_OK
    out = capsys.readouterr().out
    assert "primeira execução" in out and "10 novas" in out
    assert sources[0].closed
    assert project.db_path.exists()

    # segunda execução: backup do dia criado antes de sincronizar, nada duplicado
    assert cli.cmd_sync(project, source_factory=lambda s, r: FakeSource(scenario(1)), redactor=Redactor()) == EXIT_OK
    out = capsys.readouterr().out
    assert "0 novas, 0 atualizadas, 10 sem mudança" in out
    assert (project.backups_dir / "findash-2026-01-10.db").exists()

    assert cli.cmd_status(project) == EXIT_OK
    status = capsys.readouterr().out
    assert "MeuPluggy" in status and "Conta corrente (Conta Exemplo)" in status
    assert "Cartão de crédito (Cartao Exemplo)" in status
    # números de conta e cartão nunca aparecem
    assert "99999-1" not in status and "88887777" not in status
    assert "segredo-ficticio-cli-123" not in status


def test_sync_auth_failure_exit_code_and_no_secret_in_output(project, capsys):
    class Unauthorized(FakeSource):
        def get_item(self, item_id):
            raise PluggyAuthError("Autenticação recusada pela Pluggy (HTTP 401) em POST /auth", status=401)

    code = cli.cmd_sync(project, source_factory=lambda s, r: Unauthorized(scenario(1)), redactor=Redactor())
    assert code == EXIT_AUTH
    out = capsys.readouterr().out
    assert "HTTP 401" in out and "segredo-ficticio-cli-123" not in out
    assert cli.cmd_status(project) == EXIT_OK
    assert "ERROR" in capsys.readouterr().out


def test_missing_credentials_is_recorded(project, capsys):
    (project.root / ".env").write_text("PLUGGY_CLIENT_ID=x\n", encoding="utf-8")
    assert cli.cmd_sync(project, source_factory=lambda s, r: FakeSource(scenario(1)), redactor=Redactor()) == EXIT_ERROR
    assert "PLUGGY_CLIENT_SECRET" in capsys.readouterr().out


def test_sync_classifies_and_commands_work(project, capsys):
    import argparse

    from findash.db.base import make_engine, make_session_factory
    from findash.db.models import TransactionClassification

    assert cli.cmd_sync(project, source_factory=lambda s, r: FakeSource(scenario(1)), redactor=Redactor()) == EXIT_OK
    out = capsys.readouterr().out
    assert "Classificação: 10 transações" in out
    assert project.personal_rules_path.exists()  # arquivo de regras pessoais criado vazio, em data/

    def run(**kwargs):
        defaults = {
            "acao": None,
            "id": None,
            "mes": None,
            "limite": 30,
            "categoria": None,
            "tipo": None,
            "essencial": None,
            "nota": None,
            "remover": False,
            "fixo": None,
        }
        return cli._with_database(project, argparse.Namespace(**{**defaults, **kwargs}))

    assert run(command="classificar") == EXIT_OK
    assert "Faturas:" in capsys.readouterr().out
    assert run(command="resumo", mes="2026-01") == EXIT_OK
    resumo = capsys.readouterr().out
    assert "Resumo de 2026-01" in resumo and "Taxa de poupança" in resumo
    assert run(command="fixos") == EXIT_OK
    assert run(command="a-classificar") == EXIT_OK
    capsys.readouterr()

    pix = "00000000-0000-4000-8000-0000000000b1"
    assert run(command="override", id=pix, categoria="Moradia", essencial="s", nota="aluguel") == EXIT_OK
    assert run(command="override", id=pix, categoria="Inexistente") == EXIT_ERROR
    # o override sobrevive a um novo sync (que reclassifica tudo no final)
    assert cli.cmd_sync(project, source_factory=lambda s, r: FakeSource(scenario(1)), redactor=Redactor()) == EXIT_OK
    engine = make_engine(project.db_path)
    with make_session_factory(engine)() as session:
        result = session.get(TransactionClassification, pix)
        assert (result.category, result.essential, result.rule_level) == ("Moradia", True, "override")
    engine.dispose()


def test_status_without_database(project, capsys):
    assert cli.cmd_status(project) == EXIT_ERROR
    assert "findash sync" in capsys.readouterr().out
