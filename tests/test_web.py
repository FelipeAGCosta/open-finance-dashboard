"""API da interface local sobre o banco de demonstração (100% sintético)."""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import FakeSource, scenario
from findash.classify.commands import run_classification
from findash.cli import sync_report
from findash.config import Paths
from findash.demo import build_demo
from findash.security import Redactor
from findash.web.app import create_app

AS_OF = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 15, 0)  # UTC sem tzinfo, como no banco
LOCAL = "http://127.0.0.1:8765"
CREDENTIALS = (
    "PLUGGY_CLIENT_ID=client-ficticio\nPLUGGY_CLIENT_SECRET=segredo-ficticio-web-123\n"
    "PLUGGY_ITEM_IDS=00000000-0000-4000-8000-000000000001:nubank\n"
)


@pytest.fixture(scope="module")
def demo_template(tmp_path_factory) -> Paths:
    return build_demo(tmp_path_factory.mktemp("demo"), as_of=AS_OF, now=NOW)


@pytest.fixture
def demo_paths(demo_template, tmp_path) -> Paths:
    """Cópia do banco de demonstração por teste (os testes alteram o banco)."""
    paths = Paths(tmp_path)
    paths.ensure()
    for name in ("findash.db", "regras_pessoais.yaml", "classes_ativos.yaml", "settings.yaml"):
        shutil.copyfile(demo_template.data_dir / name, paths.data_dir / name)
    return paths


def make_client(paths: Paths, **kwargs) -> TestClient:
    kwargs.setdefault("clock", lambda: NOW)
    kwargs.setdefault("market_fetch", None)
    kwargs.setdefault("dist_dir", paths.root / "sem-dist")
    return TestClient(create_app(paths, **kwargs), base_url=LOCAL)


@pytest.fixture
def client(demo_paths) -> TestClient:
    with make_client(demo_paths, sync_runner=lambda paths: (0, ["ok"])) as c:
        yield c


def first_tx(client, month: str, **where):
    data = client.get("/api/expenses", params={"month": month}).json()
    return next(t for t in data["transactions"] if all(t[k] == v for k, v in where.items()))


def test_demo_is_reproducible(tmp_path):
    first = build_demo(tmp_path / "a", as_of=AS_OF, now=NOW)
    second = build_demo(tmp_path / "b", as_of=AS_OF, now=NOW)
    with make_client(first) as a, make_client(second) as b:
        for route in ("/api/overview", "/api/investments", "/api/plan"):
            assert a.get(route).json() == b.get(route).json()


# ---------------------------------------------------------------- leitura


def test_meta_lists_months_and_fixed_category_colors(client):
    meta = client.get("/api/meta").json()
    assert meta["current_month"] == "2026-11" and meta["months"][0] == "2026-11" and not meta["demo"]
    colors = {c["name"]: c["color"] for c in meta["categories"]}
    assert colors.pop("A classificar") == 0  # neutra
    assert sorted(colors.values()) == list(range(1, 19))  # cada categoria com a sua cor, sem repetir


