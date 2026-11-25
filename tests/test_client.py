"""Cliente HTTP da Pluggy com transporte simulado (nenhuma chamada de rede real)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from findash.pluggy.client import PluggyClient
from findash.pluggy.errors import PluggyAuthError, PluggyError, PluggyRateLimitError, PluggyServerError
from findash.security import Redactor

SECRET = "segredo-ficticio-123456"  # gitleaks:allow (falso, para testar o mascaramento)
API_KEY = "apikey-ficticia-abcdef"


class Api:
    """Servidor falso: registra as requisições e responde conforme as regras do teste."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler
        self.auth_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/auth":
            self.auth_calls += 1
            body = json.loads(request.content)
            assert body == {"clientId": "client-ficticio", "clientSecret": SECRET}
            return httpx.Response(200, json={"apiKey": f"{API_KEY}-{self.auth_calls}"})
        return self.handler(request)


def make_client(api: Api, sleeps: list[float] | None = None, **kwargs) -> PluggyClient:
    sleeps = sleeps if sleeps is not None else []
    return PluggyClient(
        "client-ficticio",
        SECRET,
        redactor=kwargs.pop("redactor", Redactor()),
        transport=httpx.MockTransport(api),
        sleep=sleeps.append,
        **kwargs,
    )


def test_authenticates_once_and_sends_api_key_header():
    api = Api(lambda r: httpx.Response(200, json={"id": "item-1", "status": "UPDATED"}))
    with make_client(api) as client:
        client.get_item("item-1")
        client.get_item("item-1")
    data_requests = [r for r in api.requests if r.url.path != "/auth"]
    assert api.auth_calls == 1
    assert all(r.headers["X-API-KEY"] == f"{API_KEY}-1" for r in data_requests)
    assert api.requests[0].method == "POST" and all(r.method == "GET" for r in data_requests)


def test_v2_transactions_follow_cursor_until_null():
    pages = {
        None: {"results": [{"id": "t1"}, {"id": "t2"}], "next": "?accountId=acc-1&after=CURSOR1"},
        "CURSOR1": {"results": [{"id": "t3"}], "next": "?accountId=acc-1&after=CURSOR2"},
        "CURSOR2": {"results": [{"id": "t4"}], "next": None},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/transactions"
        assert request.url.params["accountId"] == "acc-1"
        return httpx.Response(200, json=pages[request.url.params.get("after")])

    api = Api(handler)
    with make_client(api) as client:
        rows = client.list_transactions("acc-1", date(2025, 11, 1))
    assert [r["id"] for r in rows] == ["t1", "t2", "t3", "t4"]
    first = next(r for r in api.requests if r.url.path == "/v2/transactions")
    assert first.url.params["dateFrom"] == "2025-11-01"


def test_page_based_endpoints_read_all_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"page": page, "totalPages": 3, "results": [{"id": f"i{page}"}]})

    with make_client(Api(handler)) as client:
        assert [r["id"] for r in client.list_investments("item-1")] == ["i1", "i2", "i3"]


def test_retries_429_respecting_retry_after_then_succeeds():
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}, json={"message": "Too many requests"}),
            httpx.Response(503, json={"message": "indisponível"}),
            httpx.Response(200, json={"id": "item-1"}),
        ]
    )
    sleeps: list[float] = []
    with make_client(Api(lambda r: next(responses)), sleeps) as client:
        assert client.get_item("item-1") == {"id": "item-1"}
    assert sleeps == [7.0, 4.0]  # Retry-After; depois backoff exponencial (2 * 2^1)


def test_persistent_429_raises_rate_limit_error():
    sleeps: list[float] = []
    with (
        make_client(Api(lambda r: httpx.Response(429, json={})), sleeps, max_retries=3) as client,
        pytest.raises(PluggyRateLimitError, match="HTTP 429"),
    ):
        client.get_item("item-1")
    assert len(sleeps) == 2


def test_persistent_5xx_raises_server_error_with_backoff():
    sleeps: list[float] = []
    with (
        make_client(Api(lambda r: httpx.Response(500, json={})), sleeps, max_retries=4) as client,
        pytest.raises(PluggyServerError, match="HTTP 500"),
    ):
        client.get_item("item-1")
    assert sleeps == [2.0, 4.0, 8.0]


def test_network_errors_are_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(200, json={"id": "ok"})

    with make_client(Api(handler)) as client:
        assert client.get_item("x") == {"id": "ok"}


def test_auth_failure_has_clear_message():
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 401, "message": "Unauthorized"})

    client = PluggyClient("client-ficticio", SECRET, redactor=Redactor(), transport=httpx.MockTransport(transport))
    with pytest.raises(PluggyAuthError) as caught:
        client.get_item("item-1")
    assert caught.value.status == 401
    assert "PLUGGY_CLIENT_SECRET" in str(caught.value) and "trial" in str(caught.value)


def test_forbidden_is_auth_error():
    with (
        make_client(Api(lambda r: httpx.Response(403, json={"codeDescription": "CLIENT_IP_NOT_ALLOWED"}))) as client,
        pytest.raises(PluggyAuthError) as caught,
    ):
        client.get_item("item-1")
    assert caught.value.status == 403 and caught.value.code == "CLIENT_IP_NOT_ALLOWED"


def test_expired_api_key_is_renewed_once():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if request.headers["X-API-KEY"].endswith("-1"):
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"id": "item-1"})

    api = Api(handler)
    with make_client(api) as client:
        assert client.get_item("item-1") == {"id": "item-1"}
    assert api.auth_calls == 2


def test_other_4xx_is_plain_error():
    with (
        make_client(Api(lambda r: httpx.Response(404, json={"message": "Item not found"}))) as client,
        pytest.raises(PluggyError, match="HTTP 404"),
    ):
        client.get_item("item-1")


def test_client_only_uses_get_besides_auth():
    def handler(request):
        if request.url.path == "/v2/transactions":
            return httpx.Response(200, json={"results": [], "next": None})
        return httpx.Response(200, json={"results": [], "totalPages": 1, "id": "x"})

    api = Api(handler)
    with make_client(api) as client:
        client.get_item("i")
        client.list_accounts("i")
        client.list_transactions("a")
        client.list_investments("i")
        client.list_investment_transactions("inv", date(2026, 1, 1))
    assert {(r.method, r.url.path) for r in api.requests if r.method != "GET"} == {("POST", "/auth")}
