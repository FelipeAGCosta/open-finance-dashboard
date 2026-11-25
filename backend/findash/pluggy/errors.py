"""Erros da integração com a Pluggy. As mensagens já chegam aqui com segredos mascarados."""

from __future__ import annotations


class PluggyError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class PluggyAuthError(PluggyError):
    """401/403: credenciais inválidas, apiKey expirado, trial/plano encerrado ou IP não autorizado."""


class PluggyRateLimitError(PluggyError):
    """429 persistente depois de todas as tentativas."""


class PluggyServerError(PluggyError):
    """5xx persistente depois de todas as tentativas."""


class PluggyNetworkError(PluggyError):
    """Falha de rede (DNS, conexão, timeout) depois de todas as tentativas."""
