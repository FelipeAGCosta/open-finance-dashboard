"""Integração somente leitura com a API da Pluggy."""

from findash.pluggy.client import PluggyClient
from findash.pluggy.errors import (
    PluggyAuthError,
    PluggyError,
    PluggyNetworkError,
    PluggyRateLimitError,
    PluggyServerError,
)

__all__ = [
    "PluggyAuthError",
    "PluggyClient",
    "PluggyError",
    "PluggyNetworkError",
    "PluggyRateLimitError",
    "PluggyServerError",
]
