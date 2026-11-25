"""Comando `carteira`: alocação, patrimônio, rentabilidade × CDI/IPCA, renda fixa e proventos."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, sessionmaker

from findash.config import Paths, local_date, utcnow
from findash.invest import market
from findash.invest.classes import ClassesError, ensure_personal_file, load_class_map
from findash.invest.performance import PeriodResult, accumulated_result, monthly_results, portfolio_series
from findash.invest.portfolio import allocation, dividends, fixed_income, positions
from findash.invest.wealth import wealth

EXIT_OK, EXIT_ERROR = 0, 1
NET_WORTH_DAYS = 10


def cmd_carteira(
    paths: Paths, session_factory: sessionmaker, *, fetch: market.Fetcher | None = market.fetch_sgs
) -> int:
    try:
        ensure_personal_file(paths.asset_classes_path)
        class_map = load_class_map(paths.config_dir, paths.asset_classes_path)
    except ClassesError as exc:
        print(f"ERRO nas classes de ativos: {exc}")
        return EXIT_ERROR
    now = utcnow()
    today = local_date(now)
    with session_factory() as session:
        series = portfolio_series(session)
        update = market.SeriesUpdate()
        if len(series.valuations) >= 2:
            market.refresh(
                session, series.valuations[0][0] - timedelta(days=7), today, now=now, fetch=fetch, update=update
            )
            session.commit()
        lines = carteira_lines(session, class_map, series, today)
    lines += [f"⚠ {w}" for w in update.warnings]
    print("\n".join(lines))
    return EXIT_OK


def carteira_lines(session: Session, class_map, series, today: date) -> list[str]:
    out: list[str] = []
    title = lambda text: out.extend(["", text, "-" * len(text)])  # noqa: E731
    items = positions(session, class_map)
    if not items:
        return ["Nenhuma foto da carteira ainda. Rode: findash sync"]
    snapshot_day = items[0].snapshot.snapshot_date

    alloc = allocation(items)
    title(f"Alocação por classe (foto de {snapshot_day:%d/%m/%Y}, saldo bruto)")
    for asset_class, cents in alloc.by_class.items():
        out.append(f"  {asset_class:<10}{_brl(cents):>16}  {_pct(cents, alloc.total_cents)}")
    out.append(f"  {'TOTAL':<10}{_brl(alloc.total_cents):>16}")
    title("Alocação por ativo")
    for asset_class, label, cents in alloc.by_asset:
        out.append(f"  {asset_class:<9}{label[:40]:<41}{_brl(cents):>15}  {_pct(cents, alloc.total_cents)}")
    unmapped = sorted({p.label for p in items if "sem mapa" in p.class_source})
    if unmapped:
        out.append(f"  ⚠ sem classe conhecida (foram para Outros): {', '.join(unmapped)}")
    manual = sorted({f"{p.label}→{p.asset_class}" for p in items if p.class_source == "correção manual"})
    if manual:
        out.append(f"  correções manuais aplicadas: {', '.join(manual)}")

    title("Patrimônio total (carteira como no app do banco + em trânsito; conta e fatura ficam fora)")
    total = wealth(session, today)
    if total is None:
        out.append("  sem fotos da carteira ainda")
    else:
        for d in total.series[-NET_WORTH_DAYS:]:
            out.append(
                f"  {d.day:%d/%m/%Y}  carteira {_brl(d.portfolio_cents):>15}"
                f"  + em trânsito {_brl(d.in_transit_cents):>13}"
                f"  = {_brl(d.total_cents):>15}"
            )
        for o in total.in_transit:
            out.append(
                f"  em trânsito: {_brl(o.cents)} ({o.description}, {o.day:%d/%m}; sai da conta até {o.until:%d/%m})"
            )

    title("Rentabilidade da carteira (a partir das fotos diárias)")
    if series.valuations:
        first, last = series.valuations[0][0], series.valuations[-1][0]
        out.append(f"  fotos diárias: {series.snapshot_days} (de {first:%d/%m/%Y} a {last:%d/%m/%Y})")
    months = monthly_results(series)
    if not months:
        out.append(
            "  a rentabilidade aparece a partir da segunda foto diária (a sincronização diária cria uma por dia)"
        )
    else:
        out.append(
            f"  {'período':<10}{'de':>11}{'até':>11}{'aportes−resg.':>16}{'proventos':>13}{'TWR':>9}"
            f"{'XIRR a.a.':>11}{'XIRR per.':>11}{'CDI':>9}{'IPCA':>9}"
        )
        notes: list[str] = []
        accumulated = accumulated_result(series)
        for result in months + ([accumulated] if accumulated and len(months) > 1 else []):
            out.append(_period_line(session, result, notes))
        if len(months) == 1 and accumulated:
            out.append("  (acumulado = o único mês com fotos)")
        out += [f"  obs.: {n}" for n in dict.fromkeys(notes)]
        out.append(
            "  TWR mede os investimentos (ignora quando/quanto você aportou); XIRR mede o seu resultado com "
            "as datas dos aportes. Compare o TWR com o CDI e o IPCA."
        )

    title("Renda fixa (valor atual × valor aplicado, desde a aplicação)")
    rows = fixed_income(items)
    if not rows:
        out.append("  nenhum título de renda fixa com saldo")
    for r in rows:
        annual = r.annualized(today)
        out.append(
            f"  {r.asset_class:<8}{r.label[:44]:<45}{r.rate[:14]:<15}aplicado {_brl(r.applied_cents):>13}  "
            f"bruto {_brl(r.gross_cents):>13}  líquido {_brl(r.net_cents):>13}  "
            f"rend. {_brl(r.profit_cents):>11} ({_ratio(r.return_pct)}"
            f"{'; ' + _ratio(annual) + ' a.a.' if annual is not None else ''})"
        )

    div = dividends(session, today)
    title("Proventos nos últimos 12 meses (pagos na conta)")
    if not div.total_cents:
        out.append("  nenhum provento registrado")
    else:
        out.append(f"  total {_brl(div.total_cents)}")
        out.append("  por ativo: " + ", ".join(f"{k} {_brl(v)}" for k, v in div.by_asset.items()))
        out.append("  por mês:   " + ", ".join(f"{k} {_brl(v)}" for k, v in div.by_month.items()))
    return out


def _period_line(session: Session, r: PeriodResult, notes: list[str]) -> str:
    cdi = market.cdi_return(session, r.start, r.end)
    ipca = market.ipca_return(session, r.start, r.end)
    notes += [n for n in (cdi.note, ipca.note) if n]
    return (
        f"  {r.label:<10}{r.start.strftime('%d/%m/%Y'):>11}{r.end.strftime('%d/%m/%Y'):>11}"
        f"{_brl(r.net_flows):>16}{_brl(r.income):>13}"
        f"{_ratio(r.twr):>9}{_ratio(r.xirr_annual):>11}{_ratio(r.xirr_period):>11}{_ratio(cdi.value):>9}"
        f"{_ratio(ipca.value):>9}"
    )


def _brl(cents: int | None) -> str:
    if cents is None:
        return "—"
    text = f"{cents / 100:,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(part: int, total: int) -> str:
    return f"{part / total:6.1%}".replace(".", ",") if total else "     —"


def _ratio(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{0.0 if abs(value) < 5e-7 else value:.2%}".replace(".", ",")
