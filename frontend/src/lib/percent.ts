/** Validação de percentuais digitados (divisão do aporte, alocação-alvo): vazios ou somando 100%. */
export interface PercentState {
  nums: (number | null)[];
  sum: number;
  ok: boolean;
  empty: boolean;
  complete: boolean;
  invalid: boolean;
}

export function percentState(values: (string | number | null)[]): PercentState {
  const nums = values.map((v) => (v === "" || v === null ? null : Number(String(v).replace(",", "."))));
  const filled = nums.filter((n): n is number => n !== null);
  const invalid = nums.some((n) => n !== null && (Number.isNaN(n) || n < 0 || n > 100));
  const sum = filled.reduce((s, n) => s + n, 0);
  const empty = filled.length === 0;
  const complete = filled.length === nums.length;
  const ok = !invalid && (empty || (complete && Math.abs(sum - 100) < 0.01));
  return { nums, sum, ok, empty, complete, invalid };
}
