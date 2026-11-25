import { describe, expect, it } from "vitest";
import { foldCategories, OTHER } from "./colors";
import { formatMoneyInput, parseMoneyInput } from "./format";
import { percentState } from "./percent";

describe("campo de dinheiro", () => {
  it.each([
    ["1.000,00", 100_000],
    ["1000", 100_000],
    ["R$ 1.234,56", 123_456],
    ["1234.5", 123_450],
    ["80.000", 8_000_000],
    ["0,99", 99],
  ])("%s -> %i centavos", (text, cents) => {
    expect(parseMoneyInput(text)).toBe(cents);
  });

  it("recusa texto que não é dinheiro e deixa vazio como vazio", () => {
    expect(parseMoneyInput("mil reais")).toBeNull();
    expect(parseMoneyInput("-10")).toBeNull();
    expect(parseMoneyInput("   ")).toBeNull();
    expect(formatMoneyInput(100_000)).toBe("1.000,00");
    expect(formatMoneyInput(null)).toBe("");
  });
});

describe("percentuais (divisão do aporte, alocação-alvo)", () => {
  it("vale vazio ou somando 100%", () => {
    expect(percentState(["", "", ""]).ok).toBe(true);
    expect(percentState(["20", "40", "40"]).ok).toBe(true);
    expect(percentState(["33,33", "33,33", "33,34"]).ok).toBe(true);
  });

  it("recusa soma diferente de 100, campos pela metade e valores fora de 0..100", () => {
    const partial = percentState(["50", "", "50"]);
    expect(partial.ok).toBe(false);
    expect(partial.complete).toBe(false);
    expect(percentState(["50", "30", "10"]).sum).toBe(90);
    expect(percentState(["50", "30", "10"]).ok).toBe(false);
    expect(percentState(["120", "-20", "0"]).invalid).toBe(true);
  });
});

describe("categorias do período", () => {
  const colorOf = (name: string) => `var(--cat-${name.length})`;

  it("mostra as 7 maiores do período com a cor fixa de cada uma e junta o resto em Outras", () => {
    const items = Array.from({ length: 10 }, (_, i) => ({ name: `Categoria ${"x".repeat(i)}`, cents: (i + 1) * 1000 }));
    const folded = foldCategories(items, colorOf);
    expect(folded).toHaveLength(8);
    expect(folded.slice(0, 7).map((f) => f.cents)).toEqual([10000, 9000, 8000, 7000, 6000, 5000, 4000]);
    expect(folded[0]?.color).toBe(colorOf(items[9]!.name)); // cor da categoria, não da posição
    expect(folded[7]).toMatchObject({ name: "Outras", cents: 3000 + 2000 + 1000, color: OTHER });
  });

  it("sem cauda, não cria Outras; valores zerados ou negativos ficam fora", () => {
    const folded = foldCategories([{ name: "A", cents: 500 }, { name: "B", cents: 0 }, { name: "C", cents: -10 }], colorOf);
    expect(folded.map((f) => f.name)).toEqual(["A"]);
  });
});
