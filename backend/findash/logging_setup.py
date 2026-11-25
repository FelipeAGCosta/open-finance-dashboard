"""Logging em data/logs/ (um arquivo por mês) e no console, sempre com segredos mascarados."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from findash.security import REDACTOR, RedactingFormatter, Redactor

LOGGER_NAME = "findash"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(logs_dir: Path, *, console: bool = True, redactor: Redactor = REDACTOR) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"findash-{date.today():%Y-%m}.log"
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(RedactingFormatter(_FORMAT, redactor=redactor))
    logger.addHandler(file_handler)

    # Com pythonw (agendador), sys.stderr é None: só o arquivo recebe o log.
    if console and sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(RedactingFormatter("%(levelname)s: %(message)s", redactor=redactor))
        logger.addHandler(console_handler)
    return log_file
