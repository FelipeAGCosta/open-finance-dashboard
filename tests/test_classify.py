"""Classificação com extratos sintéticos."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from conftest import dump_tables
from findash.classify.installments import commitments_after
from findash.classify.recurrence import set_status
from findash.classify.rules import RulesError, compile_pattern, load_rulebook
from findash.classify.summary import month_summary
from findash.classify.text import counterparty_key, normalize_counterparty, raw_counterparty
from findash.db.models import ClassificationOverride, RecurringRule, TransactionClassification, TransactionLink
from findash.institutions import get_profile
from ledger import BANK, CARD, CONFIG_DIR, NOW, OWNER_CPF, OWNER_NAME, Ledger, company, person


@pytest.fixture
def ledger(session_factory, tmp_path) -> Ledger:
    return Ledger(session_factory, tmp_path / "regras_pessoais.yaml")


def cls(session_factory, tx_id: str) -> TransactionClassification:
    with session_factory() as session:
        return session.get(TransactionClassification, tx_id)


def summary(session_factory, month: str):
    with session_factory() as session:
        return month_summary(session, month)


# ---------------------------------------------------------------- contraparte


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Padaria Exemplo Ltda.", "PADARIA EXEMPLO"),
        ("Açaí do Zé ME", "ACAI DO ZE"),
        ("Dl*Corridasapp", "DL CORRIDASAPP"),
        ("Eletro Exemplo 2/3", "ELETRO EXEMPLO"),
        ("Comércio Fictício S/A", "COMERCIO FICTICIO"),
        ("  Loja   Exemplo  EIRELI ", "LOJA EXEMPLO"),
    ],
)
def test_counterparty_normalization(raw, expected):
    assert normalize_counterparty(raw) == expected


def test_counterparty_extraction_and_key():
    nubank = get_profile("nubank")
    embedded = nubank.counterparty_from_description("Transferência enviada pelo Pix|FULANO EXEMPLO")
    assert embedded == "FULANO EXEMPLO"
    assert (
        raw_counterparty("Transferência enviada pelo Pix|FULANO EXEMPLO", None, None, "DEBIT", "BANK", embedded)
        == embedded
    )
    assert get_profile("generic").counterparty_from_description("Pix|FULANO EXEMPLO") is None
    assert nubank.counterparty_from_description("Pagamento de fatura") is None
    assert raw_counterparty("Pagamento de fatura", None, None, "DEBIT", "BANK") == "Pagamento de fatura"
    assert raw_counterparty("Pix", {"receiver": {"name": "Beltrano"}}, None, "DEBIT", "BANK") == "Beltrano"
    assert counterparty_key(normalize_counterparty("Apple.Com/Bill")) == counterparty_key(
        normalize_counterparty("Applecombill")
    )


def test_pattern_semantics():
    assert compile_pattern("UBER TRIP").search("PAGTO UBER TRIP SAO PAULO")
    assert not compile_pattern("UBER").search("UBERABAPADARIA")  # palavra inteira
    assert compile_pattern("DROGA*").search("DROGARIA EXEMPLO")  # prefixo
    assert compile_pattern("apple.com").search("APPLE COM BILL")  # pontuação e maiúsculas indiferentes


# ---------------------------------------------------------------- fatura e contagem dupla


def test_bill_payment_pairing_with_and_without_pair(ledger, session_factory):
    paid = ledger.tx(BANK, date(2026, 10, 10), -500, "Pagamento de fatura")
    received = ledger.tx(CARD, date(2026, 10, 10), 500, "Pagamento recebido")
    lonely = ledger.tx(BANK, date(2026, 10, 25), -300, "Pagamento de fatura")
    stats = ledger.classify()
    assert stats.bill_pairs == 1
    assert stats.bill_unpaired_bank == [lonely] and stats.bill_unpaired_card == []
    for tx_id in (paid, received, lonely):
        assert cls(session_factory, tx_id).movement_type == "pagamento_fatura"
    with session_factory() as session:
        link = session.scalar(select(TransactionLink).where(TransactionLink.kind == "pagamento_fatura"))
    assert (link.transaction_id, link.other_transaction_id) == (paid, received)


def test_card_purchase_plus_bill_payment_is_a_single_expense(ledger, session_factory):
    ledger.tx(CARD, date(2026, 10, 3), -300, "Loja Exemplo Online", mcc=5732)
    ledger.tx(BANK, date(2026, 10, 15), -300, "Pagamento de fatura")
    ledger.tx(CARD, date(2026, 10, 15), 300, "Pagamento recebido")
    ledger.tx(
        BANK,
        date(2026, 10, 5),
        1000,
        "Transferência Recebida|EMPRESA EXEMPLO",
        payment_data={"payer": company("Empresa Exemplo")},
    )
    ledger.classify()
    s = summary(session_factory, "2026-10")
    assert s.expenses_total_cents == 30000  # a compra; o pagamento da fatura não conta de novo
    assert s.income_cents == 100000
    assert s.bill_payments_cents == 30000
    assert s.result_cents == 70000 and s.savings_rate == pytest.approx(0.7)


# ---------------------------------------------------------------- prioridade das regras


def test_rule_priority(ledger, session_factory):
    ledger.personal_rules("regras:\n  - contem: LOJA PRIORIDADE\n    categoria: Lazer e entretenimento\n")
    everything = ledger.tx(CARD, date(2026, 10, 1), -10, "IFOOD LOJA PRIORIDADE", mcc=5411, category="Pharmacy")
    base = ledger.tx(CARD, date(2026, 10, 2), -10, "IFOOD Exemplo", mcc=5411, category="Pharmacy")
    mcc = ledger.tx(CARD, date(2026, 10, 3), -10, "Estabelecimento Sem Regra", mcc=5411, category="Pharmacy")
    pluggy = ledger.tx(CARD, date(2026, 10, 4), -10, "Outro Sem Regra", category="Pharmacy")
    nothing = ledger.tx(CARD, date(2026, 10, 5), -10, "Mais Um Sem Regra")
    overridden = ledger.tx(CARD, date(2026, 10, 6), -10, "IFOOD LOJA PRIORIDADE", mcc=5411, category="Pharmacy")
    with session_factory() as session:
        session.add(
            ClassificationOverride(
                transaction_id=overridden, category="Viagem", note="teste", created_at=NOW, updated_at=NOW
            )
        )
        session.commit()
    ledger.classify()
    expected = {
        everything: ("pessoal", "Lazer e entretenimento"),
        base: ("base", "Alimentação fora e delivery"),
        mcc: ("mcc", "Mercado"),
        pluggy: ("pluggy", "Saúde e farmácia"),
        nothing: ("a_classificar", "A classificar"),
        overridden: ("override", "Viagem"),
    }
    for tx_id, (level, category) in expected.items():
        result = cls(session_factory, tx_id)
        assert (result.rule_level, result.category) == (level, category), tx_id
        assert result.rule_detail  # sempre registra qual regra decidiu


def test_rule_exclusion_and_pluggy_merchant_is_only_a_fallback(ledger, session_factory):
    mercado_pago = ledger.tx(BANK, date(2026, 10, 1), -20, "Compra no débito|MERCADO PAGO EXEMPLO")
    mercado_bitcoin = ledger.tx(BANK, date(2026, 10, 1), -25, "Compra no débito|MERCADO BITCOIN EXEMPLO")
    bar = ledger.tx(
        CARD, date(2026, 10, 2), -30, "Bar Ficticio da Esquina", merchant="Uber do Brasil Tecnologia", mcc=5921
    )
    ledger.classify()
    # regra MERCADO tem 'exceto': Mercado Pago é intermediário de pagamento, não supermercado
    assert cls(session_factory, mercado_pago).category == "Compras online"
    assert cls(session_factory, mercado_bitcoin).category == "A classificar"
    result = cls(session_factory, bar)
    assert (result.rule_level, result.category) == ("base", "Alimentação fora e delivery")  # 'BAR' na descrição


# ---------------------------------------------------------------- pessoas físicas e transferências


def test_pix_to_person_is_non_essential_expense_and_from_person_is_income(ledger, session_factory):
    sent = ledger.tx(
        BANK,
        date(2026, 10, 1),
        -80,
        "Transferência enviada pelo Pix|FULANO EXEMPLO",
        payment_data={"receiver": person("Fulano Exemplo")},
    )
    received = ledger.tx(
        BANK,
        date(2026, 10, 2),
        50,
        "Transferência Recebida|BELTRANA EXEMPLO",
        payment_data={"payer": person("Beltrana Exemplo")},
    )
    by_name = ledger.tx(BANK, date(2026, 10, 3), -15, "Transferência enviada pelo Pix|CICLANO DA SILVA EXEMPLO")
    ledger.classify()
    result = cls(session_factory, sent)
    assert (result.movement_type, result.category, result.essential) == (
        "despesa",
        "Transferências para pessoas",
        False,
    )
    assert (result.counterparty_kind, result.rule_level) == ("PF", "pessoa_fisica")
    assert cls(session_factory, received).movement_type == "receita"
    assert cls(session_factory, by_name).category == "Transferências para pessoas"  # sem CPF: heurística de nome


def test_personal_rule_reclassifies_a_person(ledger, session_factory):
    ledger.personal_rules(
        "regras:\n  - contem: FULANO EXEMPLO\n    sentido: saida\n    categoria: Moradia\n    essencial: true\n"
    )
    rent = ledger.tx(
        BANK,
        date(2026, 10, 5),
        -1500,
        "Transferência enviada pelo Pix|FULANO EXEMPLO",
        payment_data={"receiver": person("Fulano Exemplo")},
    )
    ledger.classify()
    result = cls(session_factory, rent)
    assert (result.category, result.essential, result.rule_level) == ("Moradia", True, "pessoal")


def test_transfer_to_self_is_internal(ledger, session_factory):
    to_self = ledger.tx(
        BANK,
        date(2026, 10, 1),
        -600,
        f"Transferência enviada pelo Pix|{OWNER_NAME.upper()}",
        payment_data={"payer": person(OWNER_NAME, OWNER_CPF), "receiver": person(OWNER_NAME, OWNER_CPF)},
    )
    topup = ledger.tx(BANK, date(2026, 10, 2), 100, "Valor adicionado na conta por cartão de crédito|NU")
    ledger.classify()
    assert cls(session_factory, to_self).movement_type == "transferencia_interna"
    assert cls(session_factory, topup).movement_type == "transferencia_interna"
    s = summary(session_factory, "2026-10")
    assert (s.income_cents, s.expenses_total_cents) == (0, 0)


# ---------------------------------------------------------------- investimentos


def test_investment_movements(ledger, session_factory):
    interest = ledger.tx(BANK, date(2026, 10, 15), 8.5, "Valor recebido de Investimentos")
    ledger.investment_tx(date(2026, 10, 14), "INTEREST", 8.5)
    sale = ledger.tx(BANK, date(2026, 10, 16), 1234.56, "Valor recebido de Investimentos")
    ledger.investment_tx(date(2026, 10, 16), "SELL", 1234.56)
    big_unmatched = ledger.tx(BANK, date(2026, 10, 17), 4000, "Valor recebido de Investimentos")
    small_unmatched = ledger.tx(BANK, date(2026, 10, 18), 30, "Valor recebido de Investimentos")
    buy = ledger.tx(BANK, date(2026, 10, 2), -1000, "Compra de Renda Variável")
    treasury = ledger.tx(BANK, date(2026, 10, 3), -500, "Aplicação em Tesouro Direto")
    redeem = ledger.tx(BANK, date(2026, 10, 4), 300, "Resgate RDB")
    ledger.classify()
    kinds = {
        tx: cls(session_factory, tx).movement_type
        for tx in (interest, sale, big_unmatched, small_unmatched, buy, treasury, redeem)
    }
    assert kinds == {
        interest: "renda_investimento",
        sale: "resgate",
        big_unmatched: "resgate",
        small_unmatched: "renda_investimento",
        buy: "aporte",
        treasury: "aporte",
        redeem: "resgate",
    }
    s = summary(session_factory, "2026-10")
    assert s.income_cents == 0  # renda de investimento nunca é receita
    assert s.investment_income_cents == 850 + 3000
    assert s.contributions_cents == 150000 and s.redemptions_cents == 123456 + 400000 + 30000


# ---------------------------------------------------------------- estorno


def test_refund_reduces_original_category(ledger, session_factory):
    ledger.personal_rules("regras:\n  - contem: LOJA ROUPA EXEMPLO\n    categoria: Vestuário\n")
    ledger.tx(CARD, date(2026, 10, 1), -100, "Loja Roupa Exemplo")
    refund = ledger.tx(CARD, date(2026, 10, 5), 40, "Loja Roupa Exemplo")
    loose = ledger.tx(CARD, date(2026, 10, 6), 10, "Estorno de compra")
    stats = ledger.classify()
    linked = cls(session_factory, refund)
    assert (linked.movement_type, linked.category, linked.rule_level) == ("estorno", "Vestuário", "estorno_da_compra")
    assert cls(session_factory, loose).category is None
    assert (stats.refunds_linked, stats.refunds_unlinked) == (1, 1)
    s = summary(session_factory, "2026-10")
    assert s.expenses_by_category["Vestuário"] == 6000
    assert s.refunds_without_origin_cents == 1000
    assert s.expenses_total_cents == 5000


# ---------------------------------------------------------------- recorrência


def monthly(ledger, account, description, amounts, day=5, start=(2026, 6), **kwargs):
    year, month = start
    ids = []
    for amount in amounts:
        ids.append(ledger.tx(account, date(year, month, day), amount, description, **kwargs))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return ids


def test_recurrence_detection(ledger, session_factory):
    ledger.personal_rules(
        "regras:\n"
        "  - contem: STREAMING EXEMPLO\n    categoria: Assinaturas e serviços digitais\n"
        "  - contem: LUZ EXEMPLO\n    categoria: Contas da casa\n"
        "  - contem: ACADEMIA VARIAVEL EXEMPLO\n    categoria: Lazer e entretenimento\n"
    )
    monthly(ledger, CARD, "Streaming Exemplo", [-39.90] * 6)  # fixo
    monthly(ledger, BANK, "Pagamento efetuado|LUZ EXEMPLO", [-100, -140, -90, -120, -135])  # varia 45%: conta da casa
    monthly(ledger, BANK, "Pagamento efetuado|ACADEMIA VARIAVEL EXEMPLO", [-100, -140, -90, -120])  # varia: não fixo
    monthly(ledger, CARD, "Parcelado Exemplo", [-50] * 4, installment=(1, 6))  # parcela não é fixo
    for day in range(1, 28, 3):  # várias corridas por mês, valores variados: não fixo
        for month in (8, 9, 10):
            ledger.tx(CARD, date(2026, month, day), -(10 + day), "Uber Trip Exemplo")
    stats = ledger.classify()
    with session_factory() as session:
        rules = {r.counterparty: r for r in session.scalars(select(RecurringRule).where(RecurringRule.kind == "fixo"))}
    assert set(rules) == {"STREAMING EXEMPLO", "LUZ EXEMPLO"}
    assert rules["LUZ EXEMPLO"].category == "Contas da casa"  # varia 45%, mas conta da casa pode variar
    streaming = rules["STREAMING EXEMPLO"]
    assert (streaming.status, streaming.avg_monthly_cents, streaming.months_count) == ("automatico", 3990, 6)
    assert stats.fixed_detected == 2


def test_detected_fixed_counts_immediately_and_manual_choice_wins(ledger, session_factory):
    streaming = monthly(ledger, CARD, "Streaming Exemplo", [-39.90] * 6)
    clube = monthly(ledger, CARD, "Clube Exemplo", [-20] * 6)
    ledger.classify()
    s = summary(session_factory, "2026-10")
    assert (s.fixed_cents, s.variable_cents) == (5990, 0)  # detectado = fixo, sem confirmação
    with session_factory() as session:
        ids = {r.counterparty: r.id for r in session.scalars(select(RecurringRule))}
        set_status(session, ids["STREAMING EXEMPLO"], "manual_sim", now=NOW)
        set_status(session, ids["CLUBE EXEMPLO"], "manual_nao", now=NOW)
        # fixo sim/não numa transação específica vence a regra
        session.add(ClassificationOverride(transaction_id=clube[4], fixed=True, created_at=NOW, updated_at=NOW))
        session.add(ClassificationOverride(transaction_id=streaming[3], fixed=False, created_at=NOW, updated_at=NOW))
        session.commit()
    ledger.classify(now=NOW + timedelta(days=1))
    ledger.classify(now=NOW + timedelta(days=2))
    with session_factory() as session:
        status = {r.counterparty: (r.id, r.status) for r in session.scalars(select(RecurringRule))}
    # escolhas manuais persistem; o desmarcado nunca volta a 'automatico', mesmo sendo detectado de novo
    assert status == {
        "STREAMING EXEMPLO": (ids["STREAMING EXEMPLO"], "manual_sim"),
        "CLUBE EXEMPLO": (ids["CLUBE EXEMPLO"], "manual_nao"),
    }
    assert (cls(session_factory, clube[4]).is_fixed, cls(session_factory, clube[3]).is_fixed) == (True, False)
    assert (cls(session_factory, streaming[3]).is_fixed, cls(session_factory, streaming[4]).is_fixed) == (False, True)
    september, october = summary(session_factory, "2026-09"), summary(session_factory, "2026-10")
    assert (september.fixed_cents, september.variable_cents) == (0, 5990)  # override: streaming de setembro não é fixo
    assert (october.fixed_cents, october.variable_cents) == (5990, 0)  # override: clube de outubro é fixo


def test_salary_is_applied_automatically_and_can_be_unmarked(ledger, session_factory):
    monthly(
        ledger,
        BANK,
        "Transferência Recebida|EMPRESA PAGADORA EXEMPLO",
        [5000, 5000, 5100, 5000],
        payment_data={"payer": company("Empresa Pagadora Exemplo")},
    )
    ledger.classify()
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.kind == "salario"))
    assert (rule.counterparty, rule.status) == ("EMPRESA PAGADORA EXEMPLO", "automatico")
    s = summary(session_factory, "2026-07")
    assert s.income_cents == s.income_salary_cents == 500000
    assert s.income_by_rule_status == {"automatico": 500000}
    with session_factory() as session:
        set_status(session, rule.id, "manual_nao", now=NOW)
        session.commit()
    ledger.classify(now=NOW + timedelta(days=1))
    s = summary(session_factory, "2026-07")
    assert (s.income_cents, s.income_salary_cents) == (500000, 0)  # desmarcado: continua receita, não salário
    assert rule.paycheck_cents is None and rule.avg_monthly_cents == 502500  # mensal, mas a agenda é semanal


def weekly_payments(ledger, first: date, last: date, *, paid_on=None, skip=(), name="EMPRESA SEMANAL EXEMPLO"):
    """Um crédito de R$ 1.000 por semana; paid_on troca o dia de um pagamento (atraso), skip pula semanas."""
    paid_on = paid_on or {}
    day = first
    while day <= last:
        if day not in skip:
            ledger.tx(
                BANK,
                paid_on.get(day, day),
                1000,
                f"Transferência Recebida|{name}",
                payment_data={"payer": company(name.title())},
            )
        day += timedelta(days=7)


def test_weekly_salary_expected_by_paydays_of_the_month(ledger, session_factory):
    from findash.classify.commands import summary_lines

    first = date(2026, 6, 1)
    assert first.weekday() == 0
    weekly_payments(
        ledger,
        first,
        date(2026, 11, 2),
        paid_on={
            date(2026, 6, 29): date(2026, 7, 1),  # atraso de 2 dias, cai no mês seguinte
            date(2026, 9, 7): date(2026, 9, 8),
        },  # feriado: paga na terça
        skip={date(2026, 8, 17)},
    )  # semana sem pagamento
    ledger.tx(BANK, date(2026, 11, 10), -30, "Compra no débito|Padaria Exemplo")  # dado mais recente do banco
    ledger.classify()
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.kind == "salario"))
        assert (rule.status, rule.paycheck_cents, rule.payment_interval_days) == ("automatico", 100000, 7)
        assert (rule.pay_frequency, rule.payday, rule.grace_days) == ("weekly", 0, 2)
        assert rule.avg_monthly_cents == 433333  # média anual: 1.000 × 52 ÷ 12
        august_text = "\n".join(summary_lines(session, "2026-08"))

    def month(name):
        [salary] = summary(session_factory, name).salaries
        return salary

    june, july, august, september, november = (
        month(m) for m in ("2026-06", "2026-07", "2026-08", "2026-09", "2026-11")
    )
    # (dias de pagamento no mês, esperado, recebido pelo dia de referência, recebido pelo dia do crédito, diverge?)
    assert (
        len(june.paydays),
        june.expected_cents,
        june.received_reference_cents,
        june.received_cash_cents,
        june.divergent,
    ) == (5, 500000, 500000, 400000, False)
    assert june.shifted == [(date(2026, 7, 1), date(2026, 6, 29))]
    assert (
        len(july.paydays),
        july.expected_cents,
        july.received_reference_cents,
        july.received_cash_cents,
        july.divergent,
    ) == (4, 400000, 400000, 500000, False)
    assert (
        len(august.paydays),
        august.expected_cents,
        august.received_reference_cents,
        august.divergent,
        august.missing_paydays,
    ) == (5, 500000, 400000, True, [date(2026, 8, 17)])
    assert (september.received_reference_cents, september.divergent) == (400000, False)  # terça de feriado conta
    # mês em andamento: só a segunda 02/11 já venceu (09/11 ainda está no prazo de 2 dias em 10/11)
    assert (november.expected_cents, november.expected_due_cents, november.in_progress, november.divergent) == (
        500000,
        100000,
        True,
        False,
    )
    assert "esperado no mês R$ 5.000,00 (5 pagamento(s)) | recebido R$ 4.000,00" in august_text
    assert "média ao longo do ano R$ 4.333,33/mês" in august_text
    assert "⚠ recebido difere do esperado em R$ -1.000,00 (dias sem pagamento: 17/08)" in august_text


def test_weekly_salary_on_another_weekday_does_not_follow_the_schedule(ledger, session_factory):
    friday = date(2026, 6, 5)
    assert friday.weekday() == 4
    weekly_payments(ledger, friday, date(2026, 10, 30))
    ledger.classify()
    with session_factory() as session:
        rule = session.scalar(select(RecurringRule).where(RecurringRule.kind == "salario"))
    assert rule.status == "automatico" and rule.paycheck_cents is None  # salário, mas fora da agenda configurada
    assert summary(session_factory, "2026-07").salaries == []


def test_subscription_is_fixed_after_two_consecutive_months(ledger, session_factory):
    ledger.personal_rules("regras:\n  - contem: CLUBE EXEMPLO\n    categoria: Cuidados pessoais\n")
    monthly(ledger, CARD, "Netflix Exemplo Seguida", [-39.90, -39.90], start=(2026, 9))  # 2 meses seguidos
    monthly(ledger, CARD, "Spotify Exemplo Salteado", [-21.90], start=(2026, 7))  # julho e setembro: não seguidos
    monthly(ledger, CARD, "Spotify Exemplo Salteado", [-21.90], start=(2026, 9))
    monthly(ledger, CARD, "Clube Exemplo", [-50, -50], start=(2026, 9))  # outra categoria: precisa de 3 meses
    ledger.classify()
    with session_factory() as session:
        fixed = {r.counterparty: r.months_count for r in session.scalars(select(RecurringRule))}
    assert fixed == {"NETFLIX EXEMPLO SEGUIDA": 2}


# ---------------------------------------------------------------- parcelas


def test_installment_projection(ledger, session_factory):
    purchase = date(2026, 9, 2)
    ledger.tx(
        CARD,
        date(2026, 9, 2),
        -100,
        "Eletro Exemplo 1/5",
        installment=(1, 5),
        purchase_date=purchase,
        bill_month="2026-09",
    )
    ledger.tx(
        CARD,
        date(2026, 10, 3),
        -100,
        "Eletro Exemplo 2/5",
        installment=(2, 5),
        purchase_date=purchase,
        bill_month="2026-10",
    )
    ledger.tx(
        CARD,
        date(2026, 10, 1),
        -60,
        "Fone Exemplo 2/2",
        installment=(2, 2),
        purchase_date=date(2026, 9, 1),
        bill_month="2026-10",
    )  # quitada: nada a projetar
    ledger.classify()
    with session_factory() as session:
        assert commitments_after(session, "2026-10") == {"2026-11": 10000, "2026-12": 10000, "2027-01": 10000}
        assert commitments_after(session, "2026-09") == {
            "2026-10": 16000,
            "2026-11": 10000,
            "2026-12": 10000,
            "2027-01": 10000,
        }
    assert sum(summary(session_factory, "2026-10").commitments.values()) == 30000


def test_installments_with_rounded_first_installment_and_prepayment(ledger, session_factory):
    """1ª parcela com centavos a mais e parcelas restantes antecipadas no mesmo dia: nada a projetar."""
    purchase = date(2026, 1, 28)
    ledger.tx(CARD, date(2026, 1, 28), -33.34, "Viagem Exemplo 1/3", installment=(1, 3), purchase_date=purchase)
    ledger.tx(CARD, date(2026, 8, 24), -33.33, "Viagem Exemplo 2/3", installment=(2, 3), purchase_date=purchase)
    ledger.tx(CARD, date(2026, 8, 24), -33.33, "Viagem Exemplo 3/3", installment=(3, 3), purchase_date=purchase)
    # parcela 1/2 lançada em outubro (despesa de outubro) e 2/2 em novembro: só a 2/2 é compromisso após outubro
    ledger.tx(
        CARD,
        date(2026, 10, 26),
        -487.30,
        "Clinica Exemplo 1/2",
        installment=(1, 2),
        purchase_date=date(2026, 10, 26),
        bill_month="2026-11",
    )
    ledger.classify()
    with session_factory() as session:
        assert commitments_after(session, "2026-10") == {"2026-11": 48730}
        assert commitments_after(session, "2026-01") == {"2026-08": 6666, "2026-10": 48730, "2026-11": 48730}


# ---------------------------------------------------------------- idempotência e overrides


def build_mixed_month(ledger):
    ledger.tx(CARD, date(2026, 10, 3), -89.9, "Loja Exemplo Online", mcc=5732)
    ledger.tx(CARD, date(2026, 10, 4), 20, "Loja Exemplo Online")
    ledger.tx(BANK, date(2026, 10, 15), -69.9, "Pagamento de fatura")
    ledger.tx(CARD, date(2026, 10, 15), 69.9, "Pagamento recebido")
    ledger.tx(BANK, date(2026, 10, 15), 8.5, "Valor recebido de Investimentos")
    ledger.investment_tx(date(2026, 10, 15), "INTEREST", 8.5)
    ledger.tx(
        BANK,
        date(2026, 10, 20),
        -80,
        "Transferência enviada pelo Pix|FULANO EXEMPLO",
        payment_data={"receiver": person("Fulano Exemplo")},
    )
    monthly(ledger, CARD, "Streaming Exemplo", [-39.90] * 6)


def test_classification_is_idempotent(ledger, session_factory):
    build_mixed_month(ledger)
    ledger.classify()
    first = dump_tables(session_factory)  # sem computed_at/created_at, que mudam a cada execução
    ledger.classify(now=NOW + timedelta(hours=1))
    assert dump_tables(session_factory) == first
    with session_factory() as session:
        assert session.scalar(select(TransactionClassification).limit(1)) is not None


def test_overrides_persist_across_recalculations(ledger, session_factory):
    build_mixed_month(ledger)
    pix = ledger.tx(
        BANK,
        date(2026, 10, 21),
        -300,
        "Transferência enviada pelo Pix|BELTRANO EXEMPLO",
        payment_data={"receiver": person("Beltrano Exemplo")},
    )
    with session_factory() as session:
        session.add(
            ClassificationOverride(
                transaction_id=pix,
                movement_type="despesa",
                category="Moradia",
                essential=True,
                note="aluguel",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
    for hours in range(3):
        ledger.classify(now=NOW + timedelta(hours=hours))
        result = cls(session_factory, pix)
        assert (result.category, result.essential, result.rule_level) == ("Moradia", True, "override")


def test_override_of_movement_type(ledger, session_factory):
    received = ledger.tx(
        BANK,
        date(2026, 10, 2),
        200,
        "Transferência Recebida|AMIGO EXEMPLO",
        payment_data={"payer": person("Amigo Exemplo")},
    )
    with session_factory() as session:
        session.add(
            ClassificationOverride(
                transaction_id=received, movement_type="transferencia_interna", created_at=NOW, updated_at=NOW
            )
        )
        session.commit()
    ledger.classify()
    assert cls(session_factory, received).movement_rule == "override manual"
    assert summary(session_factory, "2026-10").income_cents == 0


# ---------------------------------------------------------------- validação dos YAML


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("regras:\n  - contem: X\n    categoria: Inexistente\n", "categoria 'Inexistente' não existe"),
        ("regras:\n  - contem: X\n    categoria: Mercado\n    cor: azul\n", "campo(s) desconhecido(s): cor"),
        ("regras:\n  - contem: X\n    tipo: salario\n", "tipo 'salario' inválido"),
        ("regras:\n  - categoria: Mercado\n", "'contem' precisa"),
        ("regras:\n  - contem: X\n", "informe 'categoria', 'tipo' e/ou 'extraordinario'"),
        ("regras: [\n", "YAML inválido"),
    ],
)
def test_invalid_personal_rules_are_reported_clearly(tmp_path, content, message):
    path = tmp_path / "regras_pessoais.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(RulesError) as caught:
        load_rulebook(CONFIG_DIR, path)
    assert message in str(caught.value) and "regras_pessoais.yaml" in str(caught.value)


def test_versioned_rule_files_are_valid(tmp_path):
    book = load_rulebook(CONFIG_DIR, tmp_path / "nao_existe.yaml")
    assert book.base and book.mcc and book.pluggy and book.personal == []
    example = load_rulebook(CONFIG_DIR, CONFIG_DIR / "regras_pessoais.example.yaml")
    assert len(example.personal) == 5


def test_salary_start_date_means_earlier_paydays_are_not_missing(ledger, session_factory):
    first = date(2026, 8, 19)  # emprego começou numa quarta: referência é a segunda 17/08
    weekly_payments(ledger, date(2026, 8, 17), date(2026, 10, 26), paid_on={date(2026, 8, 17): first})
    ledger.classify()
    [august] = summary(session_factory, "2026-08").salaries
    assert august.started_on == date(2026, 8, 17)
    assert ([d.day for d in august.paydays], august.expected_cents, august.divergent) == ([17, 24, 31], 300000, False)