def test_overview(client):
    data = client.get("/api/overview").json()
    worth = data["wealth"]  # patrimônio total = só o investido (+ em trânsito); conta e fatura ficam à parte
    assert worth["total"] == worth["portfolio"] + worth["in_transit"]["cents"]
    assert [(i["date"], i["cents"], i["until"]) for i in worth["in_transit"]["items"]] == [
        ("2026-11-20", 46_250, "2026-11-27")
    ]
    assert len(worth["series"]) == 180 and worth["series"][-1]["total"] == worth["total"]
    assert set(data["accounts"]) == {"date", "bank", "card_bill"} and "net_worth" not in data
    investments = client.get("/api/investments").json()
    plan = client.get("/api/plan").json()
    assert investments["wealth"]["total"] == plan["wealth"]["total"] == worth["total"]  # o mesmo número nas três telas
    bank = investments["bank_view"]  # os grupos do app do banco somam o mesmo patrimônio total
    assert bank["institution"] == "Banco"
    assert [g["label"] for g in bank["groups"]] == ["Renda fixa", "Bolsa de valores", "Tesouro Direto"]
    assert bank["total"] == worth["total"] and bank["in_transit"] == worth["in_transit"]["cents"]
    assert len(data["history"]) == 12 and data["history"][-1]["month"] == "2026-11"
    month = data["month"]
    assert month["result"] == month["income"] + month["investment_income"] - month["expenses"]
    [salary] = month["salaries"]
    assert (salary["paycheck"], salary["schedule"], salary["paydays"], salary["divergent"]) == (
        900_000,
        "todo dia 5",
        1,
        False,
    )
    plan = data["plan"]  # resumo do "Seu aporte deste mês" (o detalhe fica na tela Plano)
    assert (plan["base"], plan["extra"], plan["total"]) == (200_000, 0, 200_000)  # salário mensal: sem pagamento extra
    assert sum(p["planned"] for p in plan["places"]) == plan["total"]
    flows = plan["flows"]  # aportei · resgatei · saldo do mês (nunca só o líquido)
    assert flows["net"] == flows["contributions"] - flows["redemptions"]
    assert plan["remaining"] == max(0, plan["total"] - flows["net"])
    assert data["data_as_of"].endswith("Z") and "capacity" not in data
    # resgate de R$ 3.200 maior que os aportes do mês: alerta "patrimônio encolhendo"
    assert month["flows"]["shrinking"] and any(a["title"] == "Patrimônio encolhendo" for a in data["alerts"])
    # extraordinários à parte (conserto do carro + parcela da viagem), total sempre visível
    assert month["extraordinary"]["cents"] == 98_000 + 61_000
    assert month["everyday"] == month["expenses"] - month["extraordinary"]["cents"]
    assert month["result_everyday"] == month["result"] + month["extraordinary"]["cents"]
    inv = data["investments_month"]  # variação = aportes − resgates + rendimento
    assert inv["change"] == inv["net_flows"] + inv["growth"]
    assert any(a["target"] == "expenses" for a in data["alerts"])  # há gastos 'A classificar' no mês
    assert client.get("/api/overview", params={"month": "2026-10"}).json()["month"]["month"] == "2026-10"
    assert client.get("/api/overview", params={"month": "out/2026"}).status_code == 422


def test_in_transit_manual_choice_persists_and_undoes(client):
    transit = client.get("/api/overview").json()["wealth"]["in_transit"]
    [item] = transit["items"]
    assert (
        transit["assets"] and client.put(f"/api/in-transit/{item['id']}", json={"action": "chegou"}).status_code == 422
    )
    asset = transit["assets"][0]["id"]
    body = client.put(f"/api/in-transit/{item['id']}", json={"action": "chegou", "investment_id": asset}).json()
    after = client.get("/api/overview").json()["wealth"]
    assert after["in_transit"]["cents"] == 0 and after["total"] == after["portfolio"]  # "já chegou": sai do total
    assert client.post("/api/undo", json=body["undo"]).json()["ok"]
    assert client.get("/api/overview").json()["wealth"]["in_transit"]["cents"] == item["cents"]
    client.put(f"/api/in-transit/{item['id']}", json={"action": "ignorar"})
    assert client.get("/api/investments").json()["wealth"]["in_transit"]["items"] == []
    assert client.put("/api/in-transit/nao-existe", json={"action": "ignorar"}).status_code == 404


def test_expenses_lists_transactions_with_the_rule_that_classified_them(client):
    data = client.get("/api/expenses", params={"month": "2026-10"}).json()
    assert data["total"] == sum(c["cents"] for c in data["by_category"])
    assert data["fixed"]["fixed"] + data["fixed"]["variable"] == data["total"]
    rent = first_tx(client, "2026-10", counterparty="ADMINISTRADORA LAR DOCE")
    assert (rent["category"], rent["rule_level"], rent["account"], rent["is_fixed"]) == (
        "Moradia",
        "pessoal",
        "conta",
        True,
    )
    assert rent["rule_pattern"] and rent["fixed_source"] == "regra" and rent["source"] == "regra_pessoal"
    assert rent["kind_options"] == ["despesa", "emprestimo_concedido"] and "rule_detail" not in rent
    loan = next(t for t in data["transactions"] if t["movement_type"] == "devolucao_emprestimo")
    assert loan["source"] == "manual" and loan["kind_options"][0] == "receita"
    assert data["loans"] == [
        {
            "key": "RENATOFARIAS",
            "counterparty": "RENATO FARIAS",
            "lent": 80_000,
            "returned": 30_000,
            "open": 50_000,
            "last_date": "2026-10-17",
        }
    ]
    nov = client.get("/api/expenses", params={"month": "2026-11"}).json()
    assert nov["reimbursements"] == 6_400
    assert nov["fixed"]["fixed"] == client.get("/api/fixed").json()["month"]["paid"]  # uma fonte de verdade
    assert sorted(t["installment"] for t in data["transactions"] if t["installment"]) == ["2/3", "6/10"]


