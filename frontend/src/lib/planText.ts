/** Frases simples da tela Plano (situação da Reserva e do Patrimônio, cada classe frente ao alvo, capacidade). */
import type { ChecklistLine, PatrimonyBucket, Plan } from "./api";

type Format = (v: number | null) => string;
type Tone = "positive" | "warning" | "neutral";

const oneDecimal = (n: number) => n.toLocaleString("pt-BR", { maximumFractionDigits: 1 });

export function reserveStatus(r: Plan["reserve"], format: Format): { status: string; tone: Tone; detail: string } {
  const covers = r.covered_months !== null ? `Cobre ${oneDecimal(r.covered_months)} meses de gastos essenciais.` : "Ainda sem meses fechados para comparar.";
  if (r.target === null) return { status: "Valor a definir", tone: "neutral", detail: "Defina o valor da Reserva em “Ajustar o plano”." };
  if (r.complete) return { status: "Completa", tone: "positive", detail: `${format(r.target)} guardados. ${covers}` };
  return { status: `Faltam ${format(r.gap)}`, tone: "warning", detail: `Meta de ${format(r.target)}. ${covers}` };
}

export function patrimonyStatus(p: Plan["patrimony"]): { status: string; tone: Tone; detail: string } {
  if (!p.target_defined) return { status: "Alvos a definir", tone: "neutral", detail: "Defina os alvos da carteira em “Ajustar o plano”." };
  if (p.off_target === 0) return { status: "No alvo", tone: "positive", detail: "Todas as classes estão perto do alvo." };
  return {
    status: p.off_target === 1 ? "1 classe fora do alvo" : `${p.off_target} classes fora do alvo`,
    tone: "warning",
    detail: "Os aportes do mês vão para as classes abaixo do alvo, sem vender nada.",
  };
}

/** Uma classe frente ao alvo, sem jargão ("faltam R$ X", "no alvo", "acima do alvo — sem novos aportes"). */
export function bucketText(b: PatrimonyBucket, format: Format): string {
  if (b.bucket === "acoes_mantidas") return "só acompanha — sem aportes e sem alvo";
  if (b.state === "sem_alvo") return "sem alvo definido";
  if (b.state === "dentro_teto") return "dentro do teto — sem aportes";
  if (b.state === "acima_teto") return "acima do teto — sem novos aportes";
  if (b.bucket === "acoes_nucleo" && b.needs_core) return `faltam ${format(-(b.deviation_cents ?? 0))} — escolha as empresas do núcleo em “Ajustar o plano”`;
  if (b.state === "abaixo") return b.suggested ? `faltam ${format(-(b.deviation_cents ?? 0))}` : `${format(-(b.deviation_cents ?? 0))} abaixo do alvo — sem novos aportes`;
  if (b.state === "acima") return b.bucket === "acoes_nucleo" ? "acima do alvo: aportes vão para as outras classes até equilibrar" : "acima do alvo — sem novos aportes";
  return b.suggested ? "no alvo" : "no alvo — sem novos aportes";
}

/** "R$ 476,00 → ABCD11 ≈ 4 cotas" */
export function checklistText(line: ChecklistLine): string {
  if (line.ticker && line.shares !== null) return `${line.where} ≈ ${line.shares} cota${line.shares === 1 ? "" : "s"}`;
  return line.where;
}

/** A capacidade do mês em UMA frase. */
export function capacityText(c: Plan["contribution"], format: Format): string {
  const done = c.checklist.length > 0 && c.checklist.every((l) => l.done);
  if (done || c.remaining <= 0) return "Meta do mês cumprida.";
  if (c.projected_surplus <= 0) return "Pelos seus gastos até agora, não sobra dinheiro novo neste mês: aporte o que couber, na ordem da lista.";
  const room = `Pelos seus gastos até agora, sobram ~${format(c.projected_surplus)}`;
  return c.fits ? `${room}: dá para cumprir a meta.` : `${room}: não dá para cumprir a meta inteira. Aporte o que couber, na ordem da lista.`;
}
