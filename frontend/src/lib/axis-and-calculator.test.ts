import { describe, expect, it } from "vitest";
import { CALC_KEY, defaultCalc, loadCalc } from "./calc";
import { axisMoneyFormatter, axisPercentFormatter, niceTicks, paddedDomain } from "./format";

describe("eixo Y adaptativo: rótulos sempre distintos", () => {
  it("variação pequena (~R$ 675 em R$ 35 mil) não repete \"R$ 35 mil\"", () => {
    const [lo, hi] = paddedDomain([3_512_340, 3_538_120, 3_579_870]);
    const ticks = niceTicks(lo, hi, 5);
    const labels = ticks.map(axisMoneyFormatter(ticks));
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    expect(new Set(labels).size).toBe(labels.length);
    expect(ticks.every((t) => t >= lo && t <= hi)).toBe(true);
  });

  it("mostra a marca exata com o menor número de casas", () => {
    const fmt = (ticks: number[]) => ticks.map(axisMoneyFormatter(ticks));
    expect(fmt([3_475_000, 3_500_000, 3_525_000, 3_550_000])).toEqual(["R$ 34,75 mil", "R$ 35,00 mil", "R$ 35,25 mil", "R$ 35,50 mil"]);
    expect(fmt([3_440_000, 3_460_000])).toEqual(["R$ 34,4 mil", "R$ 34,6 mil"]);
    expect(fmt([0, 1_000_000, 2_000_000, 3_000_000])).toEqual(["R$ 0", "R$ 10 mil", "R$ 20 mil", "R$ 30 mil"]);
    expect(fmt([3_475_010, 3_475_020])).toEqual(["R$ 34.750,10", "R$ 34.750,20"]); // nem o valor cheio sem centavos separa
  });

  it("marcas redondas e folga proporcional", () => {
    expect(niceTicks(0, 100, 5)).toEqual([0, 25, 50, 75, 100]);
    expect(paddedDomain([100, 200])).toEqual([85, 215]); // 15% do intervalo de cada lado
    expect(paddedDomain([5000, 5000])).toEqual([4900, 5100]); // sem variação: 2% do valor
  });

  it("porcentagem com casas suficientes", () => {
    const ticks = [0, 0.0025, 0.005];
    expect(ticks.map(axisPercentFormatter(ticks))).toEqual(["0,00%", "0,25%", "0,50%"]);
    expect([0, 0.1].map(axisPercentFormatter([0, 0.1]))).toEqual(["0%", "10%"]);
  });
});

describe("calculadora: data-alvo já preenchida", () => {
  it("padrão = 12 meses à frente", () => {
    expect(defaultCalc("2026-11", "10,00")).toEqual({ saved: "", monthly: "", rate: "10,00", unit: "ano", targetMonth: "2027-11", goal: "" });
  });

  it("lembra a última data; vazia, inválida ou já passada volta ao padrão", () => {
    const fallback = defaultCalc("2026-11", "10,00");
    const stored = (targetMonth: string) => {
      localStorage.setItem(CALC_KEY, JSON.stringify({ ...fallback, targetMonth }));
      return loadCalc(fallback, "2026-11").targetMonth;
    };
    expect(stored("2031-06")).toBe("2031-06");
    expect(stored("")).toBe("2027-11");
    expect(stored("2026-11")).toBe("2027-11");
    expect(stored("junho")).toBe("2027-11");
    localStorage.removeItem(CALC_KEY);
    expect(loadCalc(fallback, "2026-11").targetMonth).toBe("2027-11");
  });
});