def test_transfer_from_the_owner_is_internal(client):
    own = first_tx(client, "2026-11", counterparty="PESSOA DEMONSTRACAO")
    assert own["movement_type"] == "transferencia_interna"


def test_fixed_and_commitments(client):
    data = client.get("/api/fixed").json()
    names = {r["counterparty"] for r in data["fixed"]}
    assert {"CINEMAX PLAY", "ADMINISTRADORA LAR DOCE", "PLANO DE SAUDE VIDA DEMO"} <= names
    assert all(r["status"] == "automatico" and r["active"] for r in data["fixed"])
    states = {r["counterparty"]: r["state"] for r in data["fixed"]}
    assert states.pop("REVISTA SEMANAL DIGITAL") == "inativo" and set(states.values()) == {"ativo"}
    assert data["fixed_monthly"] == sum(r["avg_monthly"] for r in data["fixed"] if r["state"] == "ativo")
    assert data["month"]["paid"] + data["month"]["pending"] > 0
    [salary] = data["salary"]
    assert (salary["paycheck"], salary["schedule"], salary["annual_average"]) == (900_000, "todo dia 5", 900_000)
    assert salary["last_payment"] == {"date": "2026-11-05", "cents": 900_000}
    assert data["commitments"]["total"] == sum(m["cents"] for m in data["commitments"]["months"]) > 0


def test_investments(client):
    data = client.get("/api/investments").json()
    assert data["total"] == sum(a["cents"] for a in data["allocation"]) == sum(a["balance"] for a in data["assets"])
    assert data["total"] == sum(g["cents"] for g in data["allocation_by_place"])
    assert [g["place"] for g in data["allocation_by_place"]] == ["reserva", "patrimonio"]
    assert data["total_net"] < data["total"]  # bruto é o principal; o líquido desconta o IR da renda fixa
    assert {a["class"] for a in data["allocation"]} == {
        "Tesouro",
        "CDB/RDB",
        "Ações",
        "FIIs",
        "BDR",
        "ETF Brasil",
        "ETF Global",
    }
    monthly = data["monthly"]["months"]
    assert monthly[0]["partial_since"] and monthly[-1]["in_progress"] and monthly[-1]["month"] == "2026-11"
    for m in monthly:
        assert m["gain"] == m["end_value"] - m["start_value"] - m["contributions"] + m["redemptions"] + m["income"]
    by_class = data["dividends"]["by_class"]
    assert len(by_class) == 12 and sum(m["total"] for m in by_class) == data["dividends"]["total"]
    assert data["data_as_of"].endswith("Z")
    orbi = next(a for a in data["assets"] if a["code"] == "ORBI3")
    assert orbi["variation"]["bought"] > 0  # compras do período não contam como valorização
    assert orbi["variation"]["since"] == "2026-05-25" and orbi["variation"]["pct"] is not None  # 1ª das 180 fotos
    perf = data["performance"]
    assert perf["enough"] and perf["days"] == 180 and perf["series"][0]["twr"] == 0
    assert perf["accumulated"]["cdi"] > 0 and perf["accumulated"]["twr"] == pytest.approx(perf["series"][-1]["twr"])
    assert {f["class"] for f in data["fixed_income"]} == {"Tesouro", "CDB/RDB"}
    assert data["dividends"]["total"] > 0 and len(data["dividends"]["by_month"]) == 12


