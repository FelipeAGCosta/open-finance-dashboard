/**
 * Cores de dados. A cor segue a ENTIDADE, nunca a posição no gráfico:
 * - categorias de despesa: cor FIXA de cada categoria (índice vindo da API, definido em
 *   config/categorias.yaml); cada gráfico mostra as até 7 maiores DO PERÍODO e agrupa o resto em
 *   "Outras" (cinza);
 * - classes de ativo: ordem fixa; Reserva e Patrimônio: cor fixa.
 * Os valores vêm de variáveis CSS (temas claro e escuro).
 */
import type { Meta } from "./api";

export const SERIES = [1, 2, 3, 4, 5, 6, 7].map((n) => `var(--series-${n})`);
export const OTHER = "var(--series-other)";
export const INCOME = "var(--income)";
export const EXPENSE = "var(--expense)";
export const MAX_CATEGORY_SLICES = 7;
export const OTHERS_LABEL = "Outras";

export const ASSET_CLASS_ORDER = ["Tesouro", "CDB/RDB", "Ações", "FIIs", "BDR", "ETF Brasil", "ETF Global", "Outros"] as const;

export function assetClassColor(name: string): string {
  const index = ASSET_CLASS_ORDER.indexOf(name as (typeof ASSET_CLASS_ORDER)[number]);
  return index >= 0 && index < SERIES.length ? (SERIES[index] as string) : OTHER;
}

export const RESERVE_COLOR = "var(--goal-reserva)";
export const PATRIMONY_COLOR = "var(--goal-patrimonio)";

export function categoryColorResolver(meta: Meta | undefined): (name: string) => string {
  const map = new Map<string, number>();
  meta?.categories.forEach((c) => {
    if (c.color !== null) map.set(c.name, c.color);
  });
  return (name: string) => {
    const index = map.get(name);
    return index !== undefined ? `var(--cat-${index})` : OTHER;
  };
}

/** As até 7 maiores categorias do período, com a cor fixa de cada uma; o resto vira "Outras". */
export function foldCategories<T extends { name: string; cents: number }>(
  items: T[],
  colorOf: (name: string) => string,
  max = MAX_CATEGORY_SLICES,
): { name: string; cents: number; color: string; members: string[] }[] {
  const sorted = [...items].filter((i) => i.cents > 0).sort((a, b) => b.cents - a.cents || a.name.localeCompare(b.name));
  const keep = sorted.length > max ? sorted.slice(0, max) : sorted;
  const rest = sorted.length > max ? sorted.slice(max) : [];
  const out = keep.map((i) => ({ name: i.name, cents: i.cents, color: colorOf(i.name), members: [i.name] }));
  const restTotal = rest.reduce((sum, i) => sum + i.cents, 0);
  if (restTotal > 0) out.push({ name: OTHERS_LABEL, cents: restTotal, color: OTHER, members: rest.map((i) => i.name) });
  return out;
}
