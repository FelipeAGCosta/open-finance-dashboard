"""Aplicação FastAPI: API JSON da interface local + arquivos do frontend compilado (frontend/dist).

Toda a lógica de negócio continua nos pacotes classify/ e invest/; aqui só se monta JSON e se
disparam as ações já existentes (override, regra de recorrência, sincronização).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from findash.classify.actions import ActionError, Change, apply_change, counterparty_count, undo_change
from findash.classify.commands import run_classification
from findash.classify.recurrence import apply_fixed_flags, set_status
from findash.classify.rules import RulesError, load_category_colors, load_rulebook
from findash.config import PROJECT_ROOT, Paths, local_date, utcnow
from findash.db.base import make_engine, make_session_factory
from findash.db.migrate import upgrade_to_head
from findash.db.models import (
    ClassificationOverride,
    Investment,
    InvestmentSnapshot,
    RecurringRule,
    Transaction,
    TransactionClassification,
)
from findash.invest import market, transit_choices
from findash.invest.classes import ClassesError, ClassMap, ensure_personal_file, load_class_map
from findash.plan import settings as plan_settings
from findash.plan.places import set_place
from findash.settings import SettingsError, load_app_settings
from findash.web.security import LocalOnlyMiddleware
from findash.web.views import expenses as expenses_view
from findash.web.views import fixed as fixed_view
from findash.web.views import investments as investments_view
from findash.web.views import overview as overview_view
from findash.web.views import plan as plan_view
from findash.web.views import status as status_view
from findash.web.views.common import available_months

log = logging.getLogger("findash.web")

DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
MARKET_REFRESH_EVERY = timedelta(hours=6)
SyncRunner = Callable[[Paths], tuple[int, list[str]]]


@dataclass
class AppContext:
    paths: Paths
    engine: Engine
    session_factory: sessionmaker
    demo: bool = False
    sync_runner: SyncRunner | None = None
    market_fetch: market.Fetcher | None = None
    clock: Callable[[], datetime] = utcnow
    sync_lock: threading.Lock = field(default_factory=threading.Lock)
    market_refreshed_at: datetime | None = None


class TransactionPatch(BaseModel):
    category: str | None = None
    fixed: bool | None = None


class RulePatch(BaseModel):
    mode: str  # auto | sim | nao


class ClassifyBody(BaseModel):
    scope: str  # one | counterparty
    category: str | None = None
    fixed: bool | None = None
    kind: str | None = None
    extraordinary: bool | None = None


class UndoBody(BaseModel):
    kind: str  # transaction | plan_setting | investment_place | in_transit
    payload: dict


class PlanSettingBody(BaseModel):
    key: str
    effective_month: str
    value: dict


class InTransitBody(BaseModel):
    action: str | None = None  # chegou | ignorar | None (automático)
    investment_id: str | None = None


class PlaceBody(BaseModel):
    place: str | None = None  # reserva | patrimonio | None (automático)


def _default_sync(paths: Paths) -> tuple[int, list[str]]:
    from findash.cli import sync_report

    return sync_report(paths)


def create_app(
    paths: Paths,
    *,
    demo: bool = False,
    sync_runner: SyncRunner | None = _default_sync,
    market_fetch: market.Fetcher | None = market.fetch_sgs,
    dist_dir: Path = DIST_DIR,
    clock: Callable[[], datetime] = utcnow,
) -> FastAPI:
    engine = make_engine(paths.db_path)
    upgrade_to_head(engine)
    ctx = AppContext(
        paths,
        engine,
        make_session_factory(engine),
        demo=demo,
        sync_runner=None if demo else sync_runner,
        market_fetch=None if demo else market_fetch,
        clock=clock,
    )
    app = FastAPI(title="Finanças", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.add_middleware(LocalOnlyMiddleware)

    def today():
        return local_date(ctx.clock())

    # ------------------------------------------------------------------ leitura

    @app.get("/api/meta")
    def meta() -> dict:
        with ctx.session_factory() as session:
            book = load_rulebook(ctx.paths.config_dir, ctx.paths.personal_rules_path)
            colors = load_category_colors(ctx.paths.config_dir / "categorias.yaml")
            return {
                "demo": ctx.demo,
                "today": today().isoformat(),
                "current_month": f"{today():%Y-%m}",
                "months": available_months(session),
                "categories": [
                    {"name": name, "essential": essential, "color": colors.get(name)}
                    for name, essential in book.categories.items()
                ],
                "sync_enabled": ctx.sync_runner is not None,
            }

    @app.get("/api/overview")
    def overview(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> dict:
        class_map = _class_map()
        with ctx.session_factory() as session:
            summary = plan_view.overview_summary(_plan(session, class_map, with_history=False))
            return overview_view.overview(
                session,
                today=today(),
                now=ctx.clock(),
                month=month,
                plan_summary=summary,
                data_as_of=plan_view.data_as_of(session),
            )

    @app.get("/api/expenses")
    def expenses(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> dict:
        with ctx.session_factory() as session:
            return expenses_view.expenses(session, month or f"{today():%Y-%m}", today=today())

    @app.get("/api/fixed")
    def fixed() -> dict:
        with ctx.session_factory() as session:
            return fixed_view.fixed(session, today=today())

    @app.get("/api/investments")
    def investments() -> dict:
        class_map = _class_map()
        with ctx.session_factory() as session:
            _refresh_market(session)
            return investments_view.investments(session, class_map, today=today())

    @app.get("/api/plan")
    def plan() -> dict:
        class_map = _class_map()
        with ctx.session_factory() as session:
            return _plan(session, class_map)

    @app.get("/api/status")
    def status() -> dict:
        with ctx.session_factory() as session:
            data = status_view.status(session, now=ctx.clock(), demo=ctx.demo)
        data["sync_enabled"] = ctx.sync_runner is not None
        data["sync_running"] = ctx.sync_lock.locked()
        return data

    # ------------------------------------------------------------------ ações

    @app.patch("/api/transactions/{transaction_id}")
    def patch_transaction(transaction_id: str, body: TransactionPatch) -> dict:
        fields = body.model_fields_set
        if not fields & {"category", "fixed"}:
            raise HTTPException(status_code=422, detail="Informe 'category' e/ou 'fixed'.")
        try:
            book = load_rulebook(ctx.paths.config_dir, ctx.paths.personal_rules_path)
        except RulesError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        if "category" in fields and body.category is not None and body.category not in book.categories:
            raise HTTPException(status_code=422, detail=f"Categoria '{body.category}' não existe.")
        now = ctx.clock()
        with ctx.session_factory() as session:
            if session.get(Transaction, transaction_id) is None:
                raise HTTPException(status_code=404, detail="Transação não encontrada.")
            override = session.get(ClassificationOverride, transaction_id)
            if override is None:
                override = ClassificationOverride(transaction_id=transaction_id, created_at=now, updated_at=now)
                session.add(override)
            if "category" in fields:
                override.category = body.category
            if "fixed" in fields:
                override.fixed = body.fixed
            override.updated_at = now
            if (
                override.category is None
                and override.fixed is None
                and override.movement_type is None
                and override.essential is None
                and override.extraordinary is None
                and not override.note
            ):
                session.delete(override)  # nada sobrou: volta a seguir as regras
            session.commit()
        try:
            run_classification(ctx.paths, ctx.session_factory, now=now)
        except (RulesError, SettingsError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        with ctx.session_factory() as session:
            return {"transaction": expenses_view.single_transaction(session, transaction_id)}

    @app.post("/api/transactions/{transaction_id}/classify")
    def classify_transaction(transaction_id: str, body: ClassifyBody) -> dict:
        """Categoria, fixo ou tipo de movimento, com escopo 'só esta' ou 'toda a contraparte'."""
        fields = frozenset(body.model_fields_set & {"category", "fixed", "kind", "extraordinary"})
        if not fields:
            raise HTTPException(status_code=422, detail="Informe o que mudar.")
        book = _rulebook()
        now = ctx.clock()
        change = Change(body.scope, body.category, body.fixed, body.kind, fields, body.extraordinary)
        with ctx.session_factory() as session:
            try:
                undo = apply_change(
                    session, ctx.paths.personal_rules_path, transaction_id, change, categories=book.categories, now=now
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from None
            except (ActionError, RulesError) as exc:
                session.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from None
            session.commit()
        _reclassify(now)
        with ctx.session_factory() as session:
            tx = expenses_view.single_transaction(session, transaction_id)
            direction = "entrada" if tx and tx["amount"] > 0 else "saida"
            cp_key = session.scalar(
                select(TransactionClassification.counterparty_key).where(
                    TransactionClassification.transaction_id == transaction_id
                )
            )
            affected = counterparty_count(session, cp_key, direction) if body.scope == "counterparty" else 1
        return {"transaction": tx, "affected": affected, "undo": {"kind": "transaction", "payload": undo}}

    @app.post("/api/undo")
    def undo(body: UndoBody) -> dict:
        now = ctx.clock()
        with ctx.session_factory() as session:
            try:
                if body.kind == "transaction":
                    undo_change(session, ctx.paths.personal_rules_path, body.payload, now=now)
                elif body.kind == "plan_setting":
                    if not plan_settings.delete(session, int(body.payload.get("id") or 0)):
                        raise LookupError("Essa mudança já foi desfeita.")
                elif body.kind == "investment_place":
                    previous = body.payload.get("previous")
                    if previous is not None and not isinstance(previous, str):
                        raise ActionError("Pacote de desfazer inválido.")
                    set_place(session, str(body.payload.get("investment_id") or ""), previous, now=now)
                elif body.kind == "in_transit":
                    previous = body.payload.get("previous") or {}
                    if not isinstance(previous, dict):
                        raise ActionError("Pacote de desfazer inválido.")
                    transit_choices.set_choice(
                        session,
                        str(body.payload.get("transaction_id") or ""),
                        previous.get("action"),
                        previous.get("investment_id"),
                        now=now,
                    )
                else:
                    raise ActionError("Pacote de desfazer inválido.")
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from None
            except (ActionError, RulesError, ValueError) as exc:
                session.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from None
            session.commit()
        if body.kind == "transaction":
            _reclassify(now)
        return {"ok": True}

    @app.post("/api/plan/settings")
    def save_plan_setting(body: PlanSettingBody) -> dict:
        with ctx.session_factory() as session:
            try:
                row = plan_settings.save(session, body.key, body.effective_month, body.value, now=ctx.clock())
            except plan_settings.PlanError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            if row is None:  # o valor já era esse: nada gravado, nada a desfazer
                return {"id": None, "unchanged": True, "undo": None}
            session.commit()
            return {"id": row.id, "unchanged": False, "undo": {"kind": "plan_setting", "payload": {"id": row.id}}}

    @app.put("/api/investments/{investment_id}/place")
    def put_place(investment_id: str, body: PlaceBody) -> dict:
        with ctx.session_factory() as session:
            if session.get(Investment, investment_id) is None:
                raise HTTPException(status_code=404, detail="Investimento não encontrado.")
            try:
                previous = set_place(session, investment_id, body.place, now=ctx.clock())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            session.commit()
        return {"undo": {"kind": "investment_place", "payload": {"investment_id": investment_id, "previous": previous}}}

    @app.put("/api/in-transit/{transaction_id}")
    def put_in_transit(transaction_id: str, body: InTransitBody) -> dict:
        """Compra em trânsito: 'chegou' (é o ativo X), 'ignorar' ou automático (None). A escolha persiste."""
        with ctx.session_factory() as session:
            try:
                previous = transit_choices.set_choice(
                    session, transaction_id, body.action, body.investment_id, now=ctx.clock()
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from None
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            session.commit()
        return {
            "undo": {
                "kind": "in_transit",
                "payload": {"transaction_id": transaction_id, "previous": previous.as_dict() if previous else None},
            }
        }

    @app.patch("/api/recurring/{rule_id}")
    def patch_rule(rule_id: int, body: RulePatch) -> dict:
        status_value = fixed_view.MODE_TO_STATUS.get(body.mode)
        if status_value is None:
            raise HTTPException(status_code=422, detail="mode deve ser 'auto', 'sim' ou 'nao'.")
        with ctx.session_factory() as session:
            rule = set_status(session, rule_id, status_value, now=ctx.clock())
            if rule is None:
                raise HTTPException(status_code=404, detail="Regra não encontrada.")
            apply_fixed_flags(session)
            session.commit()
            return {"rule": fixed_view.rule_json(session, session.get(RecurringRule, rule_id))}

    @app.post("/api/sync")
    def sync() -> JSONResponse:
        if ctx.sync_runner is None:
            return JSONResponse(status_code=409, content={"detail": "Sincronização desativada no modo demonstração."})
        if not ctx.sync_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={"detail": "Já existe uma sincronização em andamento."})
        try:
            code, lines = ctx.sync_runner(ctx.paths)
        finally:
            ctx.sync_lock.release()
        return JSONResponse(status_code=200, content={"ok": code == 0, "code": code, "lines": lines})

    # ------------------------------------------------------------------ frontend

    @app.get("/api/{rest:path}", include_in_schema=False)
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Rota da API não existe."})

    index = dist_dir / "index.html"
    if index.exists():

        @app.get("/", include_in_schema=False)
        def root() -> FileResponse:
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        app.mount("/", StaticFiles(directory=dist_dir), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def missing_frontend() -> HTMLResponse:
            return HTMLResponse(
                "<h1>Finanças</h1><p>O frontend ainda não foi compilado. Rode "
                "<code>npm --prefix frontend ci</code> e <code>npm --prefix frontend run build</code>.</p>"
            )

    def _class_map() -> ClassMap:
        try:
            ensure_personal_file(ctx.paths.asset_classes_path)
            return load_class_map(ctx.paths.config_dir, ctx.paths.asset_classes_path)
        except ClassesError as exc:
            raise HTTPException(status_code=500, detail=f"Classes de ativos: {exc}") from None

    def _rulebook():
        try:
            return load_rulebook(ctx.paths.config_dir, ctx.paths.personal_rules_path)
        except RulesError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None

    def _reclassify(now: datetime) -> None:
        try:
            run_classification(ctx.paths, ctx.session_factory, now=now)
        except (RulesError, SettingsError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None

    def _plan(session, class_map: ClassMap, *, with_history: bool = True) -> dict:
        try:
            defaults = load_app_settings(ctx.paths).plan
            plan_settings.ensure_initial(session, f"{today():%Y-%m}", defaults, now=ctx.clock())
        except (SettingsError, plan_settings.PlanError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        session.commit()
        return plan_view.plan(session, class_map, today=today(), now=ctx.clock(), with_history=with_history)

    def _refresh_market(session) -> None:
        if ctx.market_fetch is None:
            return
        now = ctx.clock()
        if ctx.market_refreshed_at and now - ctx.market_refreshed_at < MARKET_REFRESH_EVERY:
            return
        first = session.scalar(select(func.min(InvestmentSnapshot.snapshot_date)))
        if first is None:
            return
        try:
            update = market.refresh(session, first - timedelta(days=7), today(), now=now, fetch=ctx.market_fetch)
            session.commit()
            for warning in update.warnings:
                log.warning(warning)
        except Exception as exc:  # o painel funciona com o cache mesmo sem rede
            session.rollback()
            log.warning("Atualização do CDI/IPCA falhou: %s", exc)
        ctx.market_refreshed_at = now

    return app