def test_status(client):
    data = client.get("/api/status").json()
    assert data["last_run"]["status"] == "success" and data["snapshots"]["days"] == 180
    assert data["items"][0]["consent_days"] == 240 and data["items"][0]["consent_warning"] is None
    assert data["sync_enabled"] and not data["sync_running"]
    assert "segredo" not in str(data)


# ---------------------------------------------------------------- ações


def test_patch_transaction_category_and_fixed_survive_reclassification_and_sync(demo_paths):
    (demo_paths.root / ".env").write_text(CREDENTIALS, encoding="utf-8")

    def real_sync(paths):
        return sync_report(paths, source_factory=lambda s, r: FakeSource(scenario(1)), redactor=Redactor())

    with make_client(demo_paths, sync_runner=real_sync) as client:
        pending = first_tx(client, "2026-10", category="A classificar")
        assert not pending["is_fixed"]
        body = client.patch(
            f"/api/transactions/{pending['id']}", json={"category": "Compras online", "fixed": True}
        ).json()
        assert body["transaction"]["category"] == "Compras online" and body["transaction"]["rule_level"] == "override"
        assert body["transaction"]["is_fixed"] and body["transaction"]["fixed_source"] == "transacao"
        rent = first_tx(client, "2026-10", counterparty="ADMINISTRADORA LAR DOCE")
        assert (
            client.patch(f"/api/transactions/{rent['id']}", json={"fixed": False}).json()["transaction"]["is_fixed"]
            is False
        )

        run_classification(demo_paths, client.app.state.ctx.session_factory, now=NOW)  # recálculo
        sync = client.post("/api/sync").json()  # sincronização de verdade (Pluggy falsa) + reclassificação
        assert sync["ok"], sync
        after = first_tx(client, "2026-10", id=pending["id"])
        assert (after["category"], after["is_fixed"]) == ("Compras online", True)
        assert first_tx(client, "2026-10", id=rent["id"])["is_fixed"] is False

        # null remove só aquele campo do override; sem nada, a transação volta a seguir as regras
        client.patch(f"/api/transactions/{pending['id']}", json={"category": None, "fixed": None})
        restored = first_tx(client, "2026-10", id=pending["id"])
        assert (restored["category"], restored["is_fixed"], restored["override"]) == ("A classificar", False, None)

        assert client.patch(f"/api/transactions/{pending['id']}", json={"category": "Inexistente"}).status_code == 422
        assert client.patch(f"/api/transactions/{pending['id']}", json={}).status_code == 422
        assert client.patch("/api/transactions/nao-existe", json={"fixed": True}).status_code == 404


def test_patch_recurring_rule_manual_choice_wins_and_persists(client, demo_paths):
    rule = next(r for r in client.get("/api/fixed").json()["fixed"] if r["counterparty"] == "CINEMAX PLAY")
    before = client.get("/api/fixed").json()["fixed_monthly"]
    updated = client.patch(f"/api/recurring/{rule['id']}", json={"mode": "nao"}).json()["rule"]
    assert (updated["status"], updated["active"], updated["manual"]) == ("manual_nao", False, True)
    assert client.get("/api/fixed").json()["fixed_monthly"] == before - rule["avg_monthly"]
    run_classification(demo_paths, client.app.state.ctx.session_factory, now=NOW)
    again = next(r for r in client.get("/api/fixed").json()["fixed"] if r["id"] == rule["id"])
    assert again["status"] == "manual_nao"  # o desmarcado não volta a ser automático
    assert first_tx(client, "2026-10", counterparty="CINEMAX PLAY")["is_fixed"] is False
    assert client.patch(f"/api/recurring/{rule['id']}", json={"mode": "auto"}).json()["rule"]["active"]
    assert client.patch(f"/api/recurring/{rule['id']}", json={"mode": "talvez"}).status_code == 422
    assert client.patch("/api/recurring/99999", json={"mode": "sim"}).status_code == 404


