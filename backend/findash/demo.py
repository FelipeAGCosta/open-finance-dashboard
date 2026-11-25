"""Banco de demonstração com dados 100% sintéticos.

`findash demo` recria este banco em data/demo/ e abre o app com ele. Cenário inventado: uma pessoa com
salário mensal, aluguel e contas da casa, cartão de crédito (assinaturas, mercado, parcelados), Pix para
amigos, um empréstimo com devolução parcial, um gasto extraordinário e uma carteira diversificada com
fotos diárias, proventos, aportes, um resgate e uma venda. Nomes, valores e tickers são fictícios e nada
vem de um banco real nem da internet. A semente é fixa: com a mesma data de referência (`as_of`), o
resultado é sempre o mesmo, o que deixa os screenshots reproduzíveis.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from findash.classify.commands import run_classification
from findash.config import Paths, local_date, utcnow
from findash.db.base import make_engine, make_session_factory
from findash.db.migrate import upgrade_to_head
from findash.db.models import (
    Account,
    AccountSnapshot,
    ClassificationOverride,
    Investment,
    InvestmentSnapshot,
    InvestmentTransaction,
    ItemStatus,
    MarketSeries,
    PlanSetting,
    SyncRun,
    Transaction,
)
from findash.invest.market import CDI, IPCA

SEED = 4242
HISTORY_MONTHS = 14
SNAPSHOT_DAYS = 180
ITEM = "demo-item"
INSTITUTION = "generic"
CHECKING, CARD = "demo-checking", "demo-card"
OWNER = "PESSOA DEMONSTRACAO"
EMPLOYER = "TECNOVA SISTEMAS LTDA"
SALARY_CENTS = 900_000
CARD_LIMIT_CENTS = 800_000
STARTING_BALANCE_CENTS = 300_000

FRIENDS = ("CAMILA ROCHA", "DIEGO MATOS", "PAULA NUNES", "VITOR SALES")
BORROWER = "RENATO FARIAS"

SETTINGS = """\
# Preferências da DEMONSTRAÇÃO (geradas por findash demo).
salario:
  frequencia: mensal
  dia: 5
  tolerancia_dias: 3
"""

RULES = """\
# Regras da DEMONSTRAÇÃO: contrapartes inventadas que as regras base não conhecem.
regras:
  - contem: [ADMINISTRADORA LAR DOCE, CONDOMINIO RESIDENCIAL DEMO]
    categoria: Moradia
  - contem: [COMPANHIA DE ENERGIA DEMO, FIBRANET DEMO, TELEFONIA DEMO]
    categoria: Contas da casa
  - contem: [PLANO DE SAUDE VIDA DEMO]
    categoria: Saúde e farmácia
  - contem: [CINEMAX PLAY, MUSICAPLAY, NUVEM ARQUIVOS, REVISTA SEMANAL DIGITAL]
    categoria: Assinaturas e serviços digitais
  - contem: [LOJA INFOTEC]
    categoria: Compras e eletrônicos
  - contem: [AUTO CENTER DEMO]
    categoria: Transporte
"""

CLASSES = """\
# Classes da DEMONSTRAÇÃO (tickers fictícios).
tickers:
  MUND11: ETF Global
  IBXX11: ETF Brasil
