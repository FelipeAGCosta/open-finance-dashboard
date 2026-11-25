/**
 * Calculadora de investimento (independente do Plano: nada aqui é salvo no servidor).
 *
 * Juros compostos com taxa mensal i; os aportes entram no FIM de cada mês, a partir do mês seguinte ao atual:
 *   saldo depois de n meses = guardado × (1+i)^n + aporte × ((1+i)^n − 1) / i
 *   aporte necessário       = (alvo − guardado × (1+i)^n) × i / ((1+i)^n − 1)
 * Conversão entre taxa ao ano (a) e ao mês (i): i = (1+a)^(1/12) − 1 e a = (1+i)^12 − 1.
 * Valores em centavos.
 */

export const annualToMonthly = (annual: number) => (1 + annual) ** (1 / 12) - 1;
export const monthlyToAnnual = (monthly: number) => (1 + monthly) ** 12 - 1;

export function addMonths(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = (y ?? 2000) * 12 + (m ?? 1) - 1 + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** Meses de `from` (exclusive) até `to` (inclusive): 2026-11 → 2027-11 = 12. */
export function monthsBetween(from: string, to: string): number {
  const [fy, fm] = from.split("-").map(Number);
  const [ty, tm] = to.split("-").map(Number);
  return (ty ?? 0) * 12 + (tm ?? 0) - ((fy ?? 0) * 12 + (fm ?? 0));
}

export interface CalcRow {
  /** 0 = hoje; k = depois de k meses. */
  index: number;
  month: string;
  /** O que saiu do bolso: valor já guardado + aportes feitos até aqui. */
  contributed: number;
  /** Juros acumulados (saldo − aportado). */
  interest: number;
  balance: number;
}

/** Evolução mês a mês, de hoje até `months` meses à frente. */
export function simulate(saved: number, monthly: number, rate: number, months: number, start: string): CalcRow[] {
  const rows: CalcRow[] = [{ index: 0, month: start, contributed: saved, interest: 0, balance: saved }];
  let value = saved;
  for (let k = 1; k <= months; k += 1) {
    value = value * (1 + rate) + monthly;
    const balance = Math.round(value);
    const contributed = saved + monthly * k;
    rows.push({ index: k, month: addMonths(start, k), contributed, interest: balance - contributed, balance });
  }
  return rows;
}

export function futureValue(saved: number, monthly: number, rate: number, months: number): number {
  if (months <= 0) return saved;
  if (rate === 0) return saved + monthly * months;
  const growth = (1 + rate) ** months;
  return Math.round(saved * growth + (monthly * (growth - 1)) / rate);
}

/** Aporte mensal para chegar ao alvo em `months` meses (arredondado para cima; 0 se já chega sem aportar). */
export function requiredMonthly(saved: number, target: number, rate: number, months: number): number | null {
  if (months <= 0) return null;
  if (rate === 0) return Math.max(0, Math.ceil((target - saved) / months));
  const growth = (1 + rate) ** months;
  // o arredondamento a 6 casas evita que um erro de ponto flutuante (688,4900000001) vire um centavo a mais
  return Math.max(0, Math.ceil(Number((((target - saved * growth) * rate) / (growth - 1)).toFixed(6))));
}

/** Em quantos meses o saldo alcança o alvo (0 = já alcançou; null = não chega em 100 anos). */
export function monthsToReach(saved: number, target: number, monthly: number, rate: number, limit = 1200): number | null {
  if (saved >= target) return 0;
  let value = saved;
  for (let k = 1; k <= limit; k += 1) {
    value = value * (1 + rate) + monthly;
    if (value >= target - 0.5) return k;
  }
  return null;
}

/** "10" ou "10,5" -> 0.10 / 0.105; null se vazio, inválido ou fora de 0..max (em %). */
export function parsePercent(text: string, max = 100): number | null {
  if (!text.trim()) return null;
  const value = Number(text.trim().replace(",", "."));
  return Number.isNaN(value) || value < 0 || value > max ? null : value / 100;
}

/** 0.105 -> "10,5" (até `digits` casas, sem zeros à direita). */
export const percentText = (rate: number | null | undefined, digits = 2) =>
  rate === null || rate === undefined ? "" : String(+(rate * 100).toFixed(digits)).replace(".", ",");

export type RateUnit = "ano" | "mes";

/** Taxa mensal a partir do que foi digitado, ao ano ou ao mês. */
export function monthlyRateOf(text: string, unit: RateUnit): number | null {
  const typed = parsePercent(text, unit === "ano" ? 100 : 10);
  if (typed === null) return null;
  return unit === "ano" ? annualToMonthly(typed) : typed;
}

/** Texto da taxa ao trocar a unidade (mesma taxa, convertida com juros compostos). */
export function convertRateText(text: string, from: RateUnit, to: RateUnit): string {
  const typed = parsePercent(text, from === "ano" ? 100 : 10);
  if (typed === null || from === to) return text;
  return to === "mes" ? percentText(annualToMonthly(typed), 4) : percentText(monthlyToAnnual(typed), 2);
}

// ------------------------------------------------------------------ últimos valores digitados (só neste navegador)

export interface CalcInputs {
  saved: string;
  monthly: string;
  rate: string;
  unit: RateUnit;
  targetMonth: string;
  goal: string;
}

export const CALC_KEY = "findash:calculadora";
export const DEFAULT_HORIZON_MONTHS = 12;

/** Valores iniciais: tudo vazio, a taxa padrão e a data-alvo 12 meses à frente (o resultado já aparece). */
export function defaultCalc(month: string, rate: string): CalcInputs {
  return { saved: "", monthly: "", rate, unit: "ano", targetMonth: addMonths(month, DEFAULT_HORIZON_MONTHS), goal: "" };
}

/** Últimos valores deste navegador; data-alvo ausente, inválida ou já passada (≤ `month`) volta ao padrão. */
export function loadCalc(fallback: CalcInputs, month?: string): CalcInputs {
  try {
    const raw = localStorage.getItem(CALC_KEY);
    if (!raw) return fallback;
    const data = JSON.parse(raw) as Partial<Record<keyof CalcInputs, unknown>>;
    const text = (key: keyof CalcInputs) => (typeof data[key] === "string" ? (data[key] as string) : fallback[key]);
    return {
      saved: text("saved"), monthly: text("monthly"), rate: text("rate"), unit: data.unit === "mes" ? "mes" : "ano",
      targetMonth:
        /^\d{4}-\d{2}$/.test(text("targetMonth")) && (!month || text("targetMonth") > month) ? text("targetMonth") : fallback.targetMonth,
      goal: text("goal"),
    };
  } catch {
    return fallback; // navegador sem armazenamento (ou valor corrompido): começa vazio
  }
}

export function saveCalc(inputs: CalcInputs): void {
  try {
    localStorage.setItem(CALC_KEY, JSON.stringify(inputs));
  } catch {
    /* sem armazenamento: a calculadora funciona, só não lembra */
  }
}

export function clearCalc(): void {
  try {
    localStorage.removeItem(CALC_KEY);
  } catch {
    /* idem */
  }
}
