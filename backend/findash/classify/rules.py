"""Carregamento e validação das regras em YAML (taxonomia, regras pessoais/base, MCC, Pluggy)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from findash.classify.text import counterparty_key, normalize_counterparty, normalize_text
from findash.db.models import MOVEMENT_TYPES

UNCLASSIFIED = "A classificar"
TRANSFER_TO_PEOPLE = "Transferências para pessoas"
PERSONAL_RULES_TEMPLATE = """\
# Suas regras PESSOAIS (fora do Git). Formato e exemplos fictícios em config/regras_pessoais.example.yaml.
# Elas vêm antes das regras base. Depois de editar, rode: findash classificar
regras: []
"""

_RULE_KEYS = {
    "contem",
    "contraparte",
    "exceto",
    "categoria",
    "essencial",
    "tipo",
    "sentido",
    "conta",
    "nome",
    "extraordinario",
}
_DIRECTIONS = {"saida": "out", "entrada": "in"}
_ACCOUNTS = {"corrente": "BANK", "cartao": "CREDIT"}


class RulesError(Exception):
    """Arquivo de regras inválido. A mensagem diz o arquivo e a regra."""


@dataclass(frozen=True)
class Rule:
    source: str  # "pessoal" | "base"
    index: int  # posição no arquivo (1 = primeira)
    patterns: tuple[str, ...]
    regexes: tuple[re.Pattern, ...] = field(repr=False)
    category: str | None
    essential: bool | None
    movement_type: str | None
    direction: str | None  # "in" | "out"
    account_type: str | None  # "BANK" | "CREDIT"
    name: str | None
    exclusions: tuple[re.Pattern, ...] = field(default=(), repr=False)
    counterparty: str | None = None  # 'contraparte': casa a contraparte inteira (chave sem espaços)
    counterparty_key: str | None = None
    extraordinary: bool | None = None  # 'extraordinario': gasto fora do dia a dia

    def matches(self, text: str, *, direction: str, account_type: str, key: str | None = None) -> str | None:
        """Devolve o padrão que casou (ou None)."""
        if self.direction and self.direction != direction:
            return None
        if self.account_type and self.account_type != account_type:
            return None
        if self.counterparty_key:
            return self.counterparty if key == self.counterparty_key else None
        if any(regex.search(text) for regex in self.exclusions):
            return None
        for pattern, regex in zip(self.patterns, self.regexes, strict=True):
            if regex.search(text):
                return pattern
        return None

    def describe(self, pattern: str) -> str:
        label = f" ({self.name})" if self.name else ""
        if self.counterparty_key:
            return f"{self.source} #{self.index}{label}: contraparte '{pattern}'"
        return f"{self.source} #{self.index}{label}: contém '{pattern}'"


@dataclass
class RuleBook:
    categories: dict[str, bool | None]  # nome -> essencial padrão
    personal: list[Rule]
    base: list[Rule]
    mcc: dict[int, str]
    pluggy: dict[str, str]

    def default_essential(self, category: str | None) -> bool | None:
        return self.categories.get(category) if category else None


def compile_pattern(pattern: str) -> re.Pattern:
    """Palavra/frase inteira sobre o texto normalizado; '*' no fim casa o começo da palavra."""
    prefix = pattern.endswith("*")
    core = normalize_text(pattern.rstrip("*"))
    if not core:
        raise ValueError("padrão vazio")
    body = r"\s+".join(re.escape(part) for part in core.split())
    tail = r"[A-Z0-9]*" if prefix else r"(?![A-Z0-9])"
    return re.compile(rf"(?<![A-Z0-9]){body}{tail}")


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise RulesError(f"arquivo de regras não encontrado: {path.name}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RulesError(f"{path.name}: YAML inválido: {exc}") from None


def load_categories(path: Path) -> dict[str, bool | None]:
    data = _read_yaml(path)
    categories: dict[str, bool | None] = {}
    for position, item in enumerate(data.get("categorias") or [], start=1):
        if not isinstance(item, dict) or not item.get("nome"):
            raise RulesError(f"{path.name}: categoria #{position} sem 'nome'")
        categories[str(item["nome"])] = item.get("essencial")
    for required in (UNCLASSIFIED, TRANSFER_TO_PEOPLE):
        if required not in categories:
            raise RulesError(f"{path.name}: a categoria obrigatória '{required}' não existe")
    return categories


CATEGORY_COLORS = 18  # cores fixas por categoria (1..18); 0 = neutra


def load_category_colors(path: Path) -> dict[str, int]:
    """Categoria -> índice da cor FIXA (campo 'cor' de categorias.yaml). Duas categorias não dividem cor."""
    data = _read_yaml(path)
    colors: dict[str, int] = {}
    for position, item in enumerate(data.get("categorias") or [], start=1):
        value = item.get("cor") if isinstance(item, dict) else None
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= CATEGORY_COLORS:
            raise RulesError(f"{path.name}: categoria #{position} precisa de 'cor' de 0 a {CATEGORY_COLORS}")
        if value and value in colors.values():
            raise RulesError(f"{path.name}: a cor {value} está repetida")
        colors[str(item["nome"])] = value
    return colors


def load_rules(path: Path, source: str, categories: dict[str, bool | None]) -> list[Rule]:
    if not path.exists():
        return []
    data = _read_yaml(path)
    items = data.get("regras") if isinstance(data, dict) else None
    if items is None:
        return []
    if not isinstance(items, list):
        raise RulesError(f"{path.name}: 'regras' deve ser uma lista")
    rules: list[Rule] = []
    for index, item in enumerate(items, start=1):
        where = f"{path.name}, regra #{index}"
        if not isinstance(item, dict):
            raise RulesError(f"{where}: cada regra é um bloco com 'contem' e 'categoria'/'tipo'")
        unknown = set(item) - _RULE_KEYS
        if unknown:
            raise RulesError(f"{where}: campo(s) desconhecido(s): {', '.join(sorted(unknown))}")
        counterparty = item.get("contraparte")
        if counterparty is not None and (
            not isinstance(counterparty, (str, int)) or not counterparty_key(normalize_counterparty(str(counterparty)))
        ):
            raise RulesError(f"{where}: 'contraparte' precisa ser o nome da contraparte")
        patterns = item.get("contem")
        if counterparty is not None and patterns is not None:
            raise RulesError(f"{where}: use 'contem' ou 'contraparte', não os dois")
        patterns = [patterns] if isinstance(patterns, (str, int)) else patterns
        if counterparty is None and (not patterns or not all(isinstance(p, (str, int)) for p in patterns)):
            raise RulesError(f"{where}: 'contem' precisa de um texto ou de uma lista de textos")
        patterns = [str(p) for p in patterns or []]
        category = item.get("categoria")
        movement_type = item.get("tipo")
        extraordinary = item.get("extraordinario")
        if extraordinary is not None and not isinstance(extraordinary, bool):
            raise RulesError(f"{where}: 'extraordinario' deve ser true ou false")
        if category is None and movement_type is None and extraordinary is None:
            raise RulesError(f"{where}: informe 'categoria', 'tipo' e/ou 'extraordinario'")
        if category is not None and category not in categories:
            raise RulesError(f"{where}: categoria '{category}' não existe em categorias.yaml")
        if movement_type is not None and movement_type not in MOVEMENT_TYPES:
            raise RulesError(f"{where}: tipo '{movement_type}' inválido (use: {', '.join(MOVEMENT_TYPES)})")
        essential = item.get("essencial")
        if essential is not None and not isinstance(essential, bool):
            raise RulesError(f"{where}: 'essencial' deve ser true ou false")
        direction = item.get("sentido")
        if direction is not None and direction not in _DIRECTIONS:
            raise RulesError(f"{where}: 'sentido' deve ser 'saida' ou 'entrada'")
        account = item.get("conta")
        if account is not None and account not in _ACCOUNTS:
            raise RulesError(f"{where}: 'conta' deve ser 'corrente' ou 'cartao'")
        exclusions = item.get("exceto") or []
        exclusions = [exclusions] if isinstance(exclusions, (str, int)) else exclusions
        if not isinstance(exclusions, list):
            raise RulesError(f"{where}: 'exceto' precisa de um texto ou de uma lista de textos")
        try:
            regexes = tuple(compile_pattern(p) for p in patterns)
            exclusion_regexes = tuple(compile_pattern(str(p)) for p in exclusions)
        except ValueError as exc:
            raise RulesError(f"{where}: {exc}") from None
        rules.append(
            Rule(
                source=source,
                index=index,
                patterns=tuple(patterns),
                regexes=regexes,
                category=category,
                essential=essential,
                movement_type=movement_type,
                direction=_DIRECTIONS.get(direction) if direction else None,
                account_type=_ACCOUNTS.get(account) if account else None,
                name=item.get("nome"),
                exclusions=exclusion_regexes,
                counterparty=normalize_counterparty(str(counterparty)) if counterparty is not None else None,
                counterparty_key=counterparty_key(normalize_counterparty(str(counterparty)))
                if counterparty is not None
                else None,
                extraordinary=extraordinary,
            )
        )
    return rules


def load_mcc(path: Path, categories: dict[str, bool | None]) -> dict[int, str]:
    data = _read_yaml(path)
    result: dict[int, str] = {}
    for key, category in (data.get("mcc") or {}).items():
        if category not in categories:
            raise RulesError(f"{path.name}: MCC {key}: categoria '{category}' não existe")
        text = str(key).strip()
        try:
            if "-" in text:
                start, end = (int(part) for part in text.split("-", 1))
                for code in range(start, end + 1):
                    result.setdefault(code, category)
            else:
                result[int(text)] = category
        except ValueError:
            raise RulesError(f"{path.name}: MCC inválido '{key}'") from None
    return result


def load_pluggy_map(path: Path, categories: dict[str, bool | None]) -> dict[str, str]:
    data = _read_yaml(path)
    result: dict[str, str] = {}
    for key, category in (data.get("pluggy") or {}).items():
        if category not in categories:
            raise RulesError(f"{path.name}: '{key}': categoria '{category}' não existe")
        result[str(key).strip().casefold()] = category
    return result


def ensure_personal_rules_file(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PERSONAL_RULES_TEMPLATE, encoding="utf-8")


def load_rulebook(config_dir: Path, personal_rules_path: Path) -> RuleBook:
    categories = load_categories(config_dir / "categorias.yaml")
    return RuleBook(
        categories=categories,
        personal=load_rules(personal_rules_path, "pessoal", categories),
        base=load_rules(config_dir / "regras_base.yaml", "base", categories),
        mcc=load_mcc(config_dir / "mcc.yaml", categories),
        pluggy=load_pluggy_map(config_dir / "categorias_pluggy.yaml", categories),
    )
