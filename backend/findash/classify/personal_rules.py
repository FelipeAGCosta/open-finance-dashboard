"""Regras por contraparte criadas pela interface, gravadas em data/regras_pessoais.yaml (fora do Git).

O app só reescreve um bloco delimitado por comentários, logo depois de `regras:`; o resto do arquivo
(regras e comentários escritos à mão) fica intacto. O bloco vem PRIMEIRO na lista porque a escolha
mais recente do usuário precisa vencer regras antigas que casem a mesma contraparte.

Cada regra do bloco é identificada por (contraparte, sentido) e pode ter categoria, essencial e tipo:
    - contraparte: NOME DA CONTRAPARTE
      sentido: saida
      categoria: Mercado
      nome: criada pela interface
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from findash.classify.rules import PERSONAL_RULES_TEMPLATE, RulesError
from findash.classify.text import counterparty_key, normalize_counterparty

BLOCK_START = "# >>> regras criadas pela interface do app (o app reescreve só este bloco) >>>"
BLOCK_END = "# <<< fim das regras criadas pela interface <<<"
RULE_NAME = "criada pela interface"
FIELDS = ("categoria", "essencial", "tipo", "extraordinario")


def _key(name: str) -> str:
    return counterparty_key(normalize_counterparty(name))


def _split(text: str) -> tuple[list[str], list[str], int]:
    """(linhas fora do bloco, linhas do bloco, índice onde o bloco estava ou deve entrar)."""
    lines = text.splitlines()
    stripped = [line.strip() for line in lines]
    if BLOCK_START in stripped and BLOCK_END in stripped:
        start, end = stripped.index(BLOCK_START), stripped.index(BLOCK_END)
        if end < start:
            raise RulesError("regras_pessoais.yaml: marcadores do bloco da interface fora de ordem")
        return lines[:start] + lines[end + 1 :], lines[start + 1 : end], start
    return lines, [], -1


def _managed(block: list[str]) -> list[dict[str, Any]]:
    if not block:
        return []
    data = yaml.safe_load("regras:\n" + "\n".join(block)) or {}
    items = data.get("regras") or []
    return [item for item in items if isinstance(item, dict)]


def read_managed(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    _, block, _ = _split(path.read_text(encoding="utf-8"))
    return _managed(block)


def _render(items: list[dict[str, Any]], indent: int) -> list[str]:
    pad, inner = " " * indent, " " * (indent + 2)
    out = [pad + BLOCK_START]
    for item in items:
        out.append(f"{pad}- contraparte: {_scalar(item['contraparte'])}")
        out.append(f"{inner}sentido: {item['sentido']}")
        for field in FIELDS:
            if item.get(field) is not None:
                out.append(f"{inner}{field}: {_scalar(item[field])}")
        out.append(f"{inner}nome: {RULE_NAME}")
    out.append(pad + BLOCK_END)
    return out


def _scalar(value: Any) -> str:
    return yaml.safe_dump(value, allow_unicode=True, default_flow_style=True).strip().removesuffix("...").strip()


def _write(path: Path, items: list[dict[str, Any]]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else PERSONAL_RULES_TEMPLATE
    before = yaml.safe_load(text) or {}
    outside, _, _ = _split(text)
    header = next((i for i, line in enumerate(outside) if line.split("#", 1)[0].strip().startswith("regras:")), None)
    if header is None:
        outside.append("regras:")
        header = len(outside) - 1
    if outside[header].split("#", 1)[0].strip() == "regras: []":
        outside[header] = "regras:"
    elif outside[header].split("#", 1)[0].strip() != "regras:":
        raise RulesError("regras_pessoais.yaml: não sei inserir regras numa lista escrita em uma linha só")
    first_item = next((line for line in outside[header + 1 :] if line.lstrip().startswith("- ")), None)
    indent = len(first_item) - len(first_item.lstrip()) if first_item is not None else 2
    new_lines = outside[: header + 1] + (_render(items, indent) if items else []) + outside[header + 1 :]
    new_text = "\n".join(new_lines) + "\n"
    try:
        after = yaml.safe_load(new_text) or {}
    except yaml.YAMLError as exc:
        raise RulesError(f"regras_pessoais.yaml: a gravação deixaria o arquivo inválido ({exc})") from None
    # Garantia: as regras escritas à mão continuam iguais e o bloco é exatamente o pedido.
    hand_before = [r for r in (before.get("regras") or []) if not (isinstance(r, dict) and r.get("nome") == RULE_NAME)]
    hand_after = [r for r in (after.get("regras") or []) if not (isinstance(r, dict) and r.get("nome") == RULE_NAME)]
    if hand_before != hand_after or len(after.get("regras") or []) != len(hand_after) + len(items):
        raise RulesError("regras_pessoais.yaml: a gravação mudaria regras escritas à mão; nada foi salvo")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".yaml.tmp")
    temp.write_text(new_text, encoding="utf-8")
    os.replace(temp, path)


def counterparty_rule(path: Path, counterparty: str, direction: str) -> dict[str, Any] | None:
    key = _key(counterparty)
    return next(
        (
            dict(item)
            for item in read_managed(path)
            if _key(str(item.get("contraparte", ""))) == key and item.get("sentido") == direction
        ),
        None,
    )


def set_counterparty_rule(path: Path, counterparty: str, direction: str, **values: Any) -> dict[str, Any] | None:
    """Cria/atualiza a regra (contraparte, sentido) com os campos dados; devolve a regra anterior (desfazer).

    values: categoria, essencial, tipo, extraordinario (None remove o campo). Uma regra sem nenhum campo é apagada.
    """
    if direction not in ("saida", "entrada"):
        raise ValueError("sentido deve ser 'saida' ou 'entrada'")
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise ValueError(f"campos desconhecidos: {sorted(unknown)}")
    items = read_managed(path)
    key = _key(counterparty)
    index = next(
        (
            i
            for i, item in enumerate(items)
            if _key(str(item.get("contraparte", ""))) == key and item.get("sentido") == direction
        ),
        None,
    )
    previous = dict(items[index]) if index is not None else None
    item = dict(previous) if previous else {"contraparte": normalize_counterparty(counterparty), "sentido": direction}
    item.pop("nome", None)
    for field, value in values.items():
        if value is None:
            item.pop(field, None)
        else:
            item[field] = value
    has_fields = any(item.get(f) is not None for f in FIELDS)
    if index is not None:
        items.pop(index)
    if has_fields:
        items.insert(0, item)  # a mais recente primeiro
    _write(path, items)
    if previous:
        previous.pop("nome", None)
    return previous


def restore_counterparty_rule(path: Path, counterparty: str, direction: str, previous: dict[str, Any] | None) -> None:
    """Desfaz: volta a regra (contraparte, sentido) ao estado anterior (None = não existia)."""
    items = read_managed(path)
    key = _key(counterparty)
    items = [i for i in items if not (_key(str(i.get("contraparte", ""))) == key and i.get("sentido") == direction)]
    if previous:
        restored = {k: v for k, v in previous.items() if k != "nome"}
        items.insert(0, restored)
    _write(path, items)
