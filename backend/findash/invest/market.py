"""Séries públicas do Banco Central (SGS), com cache local na tabela market_series.

Séries usadas (códigos conferidos na API do SGS):
- 12  = CDI diário, em % ao dia (um valor por dia útil);
- 433 = IPCA mensal, em % no mês (data = primeiro dia do mês; publicado no mês seguinte).
API: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json&dataInicial=DD/MM/AAAA&dataFinal=DD/MM/AAAA
Desde 26/03/2025 o BC exige dataInicial/dataFinal em séries diárias e limita a consulta a 10 anos.
Nenhum dado pessoal é enviado: só o código da série e as datas.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findash.db.models import MarketSeries

log = logging.getLogger("findash.invest.market")

CDI = 12
IPCA = 433
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
MAX_YEARS = 10

Fetcher = Callable[[int, date, date], list[tuple[date, Decimal]]]


class MarketDataError(Exception):
    """Falha ao buscar uma série no Banco Central."""


def fetch_sgs(code: int, start: date, end: date) -> list[tuple[date, Decimal]]:
    params = {"formato": "json", "dataInicial": f"{start:%d/%m/%Y}", "dataFinal": f"{end:%d/%m/%Y}"}
    try:
        response = httpx.get(SGS_URL.format(code=code), params=params, timeout=20.0)
    except httpx.HTTPError as exc:
        raise MarketDataError(f"SGS {code}: {type(exc).__name__}") from None
    if response.status_code == 404:  # o SGS responde 404 quando não há dados no período
        return []
    if response.status_code != 200:
        raise MarketDataError(f"SGS {code}: HTTP {response.status_code}")
    try:
        rows = response.json()
        return [(datetime.strptime(r["data"], "%d/%m/%Y").date(), Decimal(str(r["valor"]))) for r in rows]
    except (ValueError, KeyError, TypeError) as exc:
        raise MarketDataError(f"SGS {code}: resposta inesperada ({type(exc).__name__})") from None


@dataclass
class SeriesUpdate:
    fetched: dict[int, int] = field(default_factory=dict)  # código -> linhas novas
    warnings: list[str] = field(default_factory=list)


def refresh(
    session: Session,
    start: date,
    end: date,
    *,
    now: datetime,
    fetch: Fetcher | None = fetch_sgs,
    update: SeriesUpdate | None = None,
) -> SeriesUpdate:
    """Garante CDI e IPCA de `start` a `end` no cache. fetch=None: só o cache (modo offline)."""
    update = update or SeriesUpdate()
    if fetch is None:
        return update
    start = max(start, date(end.year - MAX_YEARS + 1, 1, 1))
    for code, first in ((CDI, start), (IPCA, start.replace(day=1))):
        last = session.scalar(
            select(func.max(MarketSeries.date)).where(MarketSeries.series_code == code, MarketSeries.date >= first)
        )
        since = first if last is None else max(first, last)
        if last is not None and since >= end:
            continue
        try:
            rows = fetch(code, since, end)
        except MarketDataError as exc:
            update.warnings.append(
                f"não foi possível atualizar a série {code} do Banco Central ({exc}); usando o que já está no banco"
            )
            continue
        existing = set(
            session.scalars(
                select(MarketSeries.date).where(
                    MarketSeries.series_code == code, MarketSeries.date.in_([day for day, _ in rows])
                )
            )
        )
        new = [
            MarketSeries(series_code=code, date=day, value=value, fetched_at=now)
            for day, value in rows
            if day not in existing
        ]
        session.add_all(new)
        session.flush()
        update.fetched[code] = len(new)
    return update


@dataclass
class Benchmark:
    value: float | None  # retorno acumulado no período (0.01 = 1%)
    note: str = ""


def cdi_return(session: Session, start: date, end: date) -> Benchmark:
    """CDI acumulado de start a end: produto de (1 + taxa do dia) para os dias úteis start <= d < end
    (a taxa publicada para o dia d remunera de d até o próximo dia útil)."""
    if end <= start:
        return Benchmark(0.0)
    rows = session.scalars(
        select(MarketSeries).where(MarketSeries.series_code == CDI, MarketSeries.date >= start, MarketSeries.date < end)
    ).all()
    last = session.scalar(select(func.max(MarketSeries.date)).where(MarketSeries.series_code == CDI))
    factor = Decimal(1)
    for row in rows:
        factor *= 1 + row.value / 100
    note = ""
    if last is None:
        return Benchmark(None, "CDI sem dados no banco")
    if last < end and (end - last).days > 4:
        note = f"CDI disponível até {last:%d/%m/%Y}"
    return Benchmark(float(factor - 1), note)


def ipca_return(session: Session, start: date, end: date) -> Benchmark:
    """IPCA acumulado de start a end; meses parciais entram proporcionalmente aos dias (juros compostos)."""
    if end <= start:
        return Benchmark(0.0)
    months = dict(
        session.execute(
            select(MarketSeries.date, MarketSeries.value).where(
                MarketSeries.series_code == IPCA, MarketSeries.date >= start.replace(day=1), MarketSeries.date < end
            )
        ).all()
    )
    return _ipca_from_months(months, start, end)


def cumulative_benchmarks(session: Session, start: date, dates: list[date]) -> list[tuple[Benchmark, Benchmark]]:
    """CDI e IPCA acumulados de `start` até cada data, numa passada só (para séries diárias)."""
    if not dates:
        return []
    end = max(dates)
    cdi_rows = session.execute(
        select(MarketSeries.date, MarketSeries.value)
        .where(MarketSeries.series_code == CDI, MarketSeries.date >= start, MarketSeries.date < end)
        .order_by(MarketSeries.date)
    ).all()
    last_cdi = session.scalar(select(func.max(MarketSeries.date)).where(MarketSeries.series_code == CDI))
    months = dict(
        session.execute(
            select(MarketSeries.date, MarketSeries.value).where(
                MarketSeries.series_code == IPCA, MarketSeries.date >= start.replace(day=1), MarketSeries.date < end
            )
        ).all()
    )
    out, factor, index = [], Decimal(1), 0
    for day in sorted(dates):
        while index < len(cdi_rows) and cdi_rows[index][0] < day:
            factor *= 1 + cdi_rows[index][1] / 100
            index += 1
        if last_cdi is None:
            cdi = Benchmark(None, "CDI sem dados no banco")
        else:
            note = f"CDI disponível até {last_cdi:%d/%m/%Y}" if last_cdi < day and (day - last_cdi).days > 4 else ""
            cdi = Benchmark(float(factor - 1) if day > start else 0.0, note)
        out.append((cdi, _ipca_from_months(months, start, day)))
    return out


def _ipca_from_months(months: dict, start: date, end: date) -> Benchmark:
    if end <= start:
        return Benchmark(0.0)
    factor, missing, cursor = 1.0, [], start
    while cursor < end:
        month_start = cursor.replace(day=1)
        next_month = date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
        segment_end = min(end, next_month)
        fraction = (segment_end - cursor).days / (next_month - month_start).days
        if month_start in months:
            factor *= (1 + float(months[month_start]) / 100) ** fraction
        else:
            missing.append(f"{month_start:%m/%Y}")
        cursor = segment_end
    note = f"IPCA ainda não publicado para {', '.join(missing)} (fica de fora)" if missing else ""
    if missing and not months:
        return Benchmark(None, note)
    return Benchmark(factor - 1, note)
