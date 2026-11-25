"""Linha de comando (`findash` ou `python -m findash`).

    findash demo [--as-of AAAA-MM-DD]     interface com dados sintéticos, sem credenciais
    findash app [--porta N]               interface no navegador com os seus dados (só neste computador)
    findash sync [--full]                 backup + migrações + sincronização + classificação + resumo
    findash status                        última sincronização, itens, contagens e saldos
    findash classificar                   recalcula a classificação inteira (idempotente)
    findash fixos [sim|nao|auto ID]
    findash resumo --mes AAAA-MM
    findash a-classificar [--mes AAAA-MM]
    findash override ID [--categoria C] [--tipo T] [--essencial s|n] [--fixo s|n] [--remover]
    findash carteira [--offline]          alocação, patrimônio, rentabilidade × CDI/IPCA, renda fixa, proventos

Códigos de saída: 0 ok; 1 erro de configuração, de regras ou inesperado; 2 autenticação/autorização
recusada pela Pluggy; 3 outro erro da API (limite, servidor, rede).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime

from findash.classify import commands
from findash.config import LOCAL_TZ, ConfigError, Paths, PluggySettings, load_settings, local_date, utcnow
from findash.db import queries
from findash.db.base import make_engine, make_session_factory
from findash.db.migrate import upgrade_to_head
from findash.db.models import SyncRun
from findash.invest import commands as invest_commands
from findash.logging_setup import configure_logging
from findash.pluggy.client import PluggyClient
from findash.security import REDACTOR, Redactor
from findash.sync.backup import backup_database
from findash.sync.service import EXIT_ERROR, EXIT_OK, PluggySource, SyncFailed, consent_warning, run_sync

log = logging.getLogger("findash.cli")

SourceFactory = Callable[[PluggySettings, Redactor], PluggySource]


def _default_source(settings: PluggySettings, redactor: Redactor) -> PluggyClient:
    return PluggyClient(settings.client_id, settings.client_secret.get_secret_value(), redactor=redactor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="findash", description="Painel financeiro local alimentado pelo Open Finance")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="abre a interface com dados sintéticos (não precisa de credenciais)")
    demo.add_argument("--as-of", type=_date_arg, help="data de referência AAAA-MM-DD (padrão: hoje)")
    demo.add_argument("--porta", type=int, default=8765)
    demo.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    sync_parser = sub.add_parser("sync", help="backup + sincronização completa + resumo")
    sync_parser.add_argument("--full", action="store_true", help="ignora a janela incremental e relê tudo")
    sub.add_parser("status", help="última sincronização, item, contagens e saldos")
    sub.add_parser("classificar", help="recalcula tipos, categorias, pareamentos e recorrência")
    fixos = sub.add_parser("fixos", help="gastos fixos e salário (automáticos ou escolha manual)")
    fixos.add_argument("acao", nargs="?", choices=("sim", "nao", "auto"))
    fixos.add_argument("id", nargs="?", type=int)
    resumo = sub.add_parser("resumo", help="resumo de um mês")
    resumo.add_argument("--mes", type=_month_arg, help="AAAA-MM (padrão: mês atual)")
    pending = sub.add_parser("a-classificar", help="despesas sem categoria, agrupadas por contraparte")
    pending.add_argument("--mes", type=_month_arg)
    pending.add_argument("--limite", type=int, default=30)
    override = sub.add_parser("override", help="corrige a classificação de uma transação específica")
    override.add_argument("id")
    override.add_argument("--categoria")
    override.add_argument("--tipo")
    override.add_argument("--essencial", choices=("s", "n"))
    override.add_argument("--fixo", choices=("s", "n"), help="fixo sim/não só nesta transação")
    override.add_argument("--nota")
    override.add_argument("--remover", action="store_true")
    carteira = sub.add_parser("carteira", help="alocação, patrimônio, rentabilidade × CDI/IPCA, renda fixa, proventos")
    carteira.add_argument("--offline", action="store_true", help="não consulta o Banco Central (usa só o cache)")
    app = sub.add_parser("app", help="abre a interface no navegador (servidor local em 127.0.0.1)")
    app.add_argument("--porta", type=int, default=8765)
    app.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    args = parser.parse_args(argv)
    if args.command == "fixos" and args.acao and args.id is None:
        parser.error("informe o ID: findash fixos sim ID")

    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = Paths.default()
    paths.ensure()
    configure_logging(paths.logs_dir)
    if args.command == "sync":
        return cmd_sync(paths, full=args.full)
    if args.command == "status":
        return cmd_status(paths)
    if args.command == "app":
        return cmd_app(paths, port=args.porta, open_browser=not args.sem_navegador)
    if args.command == "demo":
        return cmd_demo(paths, as_of=args.as_of, port=args.porta, open_browser=not args.sem_navegador)
    return _with_database(paths, args)


def cmd_app(paths: Paths, *, port: int, open_browser: bool) -> int:
    from findash.web import server

    if not paths.db_path.exists():
        print("Banco ainda não existe. Rode primeiro: findash sync  (ou veja a demonstração: findash demo)")
        return EXIT_ERROR
    # o app aplica migrações pendentes ao abrir: antes, o mesmo backup diário do sync
    backup_database(paths.db_path, paths.backups_dir, local_date(utcnow()))
    return server.run(paths, port=port, open_browser=open_browser)


def cmd_demo(paths: Paths, *, as_of: date | None, port: int, open_browser: bool) -> int:
    from findash.demo import build_demo, reference_now
    from findash.web import server

    clock = (lambda: reference_now(as_of)) if as_of else utcnow
    demo_paths = build_demo(paths.data_dir / "demo", as_of=as_of, now=clock())
    return server.run(demo_paths, demo=True, port=port, open_browser=open_browser, clock=clock)


def _date_arg(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("use AAAA-MM-DD, ex.: 2026-11-20") from None


def _sgs_fetch():
    from findash.invest.market import fetch_sgs

    return fetch_sgs


def _month_arg(value: str) -> str:
    try:
        year, month = (int(part) for part in value.split("-"))
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("use AAAA-MM, ex.: 2026-10") from None
    return f"{year:04d}-{month:02d}"


def _with_database(paths: Paths, args: argparse.Namespace) -> int:
    if not paths.db_path.exists():
        print("Banco ainda não existe. Rode: findash sync")
        return EXIT_ERROR
    engine = make_engine(paths.db_path)
    try:
        upgrade_to_head(engine)
        factory = make_session_factory(engine)
        if args.command == "classificar":
            return commands.cmd_classificar(paths, factory)
        if args.command == "fixos":
            return commands.cmd_fixos(factory, args.acao, args.id)
        if args.command == "resumo":
            return commands.cmd_resumo(factory, args.mes)
        if args.command == "a-classificar":
            return commands.cmd_a_classificar(factory, args.mes, args.limite)
        if args.command == "carteira":
            return invest_commands.cmd_carteira(paths, factory, fetch=None if args.offline else _sgs_fetch())
        return commands.cmd_override(
            paths,
            factory,
            args.id,
            category=args.categoria,
            movement_type=args.tipo,
            essential=args.essencial,
            note=args.nota,
            remove=args.remover,
            fixed=args.fixo,
        )
    finally:
        engine.dispose()


# ====================================================================== sync


def cmd_sync(
    paths: Paths, *, full: bool = False, source_factory: SourceFactory = _default_source, redactor: Redactor = REDACTOR
) -> int:
    code, lines = sync_report(paths, full=full, source_factory=source_factory, redactor=redactor)
    print("\n".join(lines))
    return code


def sync_report(
    paths: Paths, *, full: bool = False, source_factory: SourceFactory = _default_source, redactor: Redactor = REDACTOR
) -> tuple[int, list[str]]:
    """Backup + migrações + sincronização + classificação. Devolve (código de saída, linhas do relatório)."""
    log.info("=== sync iniciado (full=%s) ===", full)
    paths.ensure()
    first_run = not paths.db_path.exists()
    try:
        backup = backup_database(paths.db_path, paths.backups_dir, local_date(utcnow()))
    except Exception as exc:  # backup falhou: não arrisca o banco
        log.error("Backup falhou; sincronização cancelada: %s", redactor(str(exc)))
        return EXIT_ERROR, [f"ERRO: backup falhou ({redactor(str(exc))}); sincronização cancelada."]

    engine = make_engine(paths.db_path)
    try:
        upgrade_to_head(engine)
        session_factory = make_session_factory(engine)
        try:
            settings = load_settings(paths.root)
        except ConfigError as exc:
            _record_config_error(session_factory, str(exc))
            return EXIT_ERROR, [f"ERRO: {exc}"]

        source = source_factory(settings, redactor)
        try:
            result = run_sync(
                session_factory, source, settings.items, redactor=redactor, full=full or first_run, clock=utcnow
            )
        except SyncFailed as exc:
            return exc.exit_code, [f"ERRO (sync #{exc.run_id}): {exc}"]
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                close()
        try:
            classification = commands.run_classification(paths, session_factory)
            classification_error = None
        except Exception as exc:  # dados sincronizados continuam salvos; só a camada derivada falhou
            classification, classification_error = None, redactor(f"{type(exc).__name__}: {exc}")
            log.error("Classificação falhou após o sync: %s", classification_error)
    finally:
        engine.dispose()

    stats = result.stats
    duration = (result.finished_at - result.started_at).total_seconds()
    lines = [
        f"Sincronização #{result.run_id} concluída em {duration:.1f}s"
        + (" (primeira execução: histórico completo)" if first_run else (" (completa)" if full else "")),
        f"Backup: {backup.name if backup else 'nenhum (banco novo)'}",
        f"Contas: {stats.accounts_seen}",
        f"Transações: {stats.transactions_new} novas, {stats.transactions_updated} atualizadas, "
        f"{stats.transactions_unchanged} sem mudança, {stats.transactions_replaced} substituídas, "
        f"{stats.transactions_removed} removidas",
        f"Investimentos: {stats.investments_new} novos, {stats.investments_updated} atualizados; "
        f"fotos do dia: {stats.snapshots_created} criadas, {stats.snapshots_updated} atualizadas",
        f"Transações de investimentos: {stats.investment_transactions_new} novas, "
        f"{stats.investment_transactions_updated} atualizadas",
    ]
    lines += [f"⚠ {warning}" for warning in stats.warnings]
    if classification is not None:
        levels = classification.expense_level_sums
        total = sum(levels.values())
        pending = levels.get("a_classificar", 0)
        lines.append(
            f"Classificação: {classification.transactions} transações; 'A classificar' = "
            f"{pending / total:.1%} do valor das despesas"
            if total
            else f"Classificação: {classification.transactions} transações"
        )
    else:
        lines.append(f"ERRO na classificação (os dados do sync foram salvos): {classification_error}")
    for line in lines:
        log.info(line)
    return (EXIT_OK if classification is not None else EXIT_ERROR), lines


def _record_config_error(session_factory, message: str) -> None:
    now = utcnow()
    with session_factory() as session:
        session.add(SyncRun(started_at=now, finished_at=now, status="error", error_message=message))
        session.commit()
    log.error(message)


# ====================================================================== status


def cmd_status(paths: Paths) -> int:
    if not paths.db_path.exists():
        print("Banco ainda não existe. Rode: findash sync")
        return EXIT_ERROR
    engine = make_engine(paths.db_path)
    try:
        with make_session_factory(engine)() as session:
            print("\n".join(status_lines(session, now=utcnow())))
    finally:
        engine.dispose()
    return EXIT_OK


def status_lines(session, *, now) -> list[str]:
    out: list[str] = []
    title = lambda text: out.extend(["", text, "-" * len(text)])  # noqa: E731

    title("Última sincronização")
    run = queries.last_sync_run(session)
    if run is None:
        out.append("nenhuma execução registrada")
    else:
        out.append(f"#{run.id} {run.status.upper()} — início {_dt(run.started_at)}, fim {_dt(run.finished_at)}")
        if run.status == "success":
            out.append(
                f"transações: {run.transactions_new} novas, {run.transactions_updated} atualizadas, "
                f"{run.transactions_replaced} substituídas, {run.transactions_removed} removidas"
            )
        if run.error_message:
            out.append(f"erro: {run.error_message}")
        ok = queries.last_successful_sync_run(session)
        if ok is not None and ok.id != run.id:
            out.append(f"último sucesso: #{ok.id} em {_dt(ok.finished_at)}")

    title("Item na Pluggy")
    statuses = queries.item_statuses(session)
    if not statuses:
        out.append("sem dados do item")
    for item in statuses:
        out.append(f"conector: {item.connector_name} | status: {item.status} | execução: {item.execution_status}")
        out.append(
            f"última atualização na Pluggy: {_dt(item.pluggy_last_updated_at)} | próxima: {_dt(item.next_auto_sync_at)}"
        )
        if item.consent_expires_at:
            days = (item.consent_expires_at - now).days
            out.append(f"consentimento expira em: {item.consent_expires_at:%Y-%m-%d} ({days} dias)")
            warning = consent_warning(item.consent_expires_at, now)
            if warning:
                out.append(f"⚠ {warning}")
        out.append(f"verificado em: {_dt(item.checked_at)}")

    title("Banco local")
    for name, value in queries.table_counts(session).items():
        out.append(f"{name:<32}{value:>8}")
    first, last = queries.transaction_date_range(session)
    out.append(f"{'período das transações':<32}{_d(first)} a {_d(last)}")

    title("Saldos atuais (informados pela Pluggy)")
    for acc in queries.account_balances(session):
        if acc.type == "CREDIT":
            out.append(
                f"{acc.label:<40} fatura em aberto {_brl(acc.balance_cents):>14}"
                f" | limite disponível {_brl(acc.available_credit_limit_cents)} de {_brl(acc.credit_limit_cents)}"
            )
        else:
            out.append(f"{acc.label:<40} saldo {_brl(acc.balance_cents):>25}")

    today = local_date(now)
    month_start = date(today.year, today.month, 1)
    title(f"Movimento do mês ({month_start:%m/%Y}, só transações ativas)")
    for label, inflow, outflow in queries.monthly_flow(session, month_start, today):
        out.append(f"{label:<40} entradas {_brl(inflow):>14} | saídas {_brl(outflow):>14}")

    snapshot_date = queries.latest_snapshot_date(session)
    title(f"Carteira de investimentos (foto de {_d(snapshot_date)})")
    total = 0
    for group in queries.portfolio_by_class(session, snapshot_date) if snapshot_date else []:
        total += group.balance_cents
        out.append(
            f"{group.type!s:<14}{group.subtype!s:<20}{group.positions:>4} ativos {_brl(group.balance_cents):>16}"
        )
    out.append(f"{'TOTAL':<34}{'':>11}{_brl(total):>16}")
    return out


def _brl(cents: int | None) -> str:
    if cents is None:
        return "—"
    text = f"{cents / 100:,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def _dt(value) -> str:
    """DateTime do banco (UTC sem tzinfo) exibido no horário de Brasília."""
    if not value:
        return "—"
    return f"{value.replace(tzinfo=UTC).astimezone(LOCAL_TZ):%Y-%m-%d %H:%M}"


def _d(value) -> str:
    return value.isoformat() if value else "—"
