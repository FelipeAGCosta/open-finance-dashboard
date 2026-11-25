"""Máscara de segredos: client secret e apiKey nunca chegam a logs, erros, sync_runs ou JSONs."""

from __future__ import annotations

import logging

import httpx
import pytest
from sqlalchemy import select

from conftest import DAY1, ITEMS, FakeSource, scenario
from findash.config import ItemConfig
from findash.db.models import SyncRun, Transaction
from findash.pluggy.client import PluggyClient
from findash.pluggy.errors import PluggyError
from findash.security import MASK, RedactingFormatter, Redactor
from findash.sync.service import SyncFailed, run_sync

SECRET = "client-secret-ficticio-XYZ987"
API_KEY = "api-key-ficticia-QWE654"  # gitleaks:allow (falso, para testar o mascaramento)


def test_redactor_masks_all_known_secrets():
    redactor = Redactor()
    redactor.add(SECRET)
    redactor.add(API_KEY)
    redactor.add("")  # ignorado
    redactor.add("abc")  # curto demais: ignorado para não mascarar texto comum
    text = f"secret={SECRET} key={API_KEY} abc"
    assert redactor(text) == f"secret={MASK} key={MASK} abc"


def test_logging_formatter_masks_messages_and_tracebacks():
    redactor = Redactor()
    redactor.add(SECRET)
    formatter = RedactingFormatter("%(message)s", redactor=redactor)
    try:
        raise ValueError(f"falhou com {SECRET}")
    except ValueError:
        import sys

        record = logging.LogRecord("findash", logging.ERROR, __file__, 1, "token %s", (SECRET,), sys.exc_info())
    output = formatter.format(record)
    assert SECRET not in output and output.count(MASK) >= 2


def test_client_errors_never_contain_secret_or_api_key():
    redactor = Redactor()

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": API_KEY})
        # servidor que (indevidamente) ecoa as credenciais no corpo do erro
        return httpx.Response(400, json={"message": f"bad request {SECRET} {API_KEY}"})

    client = PluggyClient("client-ficticio", SECRET, redactor=redactor, transport=httpx.MockTransport(transport))
    with pytest.raises(PluggyError) as caught:
        client.get_item("item-1")
    message = str(caught.value)
    assert SECRET not in message and API_KEY not in message and MASK in message


def test_settings_repr_hides_secret():
    from pydantic import SecretStr

    from findash.config import PluggySettings

    settings = PluggySettings(client_id="id-ficticio", client_secret=SecretStr(SECRET), items=(ItemConfig("item"),))
    assert SECRET not in repr(settings) and SECRET not in str(settings)


def test_secret_never_reaches_database(session_factory, engine, tmp_path):
    redactor = Redactor()
    redactor.add(SECRET)

    # 1) payload da API contendo o segredo: raw_json é gravado mascarado
    data = scenario(1)
    data["transactions"][next(iter(data["transactions"]))][0]["descriptionRaw"] = f"eco {SECRET}"
    run_sync(session_factory, FakeSource(data), ITEMS, redactor=redactor, clock=lambda: DAY1)

    # 2) erro contendo o segredo: sync_runs.error_message é gravado mascarado
    class Leaky(FakeSource):
        def get_item(self, item_id):
            raise PluggyError(f"falha simulada {SECRET}")

    with pytest.raises(SyncFailed) as caught:
        run_sync(session_factory, Leaky(scenario(1)), ITEMS, redactor=redactor, clock=lambda: DAY1)
    assert SECRET not in str(caught.value)

    with session_factory() as session:
        errors = session.scalars(select(SyncRun.error_message).where(SyncRun.status == "error")).all()
        raws = session.scalars(select(Transaction.raw_json)).all()
    assert errors and all(SECRET not in e and MASK in e for e in errors)
    assert any(MASK in raw for raw in raws)
    engine.dispose()
    db_file = next(tmp_path.glob("*.db"))
    assert SECRET.encode() not in db_file.read_bytes()
