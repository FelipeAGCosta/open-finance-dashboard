"""O que muda de um banco para outro, atrás de uma interface pequena.

O Open Finance padroniza os campos, mas não o texto livre: cada banco escreve as próprias descrições
("Pagamento de fatura", "Dinheiro guardado"...), agrupa os investimentos do seu jeito no app e pode mostrar
alguns produtos pelo valor líquido de IR. Um perfil guarda exatamente isso, e o resto do código continua
genérico. Para adicionar um banco: crie uma subclasse de `InstitutionProfile`, sobrescreva só o que
for diferente e registre o perfil em `findash/institutions/__init__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from findash.db.models import Investment


@dataclass(frozen=True)
class DescriptionPatterns:
    """Começos de descrição (normalizada: maiúsculas, sem acento) que identificam um movimento."""

    bill_payment_bank: tuple[str, ...] = ("PAGAMENTO DE FATURA", "PAGAMENTO FATURA")
    bill_payment_card: tuple[str, ...] = ("PAGAMENTO RECEBIDO", "PAGAMENTO DE FATURA")
    investment_out: tuple[str, ...] = ("APLICACAO", "COMPRA DE RENDA VARIAVEL")
    investment_in: tuple[str, ...] = ("RESGATE",)
    # Rendimento OU venda: quem decide é o cruzamento com as transações de investimento.
    investment_received: tuple[str, ...] = ("VALOR RECEBIDO DE INVESTIMENTO",)
    account_topup_from_card: tuple[str, ...] = ()
    refund_in_account: tuple[str, ...] = ("REEMBOLSO", "ESTORNO", "DEVOLUCAO")


class InstitutionProfile:
    key = "generic"
    name = "Banco"
    patterns = DescriptionPatterns()
    # Grupos da tela de investimentos do app do banco, para conferir os totais lado a lado.
    app_groups: tuple[str, ...] = ("Renda fixa", "Bolsa de valores", "Tesouro Direto", "Outros")

    def counterparty_from_description(self, description: str) -> str | None:
        """Contraparte embutida na descrição da conta corrente, quando o banco a coloca ali."""
        return None

    def values_net_of_tax(self, investment: Investment) -> bool:
        """True quando o app do banco mostra este produto pelo líquido de IR, e não pelo bruto."""
        return False

    def app_group(self, investment: Investment) -> str:
        if (investment.subtype or "").upper() == "TREASURY":
            return "Tesouro Direto"
        if investment.type in ("EQUITY", "ETF"):
            return "Bolsa de valores"
        if investment.type == "FIXED_INCOME":
            return "Renda fixa"
        return "Outros"