def test_classify_with_counterparty_scope_and_undo(client, demo_paths):
    tx = first_tx(client, "2026-10", counterparty="PADARIA TRIGO BOM")
    others = [
        t
        for t in client.get("/api/expenses", params={"month": "2026-09"}).json()["transactions"]
        if t["counterparty"] == "PADARIA TRIGO BOM"
    ]
    body = client.post(
        f"/api/transactions/{tx['id']}/classify",
        json={"scope": "counterparty", "category": "Alimentação fora e delivery"},
    ).json()
    assert body["transaction"]["category"] == "Alimentação fora e delivery"
    assert body["transaction"]["source"] == "regra_pessoal" and body["affected"] > 50
    assert all(first_tx(client, "2026-09", id=t["id"])["category"] == "Alimentação fora e delivery" for t in others)
    assert "PADARIA TRIGO BOM" in demo_paths.personal_rules_path.read_text(encoding="utf-8")
    assert client.post("/api/undo", json=body["undo"]).json()["ok"]
    assert first_tx(client, "2026-10", id=tx["id"])["category"] == tx["category"]
    assert "PADARIA TRIGO BOM" not in demo_paths.personal_rules_path.read_text(encoding="utf-8")

    gym = first_tx(client, "2026-10", counterparty="ACADEMIA FORCA TOTAL")
    before = client.get("/api/fixed").json()
    body = client.post(f"/api/transactions/{gym['id']}/classify", json={"scope": "counterparty", "fixed": False}).json()
    after = client.get("/api/fixed").json()
    assert not body["transaction"]["is_fixed"] and after["fixed_monthly"] < before["fixed_monthly"]
    client.post("/api/undo", json=body["undo"])
    assert client.get("/api/fixed").json()["fixed_monthly"] == before["fixed_monthly"]

    pix = first_tx(client, "2026-10", account="conta", movement_type="despesa", counterparty_kind="PF")
    body = client.post(f"/api/transactions/{pix['id']}/classify", json={"scope": "one", "kind": "emprestimo_concedido"})
    assert body.json()["transaction"]["movement_type"] == "emprestimo_concedido"
    card = first_tx(client, "2026-10", account="cartao", movement_type="despesa")
    bad = client.post(f"/api/transactions/{card['id']}/classify", json={"scope": "one", "kind": "emprestimo_concedido"})
    assert bad.status_code == 422
    assert (
        client.post(f"/api/transactions/{card['id']}/classify", json={"scope": "todas", "fixed": True}).status_code
        == 422
    )


def test_plan_reserve_patrimony_and_checklist(client):
    plan = client.get("/api/plan").json()
    target = plan["settings"]["aporte_mensal"]
    assert target["value"] == {"cents": 200_000, "extra_paycheck": False}
    assert [h["effective_month"] for h in target["history"]] == ["2026-01", "2026-08"]  # histórico preservado
    assert target["history"][0]["value"]["cents"] == 150_000

    reserve = plan["reserve"]  # valor fixo de R$ 18.000, completo com a renda fixa
    assert reserve["target"] == 1_800_000 and reserve["current"] == 1_800_000 and reserve["complete"]
    assert reserve["covered_months"] == pytest.approx(1_800_000 / reserve["essential_average"])
    # cada real em um lugar só, e só existem dois lugares
    assert [p["place"] for p in plan["places"]] == ["reserva", "patrimonio"]
    assert sum(p["cents"] for p in plan["places"]) == sum(h["value"] for h in plan["holdings"])
    assert all(sum(part["cents"] for part in h["parts"]) == h["value"] for h in plan["holdings"])

    contribution = plan["contribution"]
    # Reserva completa: a meta inteira vai para o Patrimônio
    assert not contribution["extra"]["active"] and contribution["total"] == 200_000
    assert contribution["places"] == [
        {"place": "patrimonio", "label": "Patrimônio", "color": "var(--goal-patrimonio)", "planned": 200_000}
    ]
    checklist = contribution["checklist"]
    assert 1 <= len(checklist) <= 5 and sum(line["amount"] for line in checklist) == 200_000
    assert all(isinstance(line["done"], bool) for line in checklist) and contribution["invested"] >= 0
    assert contribution["next"] is None  # dia 20: a prévia do mês seguinte só aparece nos últimos 5 dias

    patrimony = plan["patrimony"]
    buckets = {b["bucket"]: b for b in patrimony["buckets"]}
    assert list(buckets) == [
        "renda_fixa",
        "etf_global",
        "etf_brasil",
        "acoes_nucleo",
        "fiis",
        "acoes_mantidas",
        "satelite",
    ]
    assert not buckets["fiis"]["suggested"] and not buckets["satelite"]["suggested"]
    assert not buckets["acoes_mantidas"]["suggested"] and buckets["acoes_mantidas"]["target_pct"] is None
    assert patrimony["off_target"] == sum(b["state"] in ("abaixo", "acima", "acima_teto") for b in patrimony["buckets"])
    roles = {h["ticker"]: h["role"] for h in plan["holdings"] if h["role"]}
    assert roles == {"ORBI3": "nucleo", "TERA3": "nucleo", "PRIS4": "manter", "KORA3": "manter", "NEBU34": "satelite"}
    assert sorted(m["label"] for m in buckets["acoes_mantidas"]["members"]) == ["KORA3", "PRIS4"]
    items = contribution["patrimony"]["items"]
    assert all(i["bucket"] in ("renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo") for i in items)
    assert not {i["ticker"] for i in items} & {"PRIS4", "KORA3", "NEBU34"}  # manter e satélite nunca recebem aporte
    assert sum(i["spend"] for i in items) + contribution["patrimony"]["leftover"] == contribution["patrimony"]["amount"]
    assert {c["ticker"] for c in patrimony["core"]} == {"ORBI3", "TERA3"}
    assert plan["returns"] == {"assumed": 0.10, "aspirational": 0.12}
    assert plan["data_stale_hours"] is None


