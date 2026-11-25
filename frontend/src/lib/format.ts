/** Formatação pt-BR com Intl. Valores chegam da API em centavos inteiros. */

export const HIDDEN = "••••";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brlCompact = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  notation: "compact",
  maximumFractionDigits: 1,
});
const pctFormat = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
const pctPrecise = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const numberFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 });

export interface MoneyOptions {
  /** Mostra "+" em valores positivos (entradas). */
  signed?: boolean;
  /** "R$ 12,3 mil" para eixos e rótulos curtos. */
  compact?: boolean;
  /** Esconde o valor (botão de olho). */
  hidden?: boolean;
}

/** Intl usa espaço não separável (U+00A0) entre "R$" e o número; normalizamos para testes e cópia. */
const clean = (text: string) => text.replace(/\u00a0/g, " ").replace(/\u2212/g, "-");

export function formatMoney(cents: number | null | undefined, options: MoneyOptions = {}): string {
  if (cents === null || cents === undefined || Number.isNaN(cents)) return "—";
  if (options.hidden) return `R$ ${HIDDEN}`;
  const value = cents / 100;
  const text = clean((options.compact ? brlCompact : brl).format(Math.abs(value)));
  if (value < 0) return `-${text}`;
  if (options.signed && value > 0) return `+${text}`;
  return text;
}

const brlAxis = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 0 });

/** Rótulo curto de eixo: "R$ 40 mil", "R$ 1 mi" (o valor exato fica no tooltip e na tabela). */
export function formatAxisMoney(cents: number, hidden = false): string {
  if (hidden) return HIDDEN;
  const value = cents / 100;
  const text = clean((Math.abs(value) < 10_000 ? brlCompact : brlAxis).format(Math.abs(value)));
  return value < 0 ? `-${text}` : text;
}

// ------------------------------------------------------------------ eixos adaptativos (gráficos de linha)

/** Folga proporcional ao intervalo dos dados (15%); sem variação, 2% do valor. */
export function paddedDomain(values: number[], fallback = 100): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (!finite.length) return [0, fallback];
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const pad = (max - min) * 0.15 || Math.abs(max) * 0.02 || fallback;
  return [min - pad, max + pad];
}

/** Marcas "redondas" (1, 2, 2,5 ou 5 × 10^k) dentro de [lo, hi]: pelo menos 2, perto de `count`. */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!(hi > lo)) hi = lo + 1;
  let raw = (hi - lo) / Math.max(1, count - 1);
  for (let attempt = 0; attempt < 4; attempt++) {
    const power = 10 ** Math.floor(Math.log10(raw));
    const step = ([1, 2, 2.5, 5, 10].find((m) => m * power >= raw) ?? 10) * power;
    const ticks: number[] = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) ticks.push(Number(t.toPrecision(12)));
    if (ticks.length >= 2) return ticks;
    raw /= 2;
  }
  return [lo, hi];
}

const exactAt = (value: number, digits: number) => Math.abs(value * 10 ** digits - Math.round(value * 10 ** digits)) < 1e-6;
const compactUnit = (reais: number) => (Math.abs(reais) >= 1e6 ? 1e6 : Math.abs(reais) >= 1e3 ? 1e3 : 1);

/**
 * Formatador de eixo de dinheiro para um conjunto de marcas: usa o rótulo mais curto que mostra cada marca
 * EXATA e todas DIFERENTES ("R$ 35 mil" → "R$ 34,75 mil" → "R$ 34.750"); nunca repete o mesmo rótulo.
 */
export function axisMoneyFormatter(ticks: number[], hidden = false): (cents: number) => string {
  if (hidden) return () => HIDDEN;
  const reais = ticks.map((t) => t / 100);
  const candidates: ((v: number) => string)[] = [0, 1, 2]
    .filter((d) => reais.every((v) => exactAt(v / compactUnit(v), d)))
    .map((d) => {
      const f = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", minimumFractionDigits: d, maximumFractionDigits: d });
      return (v: number) => clean(f.format(v));
    });
  const whole = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
  const full = (v: number) => clean(brl.format(v));
  candidates.push((v) => clean(whole.format(v)));
  const pick = candidates.find((f) => new Set(reais.map(f)).size === reais.length) ?? full;
  return (cents: number) => pick(cents / 100);
}

/** O mesmo para eixos de porcentagem (valores em fração: 0,012 = 1,2%). */
export function axisPercentFormatter(ticks: number[]): (value: number) => string {
  for (const digits of [0, 1, 2, 3]) {
    if (!ticks.every((t) => exactAt(t * 100, digits))) continue;
    const f = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits });
    const label = (v: number) => clean(f.format(Math.abs(v) < 1e-12 ? 0 : v));
    if (new Set(ticks.map(label)).size === ticks.length) return label;
  }
  return (v: number) => formatPercent(v, { precise: true });
}

export function formatPercent(value: number | null | undefined, options: { precise?: boolean; signed?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const rounded = Math.abs(value) < 0.00005 ? 0 : value;
  const text = clean((options.precise ? pctPrecise : pctFormat).format(rounded));
  return options.signed && rounded > 0 ? `+${text}` : text;
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : clean(numberFormat.format(value));
}

/** Campo de dinheiro digitado ("1.234,56", "1234.5", "R$ 1.000") -> centavos; null se inválido ou vazio. */
export function parseMoneyInput(text: string): number | null {
  const raw = text.replace(/R\$|\s/g, "").trim();
  if (!raw) return null;
  if (!/^\d[\d.,]*$/.test(raw)) return null;
  const lastComma = raw.lastIndexOf(",");
  const lastDot = raw.lastIndexOf(".");
  let normalized: string;
  if (lastComma > lastDot) normalized = raw.replace(/\./g, "").replace(",", ".");
  else if (lastDot > lastComma && raw.length - lastDot - 1 !== 3) normalized = raw.replace(/,/g, "");
  else normalized = raw.replace(/[.,]/g, "");
  const value = Number(normalized);
  return Number.isFinite(value) ? Math.round(value * 100) : null;
}

/** Centavos -> texto para campo de dinheiro ("1.000,00"), sem "R$". */
export function formatMoneyInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return clean(new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(cents / 100));
}

/** "2026-10" -> "outubro de 2026" (ou "out/26" no formato curto). */
export function formatMonth(month: string, style: "long" | "short" | "title" = "long"): string {
  const [year, mon] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year ?? 2000, (mon ?? 1) - 1, 15));
  if (style === "short") {
    const name = new Intl.DateTimeFormat("pt-BR", { month: "short", timeZone: "UTC" }).format(date).replace(".", "");
    return `${name}/${String(year).slice(2)}`;
  }
  const text = new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
  return style === "title" ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Data ISO "AAAA-MM-DD" (sem fuso: data de calendário) -> "24/11/2026" ou "24 nov". */
export function formatDate(iso: string | null | undefined, style: "short" | "day" | "long" = "short"): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(y ?? 2000, (m ?? 1) - 1, d ?? 1));
  if (style === "day") {
    return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", timeZone: "UTC" }).format(date).replace(".", "");
  }
  if (style === "long") {
    return new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(date);
  }
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(date);
}

/** Data/hora UTC da API ("...Z") no fuso do navegador. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(iso));
}

/** Data/hora UTC da API ("...Z") -> "24/11 20:28" no fuso do navegador. */
export function formatDayTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parts = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}/${get("month")} ${get("hour")}:${get("minute")}`;
}

export function relativeDays(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60000);
  const rtf = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
  if (Math.abs(minutes) < 60) return rtf.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return rtf.format(-hours, "hour");
  return rtf.format(-Math.round(hours / 24), "day");
}
