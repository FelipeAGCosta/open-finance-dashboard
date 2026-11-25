"""Classe de cada ativo (Tesouro, CDB/RDB, Ações, FIIs, BDR, ETF Brasil, ETF Global, Outros).

Ordem: correção manual por ticker (data/classes_ativos.yaml, fora do Git) > subtipo da Pluggy
(config/classes_ativos.yaml) > "Outros". ETF é dividido em "ETF Brasil" e "ETF Global" (a Pluggy
não informa a região; ETF sem região conta como "ETF Brasil" e "ETF" escrito à mão também).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

OTHER = "Outros"
CLASS_ORDER = ("Tesouro", "CDB/RDB", "Ações", "FIIs", "BDR", "ETF Brasil", "ETF Global", OTHER)
FIXED_INCOME_CLASSES = ("Tesouro", "CDB/RDB")
ETF_CLASSES = ("ETF Brasil", "ETF Global")
INDIVIDUAL_CLASSES = ("Ações", "FIIs", "BDR")  # ativos individuais: "manter, sem novos aportes" no Plano
ALIASES = {"ETF": "ETF Brasil"}
PERSONAL_TEMPLATE = """\
# Correção manual da classe de ativos por ticker (fora do Git). Vence o subtipo informado pela Pluggy.
# Classes válidas: Tesouro, CDB/RDB, Ações, FIIs, BDR, ETF Brasil, ETF Global, Outros.
# Depois de editar, rode: findash carteira
tickers:
#  ABCD11: ETF Global
"""


class ClassesError(Exception):
    """Arquivo de classes inválido."""


@dataclass
class ClassMap:
    subtypes: dict[str, str]
    tickers: dict[str, str] = field(default_factory=dict)

    def classify(self, code: str | None, subtype: str | None) -> tuple[str, str]:
        """(classe, origem da decisão)."""
        ticker = (code or "").strip().upper()
        if ticker and ticker in self.tickers:
            return self.tickers[ticker], "correção manual"
        if subtype and subtype.upper() in self.subtypes:
            return self.subtypes[subtype.upper()], f"subtipo da Pluggy {subtype}"
        return OTHER, f"subtipo da Pluggy {subtype or '—'} sem mapa"


def ensure_personal_file(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PERSONAL_TEMPLATE, encoding="utf-8")


def load_class_map(config_dir: Path, personal_path: Path | None) -> ClassMap:
    base = _read(config_dir / "classes_ativos.yaml")
    subtypes = {
        str(k).upper(): _valid(v, "config/classes_ativos.yaml") for k, v in (base.get("subtipos") or {}).items()
    }
    tickers: dict[str, str] = {}
    if personal_path is not None and personal_path.exists():
        personal = _read(personal_path)
        tickers = {
            str(k).strip().upper(): _valid(v, str(personal_path.name))
            for k, v in (personal.get("tickers") or {}).items()
        }
    return ClassMap(subtypes, tickers)


def _read(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ClassesError(f"{path.name}: YAML inválido ({exc})") from None
    if not isinstance(data, dict):
        raise ClassesError(f"{path.name}: esperado um mapa no topo do arquivo")
    return data


def _valid(value: object, source: str) -> str:
    text = str(value).strip()
    text = ALIASES.get(text, text)
    if text not in CLASS_ORDER:
        raise ClassesError(f"{source}: classe '{text}' inválida. Opções: {', '.join(CLASS_ORDER)}")
    return text
