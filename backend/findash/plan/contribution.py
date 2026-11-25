"""Divisão do aporte do mês: Reserva (se precisar) → Patrimônio, e o Patrimônio por classe e ativo.

1. Reserva: enquanto está abaixo do valor fixo, tem PRIORIDADE automática e recebe primeiro o que falta
   (da meta do mês, que já inclui o pagamento extra do salário, se ligado). O resto vai para o Patrimônio.
2. Patrimônio, SEM vender: "enchimento por nível" entre as classes que recebem sugestão (renda fixa,
   ETF Global, ETF Brasil e ações do núcleo; FIIs, ações mantidas e satélite nunca recebem). Com v_i o
   valor atual e p_i o alvo de cada classe, procura-se o nível L tal que Σ max(0, L·p_i − v_i) = A; cada
   classe recebe max(0, L·p_i − v_i): quem está mais abaixo do alvo recebe primeiro. Uma classe acima do
   alvo não recebe nada até as outras a alcançarem.
3. Dentro do núcleo, o mesmo enchimento com o peso de cada empresa: iguais (padrão), a proporção atual
   (cada uma recebe na proporção do que já tem) ou pesos personalizados. ETFs vão para o código escolhido.
4. Cotas ≈ valor ÷ última cotação conhecida, arredondando para baixo; a sobra que não fecha uma cota passa
   para o próximo ativo da fila e, no fim, para a renda fixa (se ela fizer parte do alvo).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from findash.plan.places import PATRIMONY, RESERVE

SUGGESTED_BUCKETS = ("renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo")
WEIGHT_MODES = ("iguais", "atual", "personalizado")


@dataclass
class MonthSplit:
    amounts: dict[str, int]  # lugar -> centavos (reserva | patrimonio)
    reserve_priority_cents: int = 0


def split_month(total: int, reserve_gap: int) -> MonthSplit:
    total = max(0, total)
    priority = min(max(0, reserve_gap), total)
    return MonthSplit({RESERVE: priority, PATRIMONY: total - priority}, reserve_priority_cents=priority)


def _largest_remainder(total: int, fractions: dict[str, float]) -> dict[str, int]:
    """Reparte centavos inteiros sem perder nenhum (método do maior resto)."""
    weight = sum(fractions.values())
    if total <= 0 or weight <= 0:
        return {k: 0 for k in fractions}
    raw = {k: total * f / weight for k, f in fractions.items()}
    out = {k: math.floor(v) for k, v in raw.items()}
    leftover = total - sum(out.values())
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:leftover]:
        out[k] += 1
    return out


@dataclass
class AssetTarget:
    key: str  # classe (balde) ou código de negociação
    pct: float  # peso-alvo (qualquer escala)
    current_cents: int


def water_fill(amount: int, targets: list[AssetTarget]) -> dict[str, int]:
    """Enchimento por nível: aproxima do alvo sem vender (ver docstring do módulo)."""
    active = [t for t in targets if t.pct > 0]
    if amount <= 0 or not active:
        return {t.key: 0 for t in targets}
    total_pct = sum(t.pct for t in active)
    weights = {t.key: t.pct / total_pct for t in active}
    values = {t.key: t.current_cents for t in active}

    def need(level: float) -> float:
        return sum(max(0.0, level * weights[k] - values[k]) for k in weights)

    low, high = 0.0, max(values[k] / weights[k] for k in weights) + amount / min(weights.values())
    for _ in range(200):
        mid = (low + high) / 2
        if need(mid) < amount:
            low = mid
        else:
            high = mid
    raw = {k: max(0.0, high * weights[k] - values[k]) for k in weights}
    shares = _largest_remainder(amount, raw) if sum(raw.values()) else {}
    return {t.key: shares.get(t.key, 0) for t in targets}


def core_weights(core_values: dict[str, int], mode: str, custom: dict[str, float] | None) -> dict[str, float]:
    """Peso de cada empresa do núcleo (qualquer escala): iguais, proporção atual ou personalizado.

    Sem dados para o modo pedido (ninguém tem valor, ou falta peso de alguma empresa), vale "iguais".
    """
    if mode == "atual" and sum(core_values.values()) > 0:
        return {t: float(v) for t, v in core_values.items()}
    if mode == "personalizado" and custom and all((custom.get(t) or 0) > 0 for t in core_values):
        return {t: float(custom[t]) for t in core_values}
    return {t: 1.0 for t in core_values}


@dataclass
class AssetSuggestion:
    bucket: str
    ticker: str | None  # None = renda fixa (sem código: Tesouro Selic ou CDB, à escolha)
    amount_cents: int  # do enchimento por nível
    price_cents: int | None
    shares: int | None = None  # ≈ cotas (arredondado para baixo)
    spend_cents: int = 0  # o que de fato vai para este ativo (cotas × preço, ou o valor em R$)
    carried_in_cents: int = 0  # sobra recebida do anterior


@dataclass
class PatrimonySplit:
    buckets: dict[str, int] = field(default_factory=dict)  # balde -> centavos (enchimento por nível)
    items: list[AssetSuggestion] = field(default_factory=list)
    leftover_cents: int = 0  # sobra final (não fecha uma cota e não há renda fixa no alvo)


def split_patrimony(
    amount: int,
    bucket_targets: dict[str, float | None],
    bucket_values: dict[str, int],
    core_values: dict[str, int],
    etf_tickers: dict[str, str | None],
    prices: dict[str, int],
    weights: dict[str, float] | None = None,
) -> PatrimonySplit:
    result = PatrimonySplit()
    eligible = [
        AssetTarget(b, bucket_targets.get(b) or 0, bucket_values.get(b, 0))
        for b in SUGGESTED_BUCKETS
        if (bucket_targets.get(b) or 0) > 0 and (b != "acoes_nucleo" or core_values)
    ]
    result.buckets = {b: v for b, v in water_fill(amount, eligible).items()}
    queue: list[AssetSuggestion] = []
    for bucket in ("etf_global", "etf_brasil"):
        cents = result.buckets.get(bucket, 0)
        if cents > 0:
            ticker = etf_tickers.get(bucket)
            queue.append(AssetSuggestion(bucket, ticker, cents, prices.get(ticker) if ticker else None))
    core_amount = result.buckets.get("acoes_nucleo", 0)
    if core_amount > 0:
        weights = weights or {t: 1.0 for t in core_values}
        core = water_fill(core_amount, [AssetTarget(t, weights.get(t, 0), v) for t, v in sorted(core_values.items())])
        order = sorted(core, key=lambda t: (-core[t], t))  # quem recebe mais vem primeiro na lista
        queue += [AssetSuggestion("acoes_nucleo", t, core[t], prices.get(t)) for t in order if core[t] > 0]
    carry = 0
    for item in queue:
        item.carried_in_cents = carry
        budget = item.amount_cents + carry
        if item.price_cents and item.ticker:
            item.shares = budget // item.price_cents
            item.spend_cents = item.shares * item.price_cents
            carry = budget - item.spend_cents
        else:
            item.spend_cents, carry = budget, 0  # sem cotação conhecida: fica o valor em R$
        result.items.append(item)
    fixed = result.buckets.get("renda_fixa", 0)
    if "renda_fixa" in result.buckets:
        result.items.append(
            AssetSuggestion("renda_fixa", None, fixed, None, spend_cents=fixed + carry, carried_in_cents=carry)
        )
        carry = 0
    result.leftover_cents = carry
    return result