"""


@dataclass
class Asset:
    code: str | None
    name: str
    kind: str
    subtype: str
    quantity: Decimal
    price: Decimal
    daily_drift: float
    daily_volatility: float
    shares_per_month: Decimal = Decimal(0)  # compra no dia 15
    monthly_income_per_share: Decimal = Decimal(0)  # provento pago no dia 14
    rate: tuple[Decimal, str] | None = None  # renda fixa: (taxa, indexador)
    deposit: tuple[int, int, int, str] | None = None  # (centavos, dia, a cada N meses, descrição na conta)


PORTFOLIO = (
    Asset(
        None,
        "Tesouro Selic 2030",
        "FIXED_INCOME",
        "TREASURY",
        Decimal("0.65"),
        Decimal("15210"),
        0.00048,
        0.00002,
        rate=(Decimal("0.05"), "SELIC"),
        deposit=(90_000, 7, 1, "Aplicação Tesouro Direto"),
    ),
    Asset(
        None,
        "Tesouro IPCA+ 2035",
        "FIXED_INCOME",
        "TREASURY",
        Decimal("1.8"),
        Decimal("2410"),
        0.00035,
        0.0009,
        rate=(Decimal("6.2"), "IPCA"),
    ),
    Asset(
        None,
        "CDB Banco Demo 110% CDI",
        "FIXED_INCOME",
        "CDB",
        Decimal("900000"),
        Decimal("0.0102"),
        0.00052,
        0.0,
        rate=(Decimal("110"), "CDI"),
        deposit=(70_000, 22, 1, "Aplicação CDB Banco Demo"),
    ),
    Asset("ORBI3", "ORBI3", "EQUITY", "STOCK", Decimal(60), Decimal("27.40"), 0.0006, 0.017, Decimal(3)),
    Asset("TERA3", "TERA3", "EQUITY", "STOCK", Decimal(35), Decimal("41.80"), 0.0004, 0.014, Decimal(2)),
    Asset("PRIS4", "PRIS4", "EQUITY", "STOCK", Decimal(80), Decimal("12.15"), 0.0002, 0.021),
    Asset("KORA3", "KORA3", "EQUITY", "STOCK", Decimal(45), Decimal("19.90"), -0.0001, 0.018),
    Asset(
        "ARMZ11",
        "ARMZ11",
        "EQUITY",
        "REAL_ESTATE_FUND",
        Decimal(28),
        Decimal("101.20"),
        0.0002,
        0.006,
        Decimal(1),
        Decimal("0.86"),
    ),
    Asset(
        "OFCX11",
        "OFCX11",
        "EQUITY",
        "REAL_ESTATE_FUND",
        Decimal(40),
        Decimal("78.30"),
        0.0001,
        0.007,
        Decimal(0),
        Decimal("0.64"),
    ),
    Asset(
        "PAPL11",
        "PAPL11",
        "EQUITY",
        "REAL_ESTATE_FUND",
        Decimal(95),
        Decimal("9.72"),
        0.0001,
        0.004,
        Decimal(0),
        Decimal("0.11"),
    ),
    Asset("MUND11", "MUND11", "ETF", "ETF", Decimal(22), Decimal("118.40"), 0.0005, 0.010, Decimal(2)),
    Asset("IBXX11", "IBXX11", "ETF", "ETF", Decimal(30), Decimal("103.60"), 0.0003, 0.012, Decimal(1)),
    Asset("NEBU34", "NEBU34", "EQUITY", "BDR", Decimal(14), Decimal("63.50"), 0.0008, 0.022),
)


def _month_start(day: date, offset: int = 0) -> date:
    index = day.year * 12 + day.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _on_day(month: date, day: int) -> date:
    last = (_month_start(month, 1) - timedelta(days=1)).day
    return month.replace(day=min(day, last))


def _next_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _add_business_days(day: date, count: int) -> date:
    step = 1 if count >= 0 else -1
    while count:
        day += timedelta(days=step)
        if day.weekday() < 5:
            count -= step
    return day


def _company(name: str) -> dict:
    return {"name": name, "documentNumber": {"type": "CNPJ", "value": "00.000.000/0001-91"}}


def _person(name: str) -> dict:
    return {"name": name, "documentNumber": {"type": "CPF", "value": "000.000.000-00"}}


class _Builder:
    """Acumula as transações do cenário e o movimento diário da conta corrente."""

    def __init__(self, session: Session, as_of: date, now: datetime, rng: random.Random):
        self.session, self.as_of, self.now, self.rng = session, as_of, now, rng
        self.start = _month_start(as_of, -(HISTORY_MONTHS - 1))
        self.sequence = 0
        self.card_spent_by_month: dict[str, int] = {}
        self.checking_moves: dict[date, int] = {}
        self.overrides: list[tuple[str, dict]] = []

    def next_id(self, prefix: str) -> str:
        self.sequence += 1
        return f"demo-{prefix}-{self.sequence:05d}"

    def amount(self, low: float, high: float) -> int:
        return round(self.rng.uniform(low, high) * 100)

    def tx(
        self,
        account: str,
        day: date,
        cents: int,
        description: str,
        *,
        payer: dict | None = None,
        receiver: dict | None = None,
        mcc: int | None = None,
        installment: tuple[int, int] | None = None,
        purchase_date: date | None = None,
        override: dict | None = None,
    ) -> str | None:
        """cents: negativo = saída ou compra, positivo = entrada (a convenção do banco local)."""
        if not self.start <= day <= self.as_of:
            return None
        tx_id = self.next_id("tx")
        if override:
            self.overrides.append((tx_id, override))
        if account == CARD and cents < 0:
            month = f"{day:%Y-%m}"
            self.card_spent_by_month[month] = self.card_spent_by_month.get(month, 0) - cents
        if account == CHECKING:
            self.checking_moves[day] = self.checking_moves.get(day, 0) + cents
        payment_data = {"payer": payer} if payer else {"receiver": receiver} if receiver else None
        moment = datetime(day.year, day.month, day.day, 11) + timedelta(minutes=self.rng.randint(0, 540))
        self.session.add(
            Transaction(
                id=tx_id,
                account_id=account,
                date=day,
                occurred_at=moment + timedelta(hours=3),
                description=description,
                amount_original_cents=cents if account == CHECKING else -cents,
                currency_code="BRL",
                amount_normalized_cents=cents,
                type="CREDIT" if cents > 0 else "DEBIT",
                status="POSTED",
                mcc=mcc,
                payment_data_json=payment_data,
                installment_number=installment[0] if installment else None,
                total_installments=installment[1] if installment else None,
                purchase_date=purchase_date,
                raw_json=json.dumps({"id": tx_id, "description": description, "synthetic": True}),
                first_seen_at=self.now,
                last_seen_at=self.now,
            )
        )
        return tx_id

    def months(self):
        month = self.start
        while month <= self.as_of:
            yield month
            month = _month_start(month, 1)


def _accounts(b: _Builder) -> None:
    for account_id, kind, subtype, name in (
        (CHECKING, "BANK", "CHECKING_ACCOUNT", "Conta Demo"),
        (CARD, "CREDIT", "CREDIT_CARD", "Cartão Demo"),
    ):
        b.session.add(
            Account(
                id=account_id,
                item_id=ITEM,
                institution=INSTITUTION,
                type=kind,
                subtype=subtype,
                name=name,
                currency_code="BRL",
                credit_limit_cents=CARD_LIMIT_CENTS if kind == "CREDIT" else None,
                raw_json=json.dumps({"owner": OWNER, "synthetic": True}),
                first_seen_at=b.now,
                last_seen_at=b.now,
            )
        )
    b.session.flush()


def _income(b: _Builder) -> None:
    for month in b.months():
        payday = _next_business_day(_on_day(month, 5))
        b.tx(CHECKING, payday, SALARY_CENTS, "Transferência recebida", payer=_company(EMPLOYER))
        if b.rng.random() < 0.25:
            b.tx(
                CHECKING,
                _on_day(month, b.rng.randint(18, 26)),
                b.amount(600, 1400),
                "Transferência recebida",
                payer=_company("ESTUDIO CRIATIVO PIXEL ME"),
            )


def _household(b: _Builder) -> None:
    for month in b.months():
        b.tx(CHECKING, _on_day(month, 8), -195_000, "Pix enviado", receiver=_company("ADMINISTRADORA LAR DOCE LTDA"))
        b.tx(
            CHECKING,
            _on_day(month, 10),
            -b.amount(455, 490),
            "Pagamento de boleto",
            receiver=_company("CONDOMINIO RESIDENCIAL DEMO"),
        )
        b.tx(
            CHECKING,
            _on_day(month, 14),
            -b.amount(118, 214),
            "Pagamento de boleto",
            receiver=_company("COMPANHIA DE ENERGIA DEMO SA"),
        )
        b.tx(CHECKING, _on_day(month, 16), -9_990, "Débito automático", receiver=_company("FIBRANET DEMO LTDA"))
        b.tx(CHECKING, _on_day(month, 20), -38_900, "Débito automático", receiver=_company("PLANO DE SAUDE VIDA DEMO"))


def _card(b: _Builder) -> None:
    rng = b.rng
    for month in b.months():
        b.tx(CARD, _on_day(month, 3), -4_990, "TELEFONIA DEMO", mcc=4814)
        b.tx(CARD, _on_day(month, 6), -12_990, "ACADEMIA FORCA TOTAL", mcc=7997)
        b.tx(CARD, _on_day(month, 9), -3_990, "CINEMAX PLAY", mcc=4899)
        b.tx(CARD, _on_day(month, 11), -2_190, "MUSICAPLAY", mcc=5815)
        b.tx(CARD, _on_day(month, 13), -1_090, "NUVEM ARQUIVOS", mcc=5817)
        for _ in range(rng.randint(4, 6)):
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(85, 380), "SUPERMERCADO ECONOMIA", mcc=5411)
        for _ in range(rng.randint(6, 10)):
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(7, 34), "PADARIA TRIGO BOM", mcc=5462)
        for _ in range(rng.randint(2, 4)):
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(48, 165), "RESTAURANTE BOA MESA", mcc=5812)
        for _ in range(rng.randint(2, 4)):
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(32, 88), "DELIVERY RAPIDO", mcc=5814)
        for _ in range(2):
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(170, 245), "POSTO RODOVIA AZUL", mcc=5541)
        if rng.random() < 0.7:
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(28, 140), "FARMACIA SAUDE MAIS", mcc=5912)
        if rng.random() < 0.5:
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(38, 96), "CINEMA ESTRELA", mcc=7832)
        if rng.random() < 0.3:
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(110, 340), "MODA URBANA", mcc=5651)
        if rng.random() < 0.4:
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(45, 120), "LIVRARIA PAGINA", mcc=5942)
        if rng.random() < 0.8:  # estabelecimento que nenhuma regra conhece: fica "A classificar"
            b.tx(CARD, _on_day(month, rng.randint(1, 28)), -b.amount(20, 150), "ZX COMERCIO DIGITAL")

    # assinatura cancelada há 3 meses: aparece como fixo inativo
    for back in range(7, 2, -1):
        b.tx(CARD, _on_day(_month_start(b.as_of, -back), 19), -1_990, "REVISTA SEMANAL DIGITAL", mcc=5815)

    # parcelados: notebook em 10x e uma viagem em 3x (a viagem é um gasto extraordinário)
    notebook = _on_day(_month_start(b.as_of, -6), 21)
    for n in range(10):
        b.tx(
            CARD,
            _on_day(_month_start(notebook, n), 21),
            -42_990,
            f"LOJA INFOTEC {n + 1}/10",
            mcc=5732,
            installment=(n + 1, 10),
            purchase_date=notebook,
        )
    trip = _on_day(_month_start(b.as_of, -2), 2)
    for n in range(3):
        b.tx(
            CARD,
            _on_day(_month_start(trip, n), 2),
            -61_000,
            f"POUSADA VENTO SUL {n + 1}/3",
            mcc=7011,
            installment=(n + 1, 3),
            purchase_date=trip,
            override={"extraordinary": True},
        )


def _people(b: _Builder) -> None:
    rng = b.rng
    for month in b.months():
        for _ in range(rng.randint(1, 3)):
            b.tx(
                CHECKING,
                _on_day(month, rng.randint(1, 28)),
                -b.amount(25, 180),
                "Pix enviado",
                receiver=_person(rng.choice(FRIENDS)),
            )
        if rng.random() < 0.25:
            b.tx(
                CHECKING,
                _on_day(month, rng.randint(1, 28)),
                b.amount(30, 120),
                "Pix recebido",
                payer=_person(rng.choice(FRIENDS)),
            )

    this_month = _month_start(b.as_of)
    b.tx(
        CHECKING,
        _on_day(_month_start(this_month, -3), 12),
        -80_000,
        "Pix enviado",
        receiver=_person(BORROWER),
        override={"movement_type": "emprestimo_concedido"},
    )
    b.tx(
        CHECKING,
        _on_day(_month_start(this_month, -1), 17),
        30_000,
        "Pix recebido",
        payer=_person(BORROWER),
        override={"movement_type": "devolucao_emprestimo"},
    )
    b.tx(
        CHECKING,
        _on_day(this_month, 2),
        6_400,
        "Pix recebido",
        payer=_person(FRIENDS[1]),
        override={"movement_type": "reembolso", "category": "Alimentação fora e delivery"},
    )
    b.tx(CHECKING, _on_day(this_month, 4), 70_000, "Transferência recebida", payer=_person(OWNER))
    b.tx(CARD, _on_day(this_month, 3), -98_000, "AUTO CENTER DEMO", mcc=7538, override={"extraordinary": True})


def _bills(b: _Builder) -> None:
    """O que foi gasto no cartão no mês M é pago no dia 12 de M+1."""
    for month in b.months():
        total = b.card_spent_by_month.get(f"{month:%Y-%m}", 0)
        due = _next_business_day(_on_day(_month_start(month, 1), 12))
        if total and due <= b.as_of:
            b.tx(CHECKING, due, -total, "Pagamento de fatura")
            b.tx(CARD, due, total, "Pagamento recebido")


def _record(
    b: _Builder,
    investment_id: str,
    day: date,
    kind: str,
    cents: int,
    *,
    quantity: Decimal | None = None,
    price: Decimal | None = None,
) -> None:
    b.session.add(
        InvestmentTransaction(
            id=b.next_id("inv"),
            investment_id=investment_id,
            date=day,
            type=kind,
            quantity=quantity,
            unit_value=price,
            amount_cents=cents,
            net_amount_cents=cents,
            raw_json="{}",
            first_seen_at=b.now,
            last_seen_at=b.now,
        )
    )


def _portfolio(b: _Builder) -> None:
    rng, as_of = b.rng, b.as_of
    first_snapshot = as_of - timedelta(days=SNAPSHOT_DAYS - 1)
    redemption_day = _add_business_days(as_of, -6)
    sale_day = _add_business_days(as_of, -32)
    for index, asset in enumerate(PORTFOLIO):
        investment_id = f"demo-inv-{index:02d}"
        fixed = asset.kind == "FIXED_INCOME"
        b.session.add(
            Investment(
                id=investment_id,
                item_id=ITEM,
                institution=INSTITUTION,
                name=asset.name,
                code=asset.code,
                type=asset.kind,
                subtype=asset.subtype,
                status="ACTIVE",
                issuer="BANCO DEMO S.A." if asset.subtype == "CDB" else None,
                rate=asset.rate[0] if asset.rate else None,
                rate_type=asset.rate[1] if asset.rate else None,
                purchase_date=b.start if fixed else None,
                raw_json="{}",
                first_seen_at=b.now,
                last_seen_at=b.now,
            )
        )
        b.session.flush()
        price, quantity = asset.price, asset.quantity
        invested = int((quantity * price * 100).quantize(Decimal(1)))
        day = b.start
        while day <= as_of:
            if day.weekday() < 5:
                price *= Decimal(str(1 + rng.gauss(asset.daily_drift, asset.daily_volatility)))
            if asset.deposit and day.day == asset.deposit[1] and day.month % asset.deposit[2] == 0:
                cents, _, _, description = asset.deposit
                bought = Decimal(cents) / 100 / price
                quantity += bought
                invested += cents
                _record(b, investment_id, day, "BUY", cents, quantity=bought, price=price)
                b.tx(CHECKING, day, -cents, description)
            if asset.shares_per_month and day.day == 15:
                quantity += asset.shares_per_month
                cents = int((asset.shares_per_month * price * 100).quantize(Decimal(1)))
                _record(b, investment_id, day, "BUY", cents, quantity=asset.shares_per_month, price=price)
                b.tx(CHECKING, day, -cents, "Compra de Renda Variável")
            if asset.monthly_income_per_share and day.day == 14:
                cents = int((asset.monthly_income_per_share * quantity * 100).quantize(Decimal(1)))
                _record(b, investment_id, day, "INTEREST", cents)
                b.tx(CHECKING, day, cents, "Valor recebido de Investimento")
            if asset.subtype == "CDB" and day == redemption_day:
                cents = 320_000  # resgate maior que os aportes do mês
                quantity -= Decimal(cents) / 100 / price
                invested -= cents
                b.tx(CHECKING, day, cents, "Resgate CDB Banco Demo")
            if asset.code == "KORA3" and day == sale_day:
                sold = Decimal(20)  # venda parcial: o dinheiro cai na conta em D+2 úteis
                quantity -= sold
                cents = int((sold * price * 100).quantize(Decimal(1)))
                _record(b, investment_id, day, "SELL", cents, quantity=sold, price=price)
                b.tx(CHECKING, _add_business_days(day, 2), cents - 35, "Valor recebido de Investimento")
            if day >= first_snapshot:
                gross = int((quantity * price * 100).quantize(Decimal(1)))
                net = gross - int(max(0, gross - invested) * Decimal("0.15")) if fixed else gross
                b.session.add(
                    InvestmentSnapshot(
                        snapshot_date=day,
                        investment_id=investment_id,
                        quantity=quantity,
                        unit_value=price,
                        balance_cents=net,
                        amount_cents=gross,
                        amount_original_cents=invested if fixed else None,
                        value_date=day,
                        status="ACTIVE",
                        captured_at=b.now,
                    )
                )
            day += timedelta(days=1)

    # compra que saiu da conta hoje e só aparece na carteira em D+2: "em trânsito" no patrimônio
    b.tx(CHECKING, as_of if as_of.weekday() < 5 else _add_business_days(as_of, -1), -46_250, "Compra de Renda Variável")


def _account_snapshots(b: _Builder) -> None:
    balance, open_bill, day = STARTING_BALANCE_CENTS, 0, b.start
    first_snapshot = b.as_of - timedelta(days=SNAPSHOT_DAYS - 1)
    while day <= b.as_of:
        balance += b.checking_moves.get(day, 0)
        open_bill = b.card_spent_by_month.get(f"{day:%Y-%m}", 0)
        if day >= first_snapshot:
            for account_id, value in ((CHECKING, balance), (CARD, open_bill)):
                b.session.add(
                    AccountSnapshot(
                        snapshot_date=day,
                        account_id=account_id,
                        balance_cents=value,
                        credit_limit_cents=CARD_LIMIT_CENTS if account_id == CARD else None,
                        available_credit_limit_cents=CARD_LIMIT_CENTS - value if account_id == CARD else None,
                        captured_at=b.now,
                    )
                )
        day += timedelta(days=1)
    b.session.get(Account, CHECKING).balance_cents = balance
    b.session.get(Account, CARD).balance_cents = open_bill


def _market(b: _Builder) -> None:
    day = b.as_of - timedelta(days=SNAPSHOT_DAYS + 15)
    while day <= b.as_of:
        if day.weekday() < 5:
            b.session.add(MarketSeries(series_code=CDI, date=day, value=Decimal("0.049037"), fetched_at=b.now))
        day += timedelta(days=1)
    month = _month_start(b.as_of)
    for value in ("0.31", "0.42", "0.18", "0.27", "0.39", "0.22", "0.35", "0.29", "0.44", "0.26"):
        month = _month_start(month, -1)  # o mês corrente ainda não tem IPCA, como na vida real
        b.session.add(MarketSeries(series_code=IPCA, date=month, value=Decimal(value), fetched_at=b.now))


def _plan(b: _Builder) -> None:
    """Metas com histórico de vigência: a meta de aporte subiu há 3 meses."""

    def month(back: int) -> str:
        return f"{_month_start(b.as_of, -back):%Y-%m}"

    settings = (
        ("aporte_mensal", month(10), {"cents": 150_000, "extra_paycheck": False}),
        ("aporte_mensal", month(3), {"cents": 200_000, "extra_paycheck": False}),
        ("colchao", month(10), {"cents": 50_000}),
        ("reserva", month(10), {"cents": 1_800_000, "order": ["CDB/RDB", "Tesouro"]}),
        (
            "alvo_patrimonio",
            month(10),
            {
                "classes": {
                    "renda_fixa": 30,
                    "etf_global": 25,
                    "etf_brasil": 15,
                    "acoes_nucleo": 15,
                    "fiis": 10,
                    "satelite": 5,
                },
                "etf_global": "MUND11",
                "etf_brasil": "IBXX11",
            },
        ),
        (
            "nucleo",
            month(10),
            {"tickers": ["ORBI3", "TERA3"], "satellite": ["NEBU34"], "weights": "iguais", "custom": {}},
        ),
        ("rentabilidade", month(10), {"assumed": 0.10, "aspirational": 0.12}),
    )
    for index, (key, effective, value) in enumerate(settings):
        b.session.add(
            PlanSetting(
                key=key,
                effective_month=effective,
                value_json=value,
                created_at=b.now - timedelta(days=len(settings) - index),
            )
        )
    for tx_id, override in b.overrides:
        b.session.add(ClassificationOverride(transaction_id=tx_id, created_at=b.now, updated_at=b.now, **override))


def _sync_status(b: _Builder) -> None:
    b.session.add(
        SyncRun(
            started_at=b.now - timedelta(hours=2),
            finished_at=b.now - timedelta(hours=2, seconds=-6),
            status="success",
            accounts_seen=2,
            transactions_new=9,
            transactions_updated=2,
            snapshots_created=13,
        )
    )
    b.session.add(
        ItemStatus(
            item_id=ITEM,
            connector_name="Conexão de demonstração",
            status="UPDATED",
            execution_status="SUCCESS",
            pluggy_last_updated_at=b.now - timedelta(hours=3),
            next_auto_sync_at=b.now + timedelta(hours=21),
            consent_expires_at=b.now + timedelta(days=240),
            checked_at=b.now - timedelta(hours=2),
        )
    )


def populate(session: Session, as_of: date, now: datetime) -> None:
    b = _Builder(session, as_of, now, random.Random(SEED))
    _accounts(b)
    _income(b)
    _household(b)
    _card(b)
    _people(b)
    _portfolio(b)
    _bills(b)
    _account_snapshots(b)
    _market(b)
    _plan(b)
    _sync_status(b)


def reference_now(as_of: date) -> datetime:
    """Meio-dia em Brasília no dia de referência, em UTC sem fuso (a convenção do banco)."""
    return datetime(as_of.year, as_of.month, as_of.day, 15)


def build_demo(root: Path, *, as_of: date | None = None, now: datetime | None = None) -> Paths:
    """(Re)cria o banco de demonstração em root/data e devolve os caminhos dele."""
    paths = Paths(root)
    paths.ensure()
    if now is None:
        now = reference_now(as_of) if as_of else utcnow()
    as_of = as_of or local_date(now)
    try:
        if paths.db_path.exists():
            paths.db_path.unlink()
    except PermissionError:  # demonstração já aberta em outra janela: reaproveita o banco
        return paths
    (paths.data_dir / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    paths.personal_rules_path.write_text(RULES, encoding="utf-8")
    paths.asset_classes_path.write_text(CLASSES, encoding="utf-8")
    engine = make_engine(paths.db_path)
    try:
        upgrade_to_head(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            populate(session, as_of, now)
            session.commit()
        run_classification(paths, factory, now=now)
    finally:
        engine.dispose()
    return paths
