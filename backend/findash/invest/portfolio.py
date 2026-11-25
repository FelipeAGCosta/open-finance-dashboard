"""Leitura da carteira a partir das fotos diárias: alocação, renda fixa e proventos (patrimônio: `wealth`).

Os valores seguem o app do banco: saldo BRUTO (amount, antes do IR estimado), exceto os produtos que o perfil
da instituição diz que o app mostra pelo LÍQUIDO (balance), como as Caixinhas do Nubank. Sem bruto informado,
vale o líquido. Ativos com saldo zero (resgatados) ficam de fora. A rentabilidade (performance) continua no
bruto, comparável com o CDI.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import Investment, InvestmentSnapshot, InvestmentTransaction
from findash.institutions import get_profile
from findash.invest.classes import CLASS_ORDER, ClassMap

INCOME_TYPES = ("INTEREST", "DIVIDEND", "JCP", "INCOME")  # proventos; renda fixa fica de fora (rendimento acumula)


@dataclass
class Position:
    investment: Investment
    snapshot: InvestmentSnapshot
    asset_class: str
    class_source: str

    @property
    def label(self) -> str:
        return position_label(self.investment)

    @property
    def value_cents(self) -> int:
        """Valor como o app do banco mostra (ver `bank_cents`)."""
        return bank_cents(self.investment, self.snapshot)

    @property
    def gross_value_cents(self) -> int:
        """Saldo bruto (antes do IR)."""
        return gross_cents(self.snapshot)

    @property
    def net_cents(self) -> int:
        """Saldo líquido (IR estimado pela Pluggy já descontado)."""
        return self.snapshot.balance_cents or 0


def gross_cents(snap: InvestmentSnapshot) -> int:
    return (snap.amount_cents if snap.amount_cents is not None else snap.balance_cents) or 0


GROSS_SQL = func.coalesce(InvestmentSnapshot.amount_cents, InvestmentSnapshot.balance_cents)


def bank_cents(inv: Investment, snap: InvestmentSnapshot) -> int:
    """Valor como no app do banco: bruto, ou líquido de IR quando o perfil da instituição diz que é assim."""
    if get_profile(inv.institution).values_net_of_tax(inv) and snap.balance_cents is not None:
        return snap.balance_cents
    return gross_cents(snap)


def position_label(inv: Investment) -> str:
    if inv.code and inv.type != "FIXED_INCOME":
        return inv.code
    suffix = f" {inv.purchase_date:%d/%m/%Y}" if inv.purchase_date else ""
    return f"{short_name(inv)}{suffix}"


def short_name(inv: Investment) -> str:
    """'CDB - BANCO EXEMPLO S.A. - SOCIEDADE DE CREDITO...' -> 'CDB - BANCO EXEMPLO S.A.'."""
    return " - ".join((inv.name or inv.subtype or "?").split(" - ")[:2])[:30]


def latest_snapshot_date(session: Session) -> date | None:
    return session.scalar(select(func.max(InvestmentSnapshot.snapshot_date)))


def positions(session: Session, class_map: ClassMap, day: date | None = None) -> list[Position]:
    day = day or latest_snapshot_date(session)
    if day is None:
        return []
    rows = session.execute(
        select(InvestmentSnapshot, Investment)
        .join(Investment, Investment.id == InvestmentSnapshot.investment_id)
        .where(InvestmentSnapshot.snapshot_date == day)
    )
    result = []
    for snap, inv in rows:
        if not snap.balance_cents or snap.balance_cents <= 0:
            continue
        asset_class, source = class_map.classify(inv.code, inv.subtype)
        result.append(Position(inv, snap, asset_class, source))
    return sorted(result, key=lambda p: (CLASS_ORDER.index(p.asset_class), -p.value_cents, p.label))


@dataclass
class Allocation:
    total_cents: int  # bruto
    by_class: dict[str, int]
    by_asset: list[tuple[str, str, int]]  # (classe, ativo, centavos), ativos de mesmo rótulo somados


def allocation(items: list[Position]) -> Allocation:
    by_class: dict[str, int] = defaultdict(int)
    by_asset: dict[tuple[str, str], int] = defaultdict(int)
    for p in items:
        by_class[p.asset_class] += p.value_cents
        label = p.label if p.investment.type != "FIXED_INCOME" else short_name(p.investment)
        by_asset[(p.asset_class, label)] += p.value_cents
    ordered = {c: by_class[c] for c in CLASS_ORDER if by_class.get(c)}
    assets = sorted(((c, a, v) for (c, a), v in by_asset.items()), key=lambda x: (CLASS_ORDER.index(x[0]), -x[2], x[1]))
    return Allocation(sum(by_class.values()), ordered, assets)


@dataclass
class FixedIncomeRow:
    label: str
    asset_class: str
    purchase_date: date | None
    due_date: date | None
    rate: str
    applied_cents: int | None
    gross_cents: int | None
    net_cents: int | None

    @property
    def profit_cents(self) -> int | None:
        return None if self.applied_cents is None or self.gross_cents is None else self.gross_cents - self.applied_cents

    @property
    def return_pct(self) -> float | None:
        if not self.applied_cents or self.gross_cents is None:
            return None
        return self.gross_cents / self.applied_cents - 1

    def annualized(self, today: date) -> float | None:
        r = self.return_pct
        if r is None or not self.purchase_date or (today - self.purchase_date).days < 30:
            return None
        return (1 + r) ** (365 / (today - self.purchase_date).days) - 1


def fixed_income(items: list[Position]) -> list[FixedIncomeRow]:
    rows = []
    for p in items:
        if p.investment.type != "FIXED_INCOME":
            continue
        inv, snap = p.investment, p.snapshot
        rate = ""
        if inv.rate is not None:
            rate = f"{_num(inv.rate)}% {inv.rate_type or ''}".strip()
            if (inv.rate_type or "").upper() in ("SELIC", "IPCA") and inv.rate < 50:
                rate = f"{inv.rate_type} + {_num(inv.rate)}%"
        elif inv.fixed_annual_rate is not None:
            rate = f"{_num(inv.fixed_annual_rate)}% a.a."
        rows.append(
            FixedIncomeRow(
                p.label,
                p.asset_class,
                inv.purchase_date,
                inv.due_date,
                rate,
                snap.amount_original_cents,
                snap.amount_cents,
                snap.balance_cents,
            )
        )
    return rows


@dataclass
class Dividends:
    by_asset: dict[str, int]
    by_month: dict[str, int]
    total_cents: int


def dividends(session: Session, today: date, months: int = 12) -> Dividends:
    index = today.year * 12 + today.month - 1 - (months - 1)
    start = date(index // 12, index % 12 + 1, 1)
    rows = session.execute(
        select(InvestmentTransaction, Investment)
        .join(Investment, Investment.id == InvestmentTransaction.investment_id)
        .where(
            InvestmentTransaction.type.in_(INCOME_TYPES),
            InvestmentTransaction.date >= start,
            InvestmentTransaction.date <= today,
            Investment.type != "FIXED_INCOME",
        )
    )
    by_asset: dict[str, int] = defaultdict(int)
    by_month: dict[str, int] = {}
    cursor = start
    while cursor <= today:
        by_month[f"{cursor:%Y-%m}"] = 0
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    for tx, inv in rows:
        cents = abs(tx.net_amount_cents if tx.net_amount_cents is not None else (tx.amount_cents or 0))
        by_asset[inv.code or inv.name or "?"] += cents
        by_month[f"{tx.date:%Y-%m}"] += cents
    ordered = dict(sorted(by_asset.items(), key=lambda kv: (-kv[1], kv[0])))
    return Dividends(ordered, by_month, sum(by_asset.values()))


@dataclass
class DividendMonth:
    month: str
    by_class: dict[str, int]
    by_asset: dict[str, int]

    @property
    def total_cents(self) -> int:
        return sum(self.by_class.values())


def dividends_by_class(session: Session, class_map: ClassMap, today: date, months: int = 12) -> list[DividendMonth]:
    """Proventos dos últimos `months` meses, mês a mês, por classe e por ativo (renda fixa fica de fora)."""
    index = today.year * 12 + today.month - 1 - (months - 1)
    start = date(index // 12, index % 12 + 1, 1)
    out: dict[str, DividendMonth] = {}
    cursor = start
    while cursor <= today:
        key = f"{cursor:%Y-%m}"
        out[key] = DividendMonth(key, defaultdict(int), defaultdict(int))
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    rows = session.execute(
        select(InvestmentTransaction, Investment)
        .join(Investment, Investment.id == InvestmentTransaction.investment_id)
        .where(
            InvestmentTransaction.type.in_(INCOME_TYPES),
            InvestmentTransaction.date >= start,
            InvestmentTransaction.date <= today,
            Investment.type != "FIXED_INCOME",
        )
    )
    for tx, inv in rows:
        cents = abs(tx.net_amount_cents if tx.net_amount_cents is not None else (tx.amount_cents or 0))
        asset_class, _ = class_map.classify(inv.code, inv.subtype)
        item = out[f"{tx.date:%Y-%m}"]
        item.by_class[asset_class] += cents
        item.by_asset[inv.code or inv.name or "?"] += cents
    for item in out.values():
        item.by_class = {c: item.by_class[c] for c in CLASS_ORDER if item.by_class.get(c)}
        item.by_asset = dict(sorted(item.by_asset.items(), key=lambda kv: (-kv[1], kv[0])))
    return list(out.values())


def _num(value: Decimal) -> str:
    text = f"{value.normalize():f}" if isinstance(value, Decimal) else str(value)
    return text.replace(".", ",")
