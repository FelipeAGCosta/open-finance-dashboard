"""Onde cada investimento conta no Plano: Reserva de emergência ou Patrimônio.

Cada real pertence a UM só lugar (a soma dos lugares é a carteira inteira, sem dupla contagem):
1. Escolha manual (investment_places) vence: o investimento inteiro vai para o lugar escolhido.
2. Reserva = VALOR FIXO. A renda fixa automática enche a Reserva na ordem escolhida (padrão: CDB/RDB,
   que inclui CDBs de liquidez diária, depois Tesouro; dentro da classe, do maior para o menor) até completar o
   valor, já descontado o que foi posto na Reserva à mão. Um título pode ficar dividido.
   Sem valor definido, toda a renda fixa automática dessas classes conta na Reserva.
3. Todo o resto é Patrimônio, inclusive a renda fixa que passa da Reserva (classe "Renda fixa").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findash.db.models import PLACE_PATRIMONY, PLACE_RESERVE, PLACES, InvestmentPlace
from findash.invest.classes import FIXED_INCOME_CLASSES
from findash.invest.portfolio import Position

RESERVE, PATRIMONY = PLACE_RESERVE, PLACE_PATRIMONY


@dataclass
class Holding:
    position: Position
    manual: str | None  # lugar escolhido à mão (reserva | patrimonio)
    parts: dict[str, int] = field(default_factory=dict)  # lugar -> centavos (brutos)
    reason: str = ""

    @property
    def place(self) -> str:
        """Lugar principal (o de maior parte)."""
        return max(self.parts.items(), key=lambda kv: kv[1])[0] if self.parts else PATRIMONY


def manual_places(session: Session) -> dict[str, str]:
    return {row.investment_id: row.place for row in session.scalars(select(InvestmentPlace))}


def assign(session: Session, items: list[Position], *, reserve_cents: int | None, order: list[str]) -> list[Holding]:
    manual = manual_places(session)
    holdings: list[Holding] = []
    automatic_fixed: list[Holding] = []
    reserved_by_hand = 0
    for p in items:
        place = manual.get(p.investment.id)
        h = Holding(p, place)
        holdings.append(h)
        if place is not None:
            h.parts, h.reason = {place: p.value_cents}, "escolha sua"
            if place == RESERVE:
                reserved_by_hand += p.value_cents
        elif p.asset_class in FIXED_INCOME_CLASSES:
            automatic_fixed.append(h)
        else:
            h.parts, h.reason = {PATRIMONY: p.value_cents}, "renda variável fica no Patrimônio"

    need = None if reserve_cents is None else max(0, reserve_cents - reserved_by_hand)
    in_order = [h for h in automatic_fixed if h.position.asset_class in order]
    in_order.sort(key=lambda h: (order.index(h.position.asset_class), -h.position.value_cents, h.position.label))
    for h in in_order:
        value = h.position.value_cents
        to_reserve = value if need is None else min(value, need)
        if need is not None:
            need -= to_reserve
        h.parts = {k: v for k, v in ((RESERVE, to_reserve), (PATRIMONY, value - to_reserve)) if v > 0}
        if to_reserve == value:
            h.reason = "renda fixa de liquidez diária: completa a Reserva"
        elif to_reserve:
            h.reason = "parte completa a Reserva; o que passa fica no Patrimônio"
        else:
            h.reason = "renda fixa acima da Reserva: fica no Patrimônio"
    sorted_ids = {id(h) for h in in_order}
    for h in automatic_fixed:
        if id(h) not in sorted_ids:
            h.parts = {PATRIMONY: h.position.value_cents}
            h.reason = "renda fixa fora da composição da Reserva: fica no Patrimônio"
    return holdings


def totals(holdings: list[Holding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in holdings:
        for place, cents in h.parts.items():
            out[place] = out.get(place, 0) + cents
    return out


def set_place(session: Session, investment_id: str, place: str | None, *, now: datetime) -> str | None:
    """Grava (ou limpa, com None) o lugar manual; devolve o anterior (para desfazer)."""
    if place is not None and place not in PLACES:
        raise ValueError("Lugar inválido.")
    row = session.get(InvestmentPlace, investment_id)
    previous = row.place if row is not None else None
    if place is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(InvestmentPlace(investment_id=investment_id, place=place, updated_at=now))
    else:
        row.place, row.updated_at = place, now
    session.flush()
    return previous
