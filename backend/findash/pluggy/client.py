"""Cliente HTTP somente leitura da API da Pluggy.

- POST /auth (clientId, clientSecret) -> apiKey, válido por 2 horas, enviado em X-API-KEY.
  É a única chamada que não é GET.
- GET /v2/transactions pagina por cursor (`next` é acrescentado ao caminho até vir null);
  /accounts, /investments e /investments/{id}/transactions paginam por page/totalPages.
- 429 e 5xx: novas tentativas com backoff exponencial, respeitando Retry-After.
- 401 numa chamada de dados: renova o apiKey uma vez (pode ter expirado) e repete.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from findash.pluggy.errors import (
    PluggyAuthError,
    PluggyError,
    PluggyNetworkError,
    PluggyRateLimitError,
    PluggyServerError,
)
from findash.security import Redactor

BASE_URL = "https://api.pluggy.ai"
PAGE_SIZE = 500
MAX_PAGES = 1000  # trava contra paginação infinita

log = logging.getLogger(__name__)


class PluggyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        redactor: Redactor,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 60.0,
    ):
        redactor.add(client_secret)
        self._client_id = client_id
        self._client_secret = client_secret
        self._redact = redactor
        self._api_key: str | None = None
        self._max_retries = max(1, max_retries)
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport, headers={"Accept": "application/json"}
        )

    # ------------------------------------------------------------------ ciclo de vida

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PluggyClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ recursos

    def get_item(self, item_id: str) -> dict[str, Any]:
        return self._get(f"/items/{_segment(item_id)}")

    def list_accounts(self, item_id: str) -> list[dict[str, Any]]:
        return self._get_paged("/accounts", {"itemId": item_id})

    def list_transactions(self, account_id: str, date_from: date | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"accountId": account_id}
        if date_from is not None:
            params["dateFrom"] = date_from.isoformat()
        results: list[dict[str, Any]] = []
        body = self._get("/v2/transactions", params)
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            results.extend(body.get("results") or [])
            cursor = body.get("next")
            if not cursor:
                return results
            if cursor in seen:
                raise PluggyError("A Pluggy repetiu o cursor de /v2/transactions; paginação interrompida.")
            seen.add(cursor)
            body = self._get("/v2/transactions" + cursor)  # `next` já traz filtros e cursor
        raise PluggyError(f"/v2/transactions passou de {MAX_PAGES} páginas; paginação interrompida.")

    def list_investments(self, item_id: str) -> list[dict[str, Any]]:
        return self._get_paged("/investments", {"itemId": item_id})

    def list_investment_transactions(self, investment_id: str, date_from: date | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if date_from is not None:
            params["from"] = date_from.isoformat()
        return self._get_paged(f"/investments/{_segment(investment_id)}/transactions", params)

    # ------------------------------------------------------------------ HTTP

    def authenticate(self) -> None:
        body = self._send(
            "POST",
            "/auth",
            json={"clientId": self._client_id, "clientSecret": self._client_secret},
            authenticated=False,
        )
        api_key = body.get("apiKey") if isinstance(body, dict) else None
        if not api_key:
            raise PluggyAuthError("POST /auth respondeu sem apiKey.")
        self._redact.add(api_key)
        self._api_key = api_key

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if self._api_key is None:
            self.authenticate()
        try:
            return self._send("GET", url, params=params)
        except PluggyAuthError as exc:
            if exc.status != 401:
                raise
            log.info("apiKey recusado (401); renovando a autenticação uma vez.")
            self.authenticate()
            return self._send("GET", url, params=params)

    def _get_paged(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = self._get(url, {**params, "page": page, "pageSize": PAGE_SIZE})
            results.extend(body.get("results") or [])
            if page >= int(body.get("totalPages") or 1):
                return results
        raise PluggyError(f"{_path(url)} passou de {MAX_PAGES} páginas; paginação interrompida.")

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        authenticated: bool = True,
    ) -> Any:
        headers = {"X-API-KEY": self._api_key} if authenticated and self._api_key else {}
        where = f"{method} {_path(url)}"
        for attempt in range(1, self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                response = self._http.request(method, url, params=params, json=json, headers=headers)
            except httpx.TransportError as exc:
                if last:
                    raise PluggyNetworkError(
                        self._redact(f"Falha de rede em {where} após {attempt} tentativas: {type(exc).__name__}.")
                    ) from None
                wait = self._backoff(attempt, None)
                log.warning("Falha de rede em %s (%s); nova tentativa em %.0fs.", where, type(exc).__name__, wait)
                self._sleep(wait)
                continue

            status = response.status_code
            if status == 429 or status >= 500:
                if last:
                    detail = self._redact(_error_detail(response))
                    if status == 429:
                        raise PluggyRateLimitError(
                            f"Limite de requisições da Pluggy excedido (HTTP 429) em {where} após {attempt} "
                            f"tentativas: {detail}",
                            status=status,
                        )
                    raise PluggyServerError(
                        f"Erro do servidor da Pluggy (HTTP {status}) em {where} após {attempt} tentativas: {detail}",
                        status=status,
                    )
                wait = self._backoff(attempt, response.headers.get("Retry-After"))
                log.warning(
                    "HTTP %s em %s; nova tentativa %s/%s em %.0fs.", status, where, attempt + 1, self._max_retries, wait
                )
                self._sleep(wait)
                continue

            if response.is_success:
                return response.json()

            detail = self._redact(_error_detail(response))
            code = _error_code(response)
            if status == 401:
                raise PluggyAuthError(
                    f"Autenticação recusada pela Pluggy (HTTP 401) em {where}: {detail}. Confira PLUGGY_CLIENT_ID e "
                    "PLUGGY_CLIENT_SECRET no arquivo de ambiente e se o plano/trial da aplicação continua ativo.",
                    status=status,
                    code=code,
                )
            if status == 403:
                raise PluggyAuthError(
                    f"Acesso negado pela Pluggy (HTTP 403) em {where}: {detail}. Possíveis causas: trial/plano "
                    "encerrado, IP fora da lista permitida ou item de outra aplicação.",
                    status=status,
                    code=code,
                )
            raise PluggyError(f"Erro da Pluggy (HTTP {status}) em {where}: {detail}", status=status, code=code)
        raise AssertionError("inalcançável")  # pragma: no cover

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._max_backoff)
            except ValueError:
                pass
        return min(self._backoff_base * (2 ** (attempt - 1)), self._max_backoff)


def _segment(value: str) -> str:
    return quote(value, safe="")


def _path(url: str) -> str:
    return url.split("?", 1)[0]


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        code = body.get("codeDescription") or body.get("code")
        return str(code) if code is not None else None
    return None


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "sem corpo")[:200]
    if isinstance(body, dict):
        parts = [str(body[key]) for key in ("code", "codeDescription", "message") if body.get(key)]
        return " | ".join(parts) or "sem detalhe"
    return str(body)[:200]
