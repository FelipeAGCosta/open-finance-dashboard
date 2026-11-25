"""Classificação que aprende (escopo só esta / toda a contraparte), tipos neutros e fixos.

Dados 100% sintéticos (nomes e valores inventados).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
import yaml
from sqlalchemy import select

from findash.classify.actions import ActionError, Change, apply_change, undo_change
from findash.classify.fixed import ACTIVE, INACTIVE, OFF, fixed_month
from findash.classify.loans import open_loans
from findash.classify.personal_rules import RULE_NAME, read_managed, set_counterparty_rule
from findash.classify.rules import RulesError, load_rulebook
from findash.classify.summary import month_summary
from findash.db.models import RULE_YES, ClassificationOverride, RecurringRule, TransactionClassification
from ledger import BANK, CARD, CONFIG_DIR, Ledger, company, person

NOW = datetime(2026, 11, 20, 12, 0)
TODAY = date(2026, 11, 20)


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def cls(session_factory, tx_id: str) -> TransactionClassification:
    with session_factory() as session:
        return session.get(TransactionClassification, tx_id)


def act(ledger: Ledger, session_factory, tx_id: str, **change) -> dict:
    fields = frozenset(k for k in ("category", "fixed", "kind", "extraordinary") if k in change)
    book = load_rulebook(CONFIG_DIR, ledger.personal_rules_path)
    with session_factory() as session:
        undo = apply_change(
            session,
            ledger.personal_rules_path,
            tx_id,
            Change(
                change.pop("scope"),
                change.get("category"),
                change.get("fixed"),
                change.get("kind"),
                fields,
                change.get("extraordinary"),
            ),
            categories=book.categories,
            now=NOW,
        )
        session.commit()
    ledger.classify()
    return undo


def undo(ledger: Ledger, session_factory, payload: dict) -> None:
    with session_factory() as session:
        undo_change(session, ledger.personal_rules_path, payload, now=NOW)
        session.commit()
    ledger.classify()


# ------------------------------------------------------------------ B1: regra criada pela lista


def test_counterparty_category_rule_covers_past_and_future_and_keeps_hand_written_rules(ledger, session_factory):
    ledger.personal_rules(
        "# minhas regras\nregras:\n  # regra escrita à mão\n  - contem: PADARIA FICTICIA\n    categoria: Mercado\n"
    )
    old = ledger.tx(CARD, date(2026, 9, 5), -42.0, "Emporio Ficticio Centro")
    recent = ledger.tx(CARD, date(2026, 10, 5), -38.0, "Emporio Ficticio Centro")
    bakery = ledger.tx(CARD, date(2026, 10, 6), -10.0, "Padaria Ficticia")
    ledger.classify()
    assert cls(session_factory, recent).category != "Alimentação fora e delivery"

    payload = act(ledger, session_factory, recent, scope="counterparty", category="Alimentação fora e delivery")
    for tx_id in (old, recent):
        row = cls(session_factory, tx_id)
        assert (row.category, row.rule_level) == ("Alimentação fora e delivery", "pessoal")
        assert RULE_NAME in row.rule_detail
    assert cls(session_factory, bakery).category == "Mercado"  # regra à mão continua valendo
    text = ledger.personal_rules_path.read_text(encoding="utf-8")
    assert "# regra escrita à mão" in text and "# minhas regras" in text
    rules = yaml.safe_load(text)["regras"]
    assert rules[0]["contraparte"] == "EMPORIO FICTICIO CENTRO" and rules[1]["contem"] == "PADARIA FICTICIA"

    future = ledger.tx(CARD, date(2026, 11, 7), -51.0, "Emporio Ficticio Centro")
    ledger.classify()
    assert cls(session_factory, future).category == "Alimentação fora e delivery"

    undo(ledger, session_factory, payload)
    assert read_managed(ledger.personal_rules_path) == []
    assert cls(session_factory, future).category != "Alimentação fora e delivery"
    assert "PADARIA FICTICIA" in ledger.personal_rules_path.read_text(encoding="utf-8")


def test_only_this_one_uses_override_and_undo_restores_previous_override(ledger, session_factory):
    a = ledger.tx(CARD, date(2026, 10, 5), -38.0, "Emporio Ficticio Centro")
    b = ledger.tx(CARD, date(2026, 10, 9), -12.0, "Emporio Ficticio Centro")
    ledger.classify()
    payload = act(ledger, session_factory, a, scope="one", category="Lazer e entretenimento")
    assert cls(session_factory, a).category == "Lazer e entretenimento"
    assert cls(session_factory, b).category != "Lazer e entretenimento"
    assert read_managed(ledger.personal_rules_path) == []
    undo(ledger, session_factory, payload)
    with session_factory() as session:
        assert session.get(ClassificationOverride, a) is None


def test_counterparty_scope_needs_a_counterparty_and_valid_kind(ledger, session_factory):
    tx = ledger.tx(CARD, date(2026, 10, 5), -38.0, "Loja Qualquer")
    ledger.classify()
    with pytest.raises(ActionError):
        act(ledger, session_factory, tx, scope="one", kind="emprestimo_concedido")  # cartão não tem esse tipo


def test_interface_block_never_breaks_the_rules_file(ledger):
    ledger.personal_rules("regras: [{contem: X, categoria: Mercado}]\n")
    with pytest.raises(RulesError):
        set_counterparty_rule(ledger.personal_rules_path, "ALGUEM", "saida", categoria="Mercado")
    assert ledger.personal_rules_path.read_text(encoding="utf-8") == "regras: [{contem: X, categoria: Mercado}]\n"


# ------------------------------------------------------------------ B2: fixo por contraparte


def test_counterparty_fixed_creates_manual_rule_shown_in_fixed_screen_and_total(ledger, session_factory):
    shop = company("ACADEMIA FICTICIA LTDA")
    ids = [
        ledger.tx(
            BANK, date(2026, m, 3), -90.0, "Pagamento de boleto|ACADEMIA FICTICIA LTDA", payment_data={"receiver": shop}
        )
        for m in (10, 11)
    ]
    ledger.classify()
    with session_factory() as session:
        assert fixed_month(session, "2026-11", today=TODAY).paid_cents == 0  # 2 meses não bastam
    act(ledger, session_factory, ids[-1], scope="counterparty", fixed=True)
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.counterparty_key == "ACADEMIAFICTICIA"))
        assert rule.status == RULE_YES and rule.avg_monthly_cents == 9_000
        month = fixed_month(session, "2026-11", today=TODAY)
        assert month.paid_cents == 9_000 == month_summary(session, "2026-11").fixed_cents  # uma fonte de verdade
        assert month.monthly_cents == 9_000
    assert all(cls(session_factory, i).is_fixed for i in ids)


def test_fixed_paid_this_month_equals_expenses_screen_including_single_marks(ledger, session_factory):
    for m in (8, 9, 10, 11):
        ledger.tx(CARD, date(2026, m, 10), -30.0, "Nuvem Ficticia")
    single = ledger.tx(CARD, date(2026, 11, 12), -200.0, "Curso Ficticio")
    for m in (8, 9, 10):
        ledger.tx(CARD, date(2026, m, 25), -50.0, "Streaming Ficticio")
    ledger.classify()
    act(ledger, session_factory, single, scope="one", fixed=True)
    with session_factory() as session:
        month = fixed_month(session, "2026-11", today=TODAY)
        summary = month_summary(session, "2026-11")
        assert month.paid_cents == summary.fixed_cents == 3_000 + 20_000
        singles = [i for i in month.items if i.rule_id is None]
        assert [(i.label, i.paid_cents) for i in singles] == [("CURSO FICTICIO", 20_000)]
        pending = {i.label: i.pending_cents for i in month.items if i.rule_id is not None}
        assert pending["STREAMING FICTICIO"] == 5_000  # ativo e ainda não cobrou em novembro


# ------------------------------------------------------------------ B3: fixo inativo


def test_subscription_without_payment_for_45_days_is_inactive_unless_manual(ledger, session_factory):
    for m in (6, 7, 8):
        ledger.tx(CARD, date(2026, m, 12), -21.9, "Musica Ficticia")
    for m in (8, 9, 10, 11):
        ledger.tx(CARD, date(2026, m, 15), -10.0, "Fotos Ficticias")
    ledger.classify()
    with session_factory() as session:
        month = fixed_month(session, "2026-11", today=TODAY)
        states = {i.label: i.state for i in month.items}
        assert states == {"MUSICA FICTICIA": INACTIVE, "FOTOS FICTICIAS": ACTIVE}
        assert month.monthly_cents == 1_000  # inativo fora do total mensal
        rule = session.scalar(select(RecurringRule).where(RecurringRule.counterparty_key == "MUSICAFICTICIA"))
        rule.status = RULE_YES  # escolha manual vence
        session.commit()
        month = fixed_month(session, "2026-11", today=TODAY)
        assert {i.label: i.state for i in month.items}["MUSICA FICTICIA"] == ACTIVE
        assert month.monthly_cents == 1_000 + 2_190
        rule.status = "manual_nao"
        session.commit()
        assert {i.label: i.state for i in fixed_month(session, "2026-11", today=TODAY).items}["MUSICA FICTICIA"] == OFF


# ------------------------------------------------------------------ B4: tipos neutros


def test_loan_given_and_returned_are_neutral_and_open_balance_is_tracked(ledger, session_factory):
    friend = person("AMIGO FICTICIO DA SILVA")
    ledger.tx(
        BANK,
        date(2026, 11, 2),
        3000.0,
        "Transferência Recebida|EMPRESA FICTICIA",
        payment_data={"payer": company("EMPRESA FICTICIA")},
    )
    out = ledger.tx(
        BANK,
        date(2026, 10, 1),
        -500.0,
        "Transferência enviada pelo Pix|AMIGO FICTICIO DA SILVA",
        payment_data={"receiver": friend},
    )
    back = ledger.tx(
        BANK, date(2026, 11, 5), 200.0, "Transferência Recebida|AMIGO FICTICIO DA SILVA", payment_data={"payer": friend}
    )
    ledger.classify()
    with session_factory() as session:
        before_oct = month_summary(session, "2026-10")
        before_nov = month_summary(session, "2026-11")
    assert before_oct.expenses_total_cents == 50_000 and before_nov.income_cents == 320_000

    act(ledger, session_factory, out, scope="one", kind="emprestimo_concedido")
    act(ledger, session_factory, back, scope="counterparty", kind="devolucao_emprestimo")
    with session_factory() as session:
        oct_, nov = month_summary(session, "2026-10"), month_summary(session, "2026-11")
        assert oct_.expenses_total_cents == 0 and oct_.loans_out_cents == 50_000
        assert nov.income_cents == 300_000 and nov.loans_in_cents == 20_000
        assert nov.result_cents == 300_000
        [loan] = open_loans(session)
        assert (loan.lent_cents, loan.returned_cents, loan.open_cents) == (50_000, 20_000, 30_000)
    later = ledger.tx(
        BANK,
        date(2026, 11, 18),
        300.0,
        "Transferência Recebida|AMIGO FICTICIO DA SILVA",
        payment_data={"payer": friend},
    )
    ledger.classify()
    assert cls(session_factory, later).movement_type == "devolucao_emprestimo"  # regra da contraparte vale no futuro
    with session_factory() as session:
        assert open_loans(session)[0].open_cents == 0


def test_reimbursement_reduces_expenses_in_the_chosen_category(ledger, session_factory):
    dinner = ledger.tx(CARD, date(2026, 11, 3), -180.0, "Restaurante Ficticio")
    share = ledger.tx(
        BANK,
        date(2026, 11, 4),
        60.0,
        "Transferência Recebida|COLEGA FICTICIA SOUZA",
        payment_data={"payer": person("COLEGA FICTICIA SOUZA")},
    )
    other = ledger.tx(
        BANK,
        date(2026, 11, 6),
        15.0,
        "Transferência Recebida|COLEGA FICTICIA SOUZA",
        payment_data={"payer": person("COLEGA FICTICIA SOUZA")},
    )
    ledger.classify()
    category = cls(session_factory, dinner).category
    act(ledger, session_factory, share, scope="one", kind="reembolso", category=category)
    act(ledger, session_factory, other, scope="one", kind="reembolso")
    with session_factory() as session:
        s = month_summary(session, "2026-11")
        assert s.income_cents == 0
        assert s.expenses_by_category[category] == 18_000 - 6_000
        assert s.reimbursements_cents == 7_500 and s.reimbursements_uncategorized_cents == 1_500
        assert s.expenses_total_cents == 18_000 - 7_500


def test_own_transfer_is_neutral(ledger, session_factory):
    tx = ledger.tx(
        BANK,
        date(2026, 11, 5),
        1500.0,
        "Transferência Recebida|PRIMO FICTICIO NUNES",
        payment_data={"payer": person("PRIMO FICTICIO NUNES")},
    )
    ledger.classify()
    with session_factory() as session:
        assert month_summary(session, "2026-11").income_cents == 150_000
    act(ledger, session_factory, tx, scope="one", kind="transferencia_propria")
    with session_factory() as session:
        s = month_summary(session, "2026-11")
        assert (s.income_cents, s.result_cents, s.own_transfers_in_cents) == (0, 0, 150_000)


# ------------------------------------------------------------------ gasto extraordinário


def test_extraordinary_only_this_one_and_whole_counterparty_with_undo(ledger, session_factory):
    ledger.personal_rules("regras:\n  - contem: PADARIA FICTICIA\n    categoria: Mercado\n")
    sep = ledger.tx(CARD, date(2026, 9, 5), -800.0, "Oficina Ficticia")
    nov = ledger.tx(CARD, date(2026, 11, 5), -1200.0, "Oficina Ficticia")
    bread = ledger.tx(CARD, date(2026, 11, 6), -10.0, "Padaria Ficticia")
    ledger.classify()
    assert not cls(session_factory, nov).extraordinary

    one = act(ledger, session_factory, nov, scope="one", extraordinary=True)
    assert cls(session_factory, nov).extraordinary and not cls(session_factory, sep).extraordinary
    with session_factory() as session:
        assert month_summary(session, "2026-11").extraordinary_cents == 120_000
    undo(ledger, session_factory, one)
    assert not cls(session_factory, nov).extraordinary

    # toda a contraparte: regra no bloco da interface (passado e futuro), o resto do arquivo intacto
    whole = act(ledger, session_factory, nov, scope="counterparty", extraordinary=True)
    assert cls(session_factory, sep).extraordinary and cls(session_factory, nov).extraordinary
    assert not cls(session_factory, bread).extraordinary
    [rule] = read_managed(ledger.personal_rules_path)
    assert rule["extraordinario"] is True and rule["sentido"] == "saida"
    future = ledger.tx(CARD, date(2026, 11, 18), -300.0, "Oficina Ficticia")
    ledger.classify()
    assert cls(session_factory, future).extraordinary
    # "só esta" vence a regra da contraparte
    act(ledger, session_factory, future, scope="one", extraordinary=False)
    assert not cls(session_factory, future).extraordinary
    undo(ledger, session_factory, whole)
    assert read_managed(ledger.personal_rules_path) == [] and not cls(session_factory, sep).extraordinary
    assert "PADARIA FICTICIA" in ledger.personal_rules_path.read_text(encoding="utf-8")


def test_extraordinary_and_category_on_same_counterparty_undo_in_reverse_order(ledger, session_factory):
    tx = ledger.tx(CARD, date(2026, 11, 5), -1200.0, "Oficina Ficticia")
    ledger.classify()
    first = act(ledger, session_factory, tx, scope="counterparty", extraordinary=True)
    second = act(ledger, session_factory, tx, scope="counterparty", category="Transporte")
    [rule] = read_managed(ledger.personal_rules_path)
    assert (rule["extraordinario"], rule["categoria"]) == (True, "Transporte")
    undo(ledger, session_factory, second)
    [rule] = read_managed(ledger.personal_rules_path)
    assert rule == {"contraparte": "OFICINA FICTICIA", "sentido": "saida", "extraordinario": True, "nome": RULE_NAME}
    undo(ledger, session_factory, first)
    assert read_managed(ledger.personal_rules_path) == []


def test_only_expenses_can_be_extraordinary(ledger, session_factory):
    salary = ledger.tx(
        BANK,
        date(2026, 11, 2),
        1000.0,
        "Transferência Recebida|EMPREGADOR FICTICIO LTDA",
        payment_data={"payer": company("EMPREGADOR FICTICIO LTDA")},
    )
    ledger.classify()
    with pytest.raises(ActionError, match="Só gastos"):
        act(ledger, session_factory, salary, scope="one", extraordinary=True)