def test_stock_role_and_core_weights_settings(client):
    value = {
        "tickers": ["ORBI3", "TERA3", "PRIS4"],
        "satellite": ["NEBU34"],
        "weights": "personalizado",
        "custom": {"ORBI3": 50, "TERA3": 30, "PRIS4": 20},
    }
    saved = client.post("/api/plan/settings", json={"key": "nucleo", "effective_month": "2026-11", "value": value})
    assert saved.status_code == 200 and saved.json()["unchanged"] is False
    plan = client.get("/api/plan").json()
    assert plan["patrimony"]["core_weights"] == "personalizado"
    assert {c["ticker"]: c["weight"] for c in plan["patrimony"]["core"]} == {
        "ORBI3": pytest.approx(0.5),
        "TERA3": pytest.approx(0.3),
        "PRIS4": pytest.approx(0.2),
    }
    bad = client.post(
        "/api/plan/settings",
        json={"key": "nucleo", "effective_month": "2026-11", "value": {**value, "custom": {"ORBI3": 50, "TERA3": 30}}},
    )
    assert bad.status_code == 422 and "cada empresa" in bad.json()["detail"]


def test_saving_the_same_setting_twice_records_nothing(client):
    before = client.get("/api/plan").json()["settings"]["alvo_patrimonio"]
    again = client.post(
        "/api/plan/settings", json={"key": "alvo_patrimonio", "effective_month": "2026-11", "value": before["value"]}
    ).json()
    assert again == {"id": None, "unchanged": True, "undo": None}
    assert client.get("/api/plan").json()["settings"]["alvo_patrimonio"]["history"] == before["history"]


def test_stale_pluggy_data_alert(demo_paths):
    # o demo tem dado de 3 h atrás: sem alerta; 40 h depois (sem nova atualização da Pluggy), o alerta aparece
    with make_client(demo_paths) as client:
        assert client.get("/api/status").json()["items"][0]["stale_hours"] is None
        assert all("desatualizados" not in a["title"] for a in client.get("/api/overview").json()["alerts"])
    with make_client(demo_paths, clock=lambda: NOW + timedelta(hours=40)) as client:
        assert client.get("/api/status").json()["items"][0]["stale_hours"] == 43
        alert = next(a for a in client.get("/api/overview").json()["alerts"] if "desatualizados" in a["title"])
        assert alert["target"] == "status" and "43 horas" in alert["detail"]
        assert client.get("/api/plan").json()["data_stale_hours"] == 43


