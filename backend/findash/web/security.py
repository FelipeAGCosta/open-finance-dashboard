"""Proteções do servidor local.

O servidor escuta só em 127.0.0.1, mas um site aberto no navegador ainda pode tentar falar com ele:
- DNS rebinding: um domínio externo que resolve para 127.0.0.1 chega com outro Host -> recusado;
- requisição de outra origem (CSRF) chega com Origin externo -> recusada.
Só Host/Origin com nome localhost ou 127.0.0.1 passam (qualquer porta: o Vite em desenvolvimento
usa outra porta).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

LOCAL_NAMES = {"127.0.0.1", "localhost"}


def _host_name(value: str) -> str:
    return (urlsplit(f"//{value}").hostname or "").lower()


def is_local_host(host: str | None) -> bool:
    return bool(host) and _host_name(host) in LOCAL_NAMES


def is_local_origin(origin: str | None) -> bool:
    if origin is None:
        return True  # navegação direta e chamadas sem Origin (mesma origem em GET)
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and (parts.hostname or "").lower() in LOCAL_NAMES


class LocalOnlyMiddleware:
    """Middleware ASGI: recusa (403) Host ou Origin que não sejam locais."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if not is_local_host(headers.get("host")) or not is_local_origin(headers.get("origin")):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = json.dumps({"detail": "Acesso permitido só a partir deste computador (localhost)."}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
