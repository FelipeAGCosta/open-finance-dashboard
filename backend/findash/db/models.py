"""Modelos do banco local.

Convenções:
- Valores monetários em centavos inteiros (`*_cents`): exatos e somáveis em SQL. O valor
  exatamente como veio da API continua em `raw_json`.
- Quantidades e preços unitários em Numeric (podem ter muitas casas decimais).
- DateTime sempre em UTC sem tzinfo; colunas Date (`date`, `snapshot_date`...) no horário de Brasília.
- Nada é apagado: transações que somem da API mudam de `state`; o histórico fora da
  janela de 12 meses da Pluggy permanece.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from findash.db.base import Base

QUANTITY = Numeric(28, 10)

# Estados de uma transação no banco local.
STATE_ACTIVE = "ativa"
STATE_REPLACED = "substituida"  # PENDING que sumiu e foi confirmada com outro id
STATE_REMOVED = "removida"  # PENDING que sumiu sem substituta (cancelada/estornada)
TRANSACTION_STATES = (STATE_ACTIVE, STATE_REPLACED, STATE_REMOVED)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # id da Pluggy
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    institution: Mapped[str] = mapped_column(String(32), default="generic")  # perfil em findash/institutions
    type: Mapped[str] = mapped_column(String(16))  # BANK | CREDIT
    subtype: Mapped[str | None] = mapped_column(String(32))  # CHECKING_ACCOUNT | CREDIT_CARD | ...
    name: Mapped[str | None] = mapped_column(String(200))
    marketing_name: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[str | None] = mapped_column(String(64))  # dado sensível: nunca exibir
    currency_code: Mapped[str | None] = mapped_column(String(8))
    balance_cents: Mapped[int | None] = mapped_column(BigInteger)  # cartão: valor da fatura em aberto
    credit_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    available_credit_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    raw_json: Mapped[str] = mapped_column(Text)
    pluggy_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("state IN ('ativa', 'substituida', 'removida')", name="state_valido"),
        Index("ix_transactions_account_date", "account_id", "date"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # id da Pluggy
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    date: Mapped[dt.date] = mapped_column(Date, index=True)  # data local (Brasília)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime)  # data/hora da API, em UTC
    description: Mapped[str | None] = mapped_column(Text)
    description_raw: Mapped[str | None] = mapped_column(Text)
    amount_original_cents: Mapped[int] = mapped_column(BigInteger)  # como veio da API, na moeda currency_code
    currency_code: Mapped[str | None] = mapped_column(String(8))
    amount_in_account_currency_cents: Mapped[int | None] = mapped_column(BigInteger)
    # Convenção única, em moeda da conta: NEGATIVO = dinheiro saindo/compra; POSITIVO = entrada.
    amount_normalized_cents: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str | None] = mapped_column(String(8))  # DEBIT | CREDIT
    status: Mapped[str] = mapped_column(String(16), index=True)  # PENDING | POSTED
    operation_type: Mapped[str | None] = mapped_column(String(64))
    merchant_name: Mapped[str | None] = mapped_column(String(200))
    merchant_cnpj: Mapped[str | None] = mapped_column(String(32))
    merchant_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payment_data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    mcc: Mapped[int | None] = mapped_column(Integer)
    installment_number: Mapped[int | None] = mapped_column(Integer)
    total_installments: Mapped[int | None] = mapped_column(Integer)
    bill_id: Mapped[str | None] = mapped_column(String(64))
    purchase_date: Mapped[dt.date | None] = mapped_column(Date)
    category_pluggy: Mapped[str | None] = mapped_column(String(120))
    category_id_pluggy: Mapped[str | None] = mapped_column(String(32))
    raw_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default=STATE_ACTIVE, index=True)
    replaced_by_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"))
    state_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    pluggy_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    pluggy_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)


class Investment(Base):
    """Dados fixos do ativo. Valores que mudam todo dia ficam em InvestmentSnapshot."""

    __tablename__ = "investments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # id da Pluggy
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    institution: Mapped[str] = mapped_column(String(32), default="generic")
    name: Mapped[str | None] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(64))  # ticker / CNPJ do fundo
    isin: Mapped[str | None] = mapped_column(String(16))
    type: Mapped[str | None] = mapped_column(String(32))
    subtype: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    currency_code: Mapped[str | None] = mapped_column(String(8))
    issuer: Mapped[str | None] = mapped_column(String(200))
    issuer_cnpj: Mapped[str | None] = mapped_column(String(32))
    purchase_date: Mapped[dt.date | None] = mapped_column(Date)
    issue_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    rate: Mapped[Decimal | None] = mapped_column(QUANTITY)
    rate_type: Mapped[str | None] = mapped_column(String(32))
    fixed_annual_rate: Mapped[Decimal | None] = mapped_column(QUANTITY)
    raw_json: Mapped[str] = mapped_column(Text)
    pluggy_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)


class InvestmentSnapshot(Base):
    """Foto diária da carteira: uma linha por (data, investimento)."""

    __tablename__ = "investment_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", "investment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[dt.date] = mapped_column(Date, index=True)  # data local da sincronização
    investment_id: Mapped[str] = mapped_column(ForeignKey("investments.id"), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    unit_value: Mapped[Decimal | None] = mapped_column(QUANTITY)  # preço da cota/ação em value_date
    balance_cents: Mapped[int | None] = mapped_column(BigInteger)  # saldo líquido
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)  # saldo bruto
    amount_original_cents: Mapped[int | None] = mapped_column(BigInteger)
    amount_profit_cents: Mapped[int | None] = mapped_column(BigInteger)
    amount_withdrawal_cents: Mapped[int | None] = mapped_column(BigInteger)
    value_date: Mapped[dt.date | None] = mapped_column(Date)  # data da cotação informada pela Pluggy
    status: Mapped[str | None] = mapped_column(String(32))
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime)  # última gravação da foto do dia


class InvestmentTransaction(Base):
    __tablename__ = "investment_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # id da Pluggy
    investment_id: Mapped[str] = mapped_column(ForeignKey("investments.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    trade_date: Mapped[dt.date | None] = mapped_column(Date)
    type: Mapped[str | None] = mapped_column(String(16))  # BUY | SELL | INTEREST | TAX | ...
    movement_type: Mapped[str | None] = mapped_column(String(16))
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    unit_value: Mapped[Decimal | None] = mapped_column(QUANTITY)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    net_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime)


class AccountSnapshot(Base):
    """Foto diária de cada conta: saldo da conta corrente; fatura em aberto e limites do cartão."""

    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", "account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[dt.date] = mapped_column(Date, index=True)  # data local da sincronização
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    balance_cents: Mapped[int | None] = mapped_column(BigInteger)  # cartão: fatura em aberto
    credit_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    available_credit_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime)


# Camada derivada: transaction_classifications, transaction_links e redemption_origins são recalculadas do
# zero a cada `classificar`; recurring_rules e classification_overrides guardam decisões do usuário e
# sobrevivem aos recálculos.

# Estado de uma regra de recorrência (gasto fixo ou salário). 'automatico' segue a detecção; as
# escolhas manuais vencem o algoritmo e persistem (um 'manual_nao' nunca volta a ser aplicado).
RULE_AUTO, RULE_YES, RULE_NO = "automatico", "manual_sim", "manual_nao"
RULE_STATUSES = (RULE_AUTO, RULE_YES, RULE_NO)

MOVEMENT_TYPES = (
    "receita",
    "despesa",
    "pagamento_fatura",
    "transferencia_interna",
    "aporte",
    "resgate",
    "renda_investimento",
    "estorno",
    # escolhidos pelo usuário (ou por regra pessoal): ficam fora de receitas e despesas
    "reembolso",
    "emprestimo_concedido",
    "devolucao_emprestimo",
    "transferencia_propria",
)
# reembolso abate despesa; empréstimos e transferência própria são neutros (não mexem no resultado).
LOAN_OUT, LOAN_IN, REIMBURSEMENT, OWN_TRANSFER = (
    "emprestimo_concedido",
    "devolucao_emprestimo",
    "reembolso",
    "transferencia_propria",
)
MOVEMENT_CHECK = "movement_type IN (" + ", ".join(f"'{t}'" for t in MOVEMENT_TYPES) + ")"


class TransactionClassification(Base):
    __tablename__ = "transaction_classifications"
    __table_args__ = (CheckConstraint(MOVEMENT_CHECK, name="movement_type_valido"),)

    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    movement_type: Mapped[str] = mapped_column(String(32), index=True)
    movement_rule: Mapped[str] = mapped_column(Text)  # por que recebeu este tipo
    category: Mapped[str | None] = mapped_column(String(80), index=True)  # só despesas e estornos
    essential: Mapped[bool | None] = mapped_column(Boolean)
    rule_level: Mapped[str | None] = mapped_column(String(32))  # override|pessoal|base|pessoa_fisica|mcc|pluggy|...
    rule_detail: Mapped[str | None] = mapped_column(Text)  # qual regra decidiu a categoria
    counterparty: Mapped[str | None] = mapped_column(String(200))  # normalizada, para exibição
    counterparty_key: Mapped[str | None] = mapped_column(String(200), index=True)  # sem espaços: agrupa variações
    counterparty_kind: Mapped[str | None] = mapped_column(String(4))  # PF | PJ
    recurring_rule_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_rules.id"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # override da transação > regra > variável
    extraordinary: Mapped[bool] = mapped_column(Boolean, default=False)  # gasto fora do dia a dia
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime)


class TransactionLink(Base):
    """Vínculos derivados: pagamento de fatura (conta↔cartão), estorno→compra, crédito↔investimento."""

    __tablename__ = "transaction_links"
    __table_args__ = (UniqueConstraint("kind", "transaction_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))  # pagamento_fatura | estorno | investimento
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    other_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    investment_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("investment_transactions.id"))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)


class RecurringRule(Base):
    """Gasto fixo ou salário detectado. O status escolhido pelo usuário persiste entre recálculos."""

    __tablename__ = "recurring_rules"
    __table_args__ = (
        UniqueConstraint("kind", "counterparty_key"),
        CheckConstraint("status IN ('automatico', 'manual_sim', 'manual_nao')", name="status_valido"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # fixo | salario
    counterparty_key: Mapped[str] = mapped_column(String(200))
    counterparty: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default=RULE_AUTO)
    avg_monthly_cents: Mapped[int | None] = mapped_column(BigInteger)
    months_count: Mapped[int | None] = mapped_column(Integer)
    median_interval_days: Mapped[int | None] = mapped_column(Integer)
    amount_variation: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    first_date: Mapped[dt.date | None] = mapped_column(Date)
    last_date: Mapped[dt.date | None] = mapped_column(Date)
    payment_interval_days: Mapped[int | None] = mapped_column(Integer)  # mediana entre pagamentos consecutivos
    # Salário que segue a agenda configurada (settings.yaml): valor de cada pagamento e a agenda em si.
    paycheck_cents: Mapped[int | None] = mapped_column(BigInteger)
    pay_frequency: Mapped[str | None] = mapped_column(String(16))  # weekly | biweekly | monthly
    payday: Mapped[int | None] = mapped_column(Integer)  # dia da semana (0 = segunda) ou dia do mês
    grace_days: Mapped[int | None] = mapped_column(Integer)
    detected: Mapped[bool] = mapped_column(Boolean, default=True)  # apareceu no último recálculo
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime)
    status_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class ClassificationOverride(Base):
    """Correção manual de uma transação específica. Vence todas as regras."""

    __tablename__ = "classification_overrides"

    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    movement_type: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(80))
    essential: Mapped[bool | None] = mapped_column(Boolean)
    fixed: Mapped[bool | None] = mapped_column(Boolean)  # fixo sim/não só nesta transação (None = segue a regra)
    extraordinary: Mapped[bool | None] = mapped_column(Boolean)  # extraordinário sim/não só nesta transação
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime)


class RedemptionOrigin(Base):
    """Derivada (recalculada a cada `classificar`): de qual ativo veio cada crédito de resgate/venda na conta.

    source = 'foto' (queda de quantidade/saldo entre fotos diárias) ou 'transacao' (SELL/AMORTIZATION
    em investment_transactions). Um crédito pode ter várias linhas (vários ativos/vendas somados).
    """

    __tablename__ = "redemption_origins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # foto | transacao
    investment_id: Mapped[str | None] = mapped_column(ForeignKey("investments.id"), index=True)
    investment_transaction_id: Mapped[str | None] = mapped_column(ForeignKey("investment_transactions.id"))
    event_date: Mapped[dt.date] = mapped_column(Date)  # data da foto com a queda, ou da venda
    gross_cents: Mapped[int] = mapped_column(BigInteger)
    net_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)


class MarketSeries(Base):
    """Cache local de séries públicas do Banco Central (SGS): CDI diário (% a.d.) e IPCA mensal (% a.m.)."""

    __tablename__ = "market_series"

    series_code: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)  # IPCA: primeiro dia do mês
    value: Mapped[Decimal] = mapped_column(Numeric(20, 10))  # em %, como o SGS publica
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime)


# Onde cada investimento conta no Plano: Reserva de emergência ou Patrimônio.
PLACE_RESERVE, PLACE_PATRIMONY = "reserva", "patrimonio"
PLACES = (PLACE_RESERVE, PLACE_PATRIMONY)


class PlanSetting(Base):
    """Metas da tela Plano com histórico de vigência.

    Cada gravação é uma linha nova: o valor de uma chave num mês M é o da linha mais recente com
    effective_month <= M. Assim uma mudança vale do mês escolhido em diante e os meses passados
    mantêm a meta da época. Desfazer = apagar a linha recém-criada.
    """

    __tablename__ = "plan_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(40), index=True)
    effective_month: Mapped[str] = mapped_column(String(7))  # AAAA-MM
    value_json: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)


class InvestmentPlace(Base):
    """Lugar escolhido manualmente para um investimento (vence a distribuição automática)."""

    __tablename__ = "investment_places"
    __table_args__ = (CheckConstraint("place IN ('reserva', 'patrimonio')", name="place_valido"),)

    investment_id: Mapped[str] = mapped_column(ForeignKey("investments.id"), primary_key=True)
    place: Mapped[str] = mapped_column(String(12))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime)


class ItemStatus(Base):
    __tablename__ = "item_status"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connector_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(32))
    execution_status: Mapped[str | None] = mapped_column(String(64))
    pluggy_last_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    next_auto_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    consent_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))  # running | success | error
    full_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    accounts_seen: Mapped[int] = mapped_column(Integer, default=0)
    transactions_new: Mapped[int] = mapped_column(Integer, default=0)
    transactions_updated: Mapped[int] = mapped_column(Integer, default=0)
    transactions_replaced: Mapped[int] = mapped_column(Integer, default=0)
    transactions_removed: Mapped[int] = mapped_column(Integer, default=0)
    investments_new: Mapped[int] = mapped_column(Integer, default=0)
    investments_updated: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_updated: Mapped[int] = mapped_column(Integer, default=0)
    investment_transactions_new: Mapped[int] = mapped_column(Integer, default=0)
    investment_transactions_updated: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)  # sempre mascarada
