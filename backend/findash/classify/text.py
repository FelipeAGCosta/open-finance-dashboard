"""Normalização de texto e extração da contraparte de uma transação."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Sufixos societários removidos da contraparte (só no fim do nome).
_COMPANY_SUFFIXES = ("LTDA", "LIMITADA", "ME", "EPP", "EIRELI", "MEI", "SA", "S A", "S/A", "CIA", "EI")
_COMPANY_WORDS = {
    "LTDA",
    "EIRELI",
    "COMERCIO",
    "COMERCIAL",
    "SERVICOS",
    "SERVICO",
    "INDUSTRIA",
    "PARTICIPACOES",
    "PAGAMENTOS",
    "BANCO",
    "TECNOLOGIA",
    "DISTRIBUIDORA",
    "ATACADISTA",
    "RESTAURANTE",
    "CENTRO",
    "INSTITUTO",
    "ASSOCIACAO",
    "EMPREENDIMENTOS",
    "TRANSPORTES",
    "LOGISTICA",
    "CONSULTORIA",
    "AGENCIA",
    "OPERADORA",
    "FARMACIA",
    "DROGARIA",
    "SUPERMERCADO",
    "MERCADO",
    "LOJA",
    "LOJAS",
    "EDITORA",
    "HOTEL",
    "CLINICA",
    "SOCIEDADE",
    "FUNDACAO",
    "IGREJA",
    "CONDOMINIO",
    "COOPERATIVA",
    "SEGUROS",
    "INVESTIMENTOS",
    "CORRETORA",
    "SA",
    "ME",
    "EPP",
    "MEI",
    "INC",
    "LLC",
    "CO",
    "BRASIL",
    "GROUP",
    "GRUPO",
}
_INSTALLMENT_SUFFIX = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\s*$")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_text(text: str | None) -> str:
    """Maiúsculas, sem acentos; qualquer coisa que não seja letra/dígito vira espaço."""
    text = strip_accents(text or "").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", text)).strip()


def normalize_counterparty(text: str | None) -> str:
    """Contraparte normalizada: maiúsculas, sem acentos, sem '*', sem sufixos societários e sem 'n/N'."""
    raw = strip_accents(text or "").upper()
    raw = _INSTALLMENT_SUFFIX.sub("", raw.strip())
    name = normalize_text(raw)
    changed = True
    while changed and name:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            if name.endswith(" " + suffix) and len(name) > len(suffix) + 1:
                name = name[: -(len(suffix) + 1)].rstrip()
                changed = True
    return name


def counterparty_key(name: str | None) -> str:
    """Chave de agrupamento sem espaços: 'APPLE COM BILL' e 'APPLECOMBILL' viram a mesma."""
    return re.sub(r"[^A-Z0-9]", "", name or "")


def counterparty_side(tx_type: str | None) -> str:
    """Lado da contraparte em paymentData: o recebedor numa saída, o pagador numa entrada."""
    return "payer" if tx_type == "CREDIT" else "receiver"


def counterparty_document(payment_data: dict[str, Any] | None, tx_type: str | None) -> tuple[str | None, str | None]:
    """(tipo, só dígitos) do documento da contraparte, se a Pluggy informar."""
    participant = (payment_data or {}).get(counterparty_side(tx_type)) or {}
    document = participant.get("documentNumber")
    if isinstance(document, dict):
        digits = re.sub(r"\D", "", str(document.get("value") or ""))
        return (document.get("type") or None), (digits or None)
    if isinstance(document, str):
        digits = re.sub(r"\D", "", document)
        return ("CPF" if len(digits) == 11 else "CNPJ" if len(digits) == 14 else None), (digits or None)
    return None, None


def raw_counterparty(
    description: str | None,
    payment_data: dict[str, Any] | None,
    merchant_name: str | None,
    tx_type: str | None,
    account_type: str,
    embedded: str | None = None,
) -> str | None:
    """Texto da contraparte antes de normalizar.

    Conta corrente: a contraparte embutida na descrição, quando o perfil do banco sabe extraí-la
    (`embedded`); senão o nome em paymentData; senão o estabelecimento. Cartão: a própria descrição
    (é o nome do estabelecimento na fatura e é estável entre meses); o merchant só sem descrição.
    """
    description = (description or "").strip()
    if account_type == "BANK":
        if embedded:
            return embedded
        name = ((payment_data or {}).get(counterparty_side(tx_type)) or {}).get("name")
        return name or merchant_name or description or None
    return description or merchant_name or None


def looks_like_person(name: str) -> bool:
    """Heurística para quando não há CPF/CNPJ: 2 a 6 palavras só com letras e sem termos de empresa."""
    words = name.split()
    if not 2 <= len(words) <= 6:
        return False
    if any(not w.isalpha() for w in words):
        return False
    return not any(w in _COMPANY_WORDS for w in words)


def counterparty_kind(name: str | None, document_type: str | None, account_type: str) -> str | None:
    if document_type == "CPF":
        return "PF"
    if document_type == "CNPJ":
        return "PJ"
    if account_type == "CREDIT":
        return "PJ"  # compra no cartão: estabelecimento
    if name and looks_like_person(name):
        return "PF"
    return "PJ" if name else None
