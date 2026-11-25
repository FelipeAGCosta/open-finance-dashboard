"""Mascaramento de segredos (client secret e apiKey) em logs, erros e JSONs."""

from __future__ import annotations

import logging
import threading

MASK = "[REDACTED]"
_MIN_SECRET_LENGTH = 6  # evita mascarar trechos curtos e comuns por engano


class Redactor:
    """Guarda os segredos conhecidos do processo e os substitui por MASK em qualquer texto."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def add(self, secret: str | None) -> None:
        if secret and len(secret) >= _MIN_SECRET_LENGTH:
            with self._lock:
                self._secrets.add(secret)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, MASK)
        return text


# Instância do processo, usada pelo logging e pelo cliente da Pluggy.
REDACTOR = Redactor()


class RedactingFormatter(logging.Formatter):
    """Mascara a linha inteira já formatada, incluindo tracebacks."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None, redactor: Redactor = REDACTOR):
        super().__init__(fmt, datefmt)
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        return self._redactor(super().format(record))