def test_plan_settings_and_investment_place_with_undo(client):
    saved = client.post(
        "/api/plan/settings", json={"key": "aporte_mensal", "effective_month": "2026-12", "value": {"cents": 250_000}}
    ).json()
    assert client.get("/api/plan").json()["settings"]["aporte_mensal"]["value"]["cents"] == 200_000  # vale em dez.
    client.post("/api/undo", json=saved["undo"])
    assert len(client.get("/api/plan").json()["settings"]["aporte_mensal"]["history"]) == 2
    bad = client.post(
        "/api/plan/settings",
        json={
            "key": "alvo_patrimonio",
            "effective_month": "2026-11",
            "value": {
                "classes": {
                    "renda_fixa": 50,
                    "etf_global": 10,
                    "etf_brasil": 10,
                    "acoes_nucleo": 10,
                    "fiis": 10,
                    "satelite": 0,
                }
            },
        },
    )
    assert bad.status_code == 422 and "100%" in bad.json()["detail"]

    plan = client.get("/api/plan").json()
    holding = next(h for h in plan["holdings"] if h["class"] == "Tesouro")
    moved = client.put(f"/api/investments/{holding['investment_id']}/place", json={"place": "patrimonio"}).json()
    after = next(
        h for h in client.get("/api/plan").json()["holdings"] if h["investment_id"] == holding["investment_id"]
    )
    assert after["place"] == "patrimonio" and after["manual"] and after["reason"] == "escolha sua"
    client.post("/api/undo", json=moved["undo"])
    again = next(
        h for h in client.get("/api/plan").json()["holdings"] if h["investment_id"] == holding["investment_id"]
    )
    assert not again["manual"]
    assert client.put(f"/api/investments/{holding['investment_id']}/place", json={"place": "outro"}).status_code == 422
    assert client.put("/api/investments/nao-existe/place", json={"place": "reserva"}).status_code == 404


def test_classify_extraordinary_from_the_list_with_undo(client):
    tx = first_tx(client, "2026-10", category="Mercado")
    result = client.post(f"/api/transactions/{tx['id']}/classify", json={"scope": "one", "extraordinary": True}).json()
    assert result["transaction"]["extraordinary"] and result["transaction"]["source"] == "manual"
    month = client.get("/api/expenses", params={"month": "2026-10"}).json()
    assert month["extraordinary"]["cents"] >= -tx["amount"]
    assert month["everyday"] + month["extraordinary"]["cents"] == month["total"]
    client.post("/api/undo", json=result["undo"])
    assert not first_tx(client, "2026-10", id=tx["id"])["extraordinary"]


def test_investments_show_aspirational_target_line(client):
    data = client.get("/api/investments").json()
    assert data["aspirational"] == 0.12
    series = data["performance"]["series"]
    assert series[0]["target"] == 0 and series[-1]["target"] > 0
    assert data["performance"]["accumulated"]["above_target"] in (True, False)


def test_sync_disabled_in_demo_mode(demo_paths):
    with make_client(demo_paths, demo=True) as client:
        assert client.get("/api/meta").json()["demo"] is True
        response = client.post("/api/sync")
        assert response.status_code == 409 and "demonstração" in response.json()["detail"]


# ---------------------------------------------------------------- segurança e frontend


@pytest.mark.parametrize("host", ["evil.example.com", "127.0.0.1.evil.example.com", "192.168.0.10:8765"])
def test_rejects_non_local_host(demo_paths, host):
    with make_client(demo_paths) as client:
        response = client.get("/api/meta", headers={"host": host})
        assert response.status_code == 403


def test_rejects_cross_origin_requests(client):
    tx = first_tx(client, "2026-10", category="A classificar")
    evil = client.patch(
        f"/api/transactions/{tx['id']}", json={"fixed": True}, headers={"origin": "https://evil.example.com"}
    )
    assert evil.status_code == 403
    assert first_tx(client, "2026-10", id=tx["id"])["is_fixed"] is False
    assert (
        client.get("/api/meta", headers={"origin": "http://localhost:5173", "host": "localhost:8765"}).status_code
        == 200
    )


def test_frontend_is_served_when_built(demo_paths, tmp_path):
    with make_client(demo_paths) as client:
        assert "compilado" in client.get("/").text  # sem build: instrução clara
        assert client.get("/api/nao-existe").status_code == 404
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Painel</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with make_client(demo_paths, dist_dir=dist) as client:
        assert "<title>Painel</title>" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
