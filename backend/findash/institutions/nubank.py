"""Perfil do Nubank, o primeiro exemplo de perfil de instituição."""

from __future__ import annotations

from findash.db.models import Investment
from findash.institutions.base import DescriptionPatterns, InstitutionProfile

# As Caixinhas chegam pela Pluggy como CDB/RDB emitido pela Nu Financeira.
_SAVINGS_BOX_SUBTYPES = ("CDB", "RDB")
_SAVINGS_BOX_ISSUER = "NU FINANCEIRA"


class NubankProfile(InstitutionProfile):
    key = "nubank"
    name = "Nubank"
    patterns = DescriptionPatterns(
        bill_payment_card=("PAGAMENTO RECEBIDO", "PAGAMENTO DE FATURA", "PAGAMENTO EM DIA"),
        investment_out=(
            "COMPRA DE RENDA VARIAVEL",
            "APLICACAO",
            "VALOR TRANSFERIDO PARA INVESTIMENTOS",
            "DINHEIRO GUARDADO",
            "VALOR GUARDADO",
            "GUARDADO NA CAIXINHA",
        ),
        investment_in=("RESGATE", "DINHEIRO RESGATADO", "VALOR RESGATADO", "DINHEIRO RETIRADO", "VALOR RETIRADO"),
        account_topup_from_card=("VALOR ADICIONADO NA CONTA POR CARTAO",),
    )
    app_groups = ("Caixinhas", "Bolsa de valores", "Tesouro Direto", "Outros")

    def counterparty_from_description(self, description: str) -> str | None:
        # Na conta corrente a descrição vem como "Tipo|NOME": "Transferência enviada pelo Pix|FULANO".
        if "|" not in description:
            return None
        return description.split("|", 1)[1].strip() or None

    def values_net_of_tax(self, investment: Investment) -> bool:
        return self.is_savings_box(investment)

    def app_group(self, investment: Investment) -> str:
        if self.is_savings_box(investment):
            return "Caixinhas"
        group = super().app_group(investment)
        return "Outros" if group == "Renda fixa" else group  # o app não tem um grupo para outros CDBs

    @staticmethod
    def is_savings_box(investment: Investment) -> bool:
        if investment.type != "FIXED_INCOME" or (investment.subtype or "").upper() not in _SAVINGS_BOX_SUBTYPES:
            return False
        return _SAVINGS_BOX_ISSUER in f"{investment.issuer or ''} {investment.name or ''}".upper()
