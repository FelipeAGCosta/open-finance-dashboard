"""Rentabilidade da carteira a partir das fotos diárias: TWR e XIRR.

TWR × XIRR, em uma frase cada:
- TWR (retorno ponderado pelo tempo) mede a qualidade dos INVESTIMENTOS: divide o período em
  trechos entre fotos, calcula o retorno de cada trecho descontando aportes e resgates e encadeia
  (1+r1)(1+r2)... − 1. Quanto e quando você aportou não muda o resultado; é o número comparável
  com CDI, IPCA e fundos.
- XIRR (taxa interna de retorno com datas) mede o resultado do INVESTIDOR: a taxa anual que zera
  o valor presente de todos os fluxos (valor inicial e aportes como saídas do bolso; resgates,
  proventos e valor final como entradas). Aportar muito antes de uma alta aumenta o XIRR; o TWR
  não muda.

Convenções:
- valor da carteira = soma do saldo BRUTO (amount; sem ele, o líquido) de todos os ativos na foto do dia
  (o CDI e o IPCA de comparação também são brutos);
- fluxos externos: aportes da conta (entram na carteira) e resgates/vendas (saem). Um resgate ligado
  à queda de uma foto usa a data da foto; os demais, a data do crédito na conta;
- proventos e rendimentos pagos na conta contam como RETORNO (não como resgate);
- dentro de cada trecho entre fotos, o fluxo é ponderado pelo tempo restante (Dietz modificado):
  com fotos diárias, um fluxo do próprio dia da foto entra como fim do trecho (peso 0);
- XIRR usa base de 365 dias; para o mês, também é mostrado o retorno equivalente do período.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import (
    STATE_ACTIVE,
    Account,
    InvestmentSnapshot,
    RedemptionOrigin,
    Transaction,
    TransactionClassification,
)


def twr(
    valuations: list[tuple[date, int]], flows: list[tuple[date, int]], income: list[tuple[date, int]] = ()
) -> float | None:
    """Retorno ponderado pelo tempo. flows: + entra na carteira (aporte), − sai (resgate).
    income: proventos pagos fora da carteira (contam como retorno). None se não houver trecho válido."""
    points = sorted(valuations)
    if len(points) < 2:
        return None
    factor, valid = 1.0, False
    for (d0, v0), (d1, v1) in itertools.pairwise(points):
        span = (d1 - d0).days
        period_flows = [(d, c) for d, c in flows if d0 < d <= d1]
        net_flow = sum(c for _, c in period_flows)
        weighted = sum(c * (d1 - d).days / span for d, c in period_flows) if span else 0
        gain = v1 - v0 - net_flow + sum(c for d, c in income if d0 < d <= d1)
        base = v0 + weighted
        if base <= 0:
            continue  # carteira vazia no início do trecho: retorno indefinido
        factor *= 1 + gain / base
        valid = True
    return factor - 1 if valid else None


def xirr(cashflows: list[tuple[date, int]]) -> float | None:
    """Taxa anual (base 365) que zera o VPL. Convenção do investidor: saídas do bolso negativas."""
    flows = [(d, c) for d, c in cashflows if c]
    if not flows or not any(c > 0 for _, c in flows) or not any(c < 0 for _, c in flows):
        return None
    origin = min(d for d, _ in flows)
    times = [((d - origin).days / 365.0, c) for d, c in flows]
    if max(t for t, _ in times) == 0:
        return None

    def npv(rate: float) -> float:
        return sum(c / (1 + rate) ** t for t, c in times)

    low, high = -0.9999, 1.0
    while npv(high) > 0 and high < 1e6:  # amplia o intervalo para taxas altas em períodos curtos
        high *= 2
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(300):  # bisseção: robusta e precisa o bastante (centésimos de ponto percentual)
        mid = (low + high) / 2
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
        if high - low < 1e-12:
            break
    return (low + high) / 2


def period_equivalent(annual_rate: float | None, days: int) -> float | None:
    return None if annual_rate is None else (1 + annual_rate) ** (days / 365.0) - 1


# ---------------------------------------------------------------------------------- dados do banco


@dataclass
class PortfolioSeries:
    valuations: list[tuple[date, int]] = field(default_factory=list)
    flows: list[tuple[date, int]] = field(default_factory=list)  # + aporte, − resgate
    income: list[tuple[date, int]] = field(default_factory=list)

    @property
    def snapshot_days(self) -> int:
        return len(self.valuations)


def portfolio_series(session: Session) -> PortfolioSeries:
    series = PortfolioSeries()
    series.valuations = [
        (d, int(v or 0))
        for d, v in session.execute(
            select(
                InvestmentSnapshot.snapshot_date,
                func.sum(func.coalesce(InvestmentSnapshot.amount_cents, InvestmentSnapshot.balance_cents)),
            )
            .group_by(InvestmentSnapshot.snapshot_date)
            .order_by(InvestmentSnapshot.snapshot_date)
        )
    ]
    if not series.valuations:
        return series
    photo_date: dict[str, date] = {}
    for tx_id, event_date in session.execute(
        select(RedemptionOrigin.transaction_id, func.min(RedemptionOrigin.event_date))
        .where(RedemptionOrigin.source == "foto")
        .group_by(RedemptionOrigin.transaction_id)
    ):
        photo_date[tx_id] = event_date
    rows = session.execute(
        select(
            Transaction.id,
            Transaction.date,
            Transaction.amount_normalized_cents,
            TransactionClassification.movement_type,
        )
        .join(TransactionClassification, TransactionClassification.transaction_id == Transaction.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Transaction.state == STATE_ACTIVE,
            Account.type == "BANK",
            TransactionClassification.movement_type.in_(("aporte", "resgate", "renda_investimento")),
        )
    )
    for tx_id, day, cents, kind in rows:
        if kind == "aporte":
            series.flows.append((day, -cents))  # débito na conta = entra na carteira
        elif kind == "resgate":
            series.flows.append((photo_date.get(tx_id, day), -cents))
        else:
            series.income.append((day, cents))
    series.flows.sort()
    series.income.sort()
    return series


@dataclass
class PeriodResult:
    label: str
    start: date
    end: date
    start_value: int
    end_value: int
    net_flows: int  # + aportes − resgates
    income: int
    twr: float | None
    xirr_annual: float | None
    xirr_period: float | None


def period_result(series: PortfolioSeries, label: str, start: date, end: date) -> PeriodResult | None:
    """Resultado entre a última foto até `start` (inclusive) e a última foto até `end`."""
    points = [p for p in series.valuations if p[0] <= end]
    before = [p for p in points if p[0] <= start]
    inside = [p for p in points if p[0] > start]
    if not inside:
        return None
    first = before[-1] if before else inside[0]
    window = [first] + [p for p in inside if p[0] > first[0]]
    if len(window) < 2:
        return None
    d0, v0 = window[0]
    d1, v1 = window[-1]
    flows = [(d, c) for d, c in series.flows if d0 < d <= d1]
    income = [(d, c) for d, c in series.income if d0 < d <= d1]
    cashflows = [(d0, -v0)] + [(d, -c) for d, c in flows] + income + [(d1, v1)]
    annual = xirr(cashflows)
    return PeriodResult(
        label,
        d0,
        d1,
        v0,
        v1,
        sum(c for _, c in flows),
        sum(c for _, c in income),
        twr(window, flows, income),
        annual,
        period_equivalent(annual, (d1 - d0).days),
    )


def monthly_results(series: PortfolioSeries) -> list[PeriodResult]:
    if len(series.valuations) < 2:
        return []
    first, last = series.valuations[0][0], series.valuations[-1][0]
    results = []
    month = first.replace(day=1)
    while month <= last:
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        start = max(first, date.fromordinal(month.toordinal() - 1))  # última foto do mês anterior
        result = period_result(series, f"{month:%Y-%m}", start, date.fromordinal(next_month.toordinal() - 1))
        if result is not None:
            results.append(result)
        month = next_month
    return results


def cumulative_twr(series: PortfolioSeries) -> list[tuple[date, float]]:
    """TWR acumulado em cada foto, desde a primeira (0 na primeira foto)."""
    if not series.valuations:
        return []
    points = [(series.valuations[0][0], 0.0)]
    factor = 1.0
    for before, after in itertools.pairwise(series.valuations):
        d0, d1 = before[0], after[0]
        step = twr(
            [before, after],
            [(d, c) for d, c in series.flows if d0 < d <= d1],
            [(d, c) for d, c in series.income if d0 < d <= d1],
        )
        if step is not None:
            factor *= 1 + step
        points.append((d1, factor - 1))
    return points


def accumulated_result(series: PortfolioSeries) -> PeriodResult | None:
    if len(series.valuations) < 2:
        return None
    return period_result(series, "acumulado", series.valuations[0][0], series.valuations[-1][0])


@dataclass
class MonthlyReturn:
    """Rendimento de um mês: investido no início, aportes e resgates separados, ganho e TWR."""

    month: str
    start: date  # foto de partida (última do mês anterior; ou a primeira do mês, se não houver)
    end: date
    start_value: int
    end_value: int
    contributions: int  # aportes (positivo)
    redemptions: int  # resgates (positivo)
    income: int  # proventos/rendimentos pagos na conta
    twr: float | None
    partial_since: date | None  # mês que começou depois da primeira foto (ex.: fotos desde 23/11)
    in_progress: bool

    @property
    def gain(self) -> int:
        """Ganho do mês = variação − aportes + resgates (proventos incluídos)."""
        return self.end_value - self.start_value - self.contributions + self.redemptions + self.income


def monthly_returns(series: PortfolioSeries, today: date) -> list[MonthlyReturn]:
    if len(series.valuations) < 2:
        return []
    first, last = series.valuations[0][0], series.valuations[-1][0]
    out = []
    month = first.replace(day=1)
    while month <= last:
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        before = [p for p in series.valuations if p[0] < month]
        inside = [p for p in series.valuations if month <= p[0] < next_month]
        if inside:
            window = ([before[-1]] if before else []) + inside
            if len(window) >= 2:
                d0, v0 = window[0]
                d1, v1 = window[-1]
                flows = [(d, c) for d, c in series.flows if d0 < d <= d1]
                income = sum(c for d, c in series.income if d0 < d <= d1)
                out.append(
                    MonthlyReturn(
                        f"{month:%Y-%m}",
                        d0,
                        d1,
                        v0,
                        v1,
                        sum(c for _, c in flows if c > 0),
                        -sum(c for _, c in flows if c < 0),
                        income,
                        twr(window, flows, [(d, c) for d, c in series.income if d0 < d <= d1]),
                        d0 if not before else None,
                        today < next_month,
                    )
                )
        month = next_month
    return out
