import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChecklistLine, PatrimonyBucket, Plan } from "./api";
import {
  CALC_KEY,
  addMonths,
  annualToMonthly,
  clearCalc,
  convertRateText,
  futureValue,
  loadCalc,
  monthlyRateOf,
  monthlyToAnnual,
  monthsBetween,
  monthsToReach,
  parsePercent,
  percentText,
  requiredMonthly,
  saveCalc,
  simulate,
} from "./calc";
import { bucketText, capacityText, checklistText, patrimonyStatus, reserveStatus } from "./planText";

const money = (v: number | null) => (v === null ? "—" : `R$ ${(v / 100).toLocaleString("pt-BR")}`);

describe("calculadora de investimento (contas conferidas à mão)", () => {
  it("converte a taxa ao ano em ao mês e de volta com juros compostos", () => {
    // 12% a.a. -> 1,12^(1/12) − 1 = 0,948879% a.m. (e não 1%: 12 ÷ 12 seria juros simples)
    expect(annualToMonthly(0.12)).toBeCloseTo(0.00948879, 8);
    // 1% a.m. -> 1,01^12 − 1 = 12,6825% a.a.
    expect(monthlyToAnnual(0.01)).toBeCloseTo(0.126825, 6);
    expect(monthlyToAnnual(annualToMonthly(0.1))).toBeCloseTo(0.1, 12);
    // o que aparece no campo ao trocar a unidade
    expect(convertRateText("12", "ano", "mes")).toBe("0,9489");
    expect(convertRateText("1", "mes", "ano")).toBe("12,68");
    expect(convertRateText("abc", "ano", "mes")).toBe("abc"); // inválido: não mexe
    expect(monthlyRateOf("1", "mes")).toBe(0.01);
    expect(monthlyRateOf("12", "ano")).toBeCloseTo(0.00948879, 8);
    expect(monthlyRateOf("15", "mes")).toBeNull(); // mais de 10% ao mês: provavelmente erro de digitação
  });

  it("quanto terei na data: guardado + aportes + juros", () => {
    // R$ 10.000 guardados + R$ 500/mês a 1% a.m. por 12 meses:
    // 10.000 × 1,126825 = 11.268,25; aportes: 500 × (0,126825 ÷ 0,01) = 500 × 12,6825 = 6.341,25 -> 17.609,50
    expect(futureValue(1_000_000, 50_000, 0.01, 12)).toBe(1_760_950);
    const rows = simulate(1_000_000, 50_000, 0.01, 12, "2026-11");
    expect(rows).toHaveLength(13);
    expect(rows[0]).toEqual({ index: 0, month: "2026-11", contributed: 1_000_000, interest: 0, balance: 1_000_000 });
    // 1º mês: 10.000 × 1,01 + 500 = 10.600 (100 de juros)
    expect(rows[1]).toEqual({ index: 1, month: "2026-12", contributed: 1_050_000, interest: 10_000, balance: 1_060_000 });
    // no fim: 16.000 saíram do bolso (10.000 + 12 × 500) e 1.609,50 são juros
    expect(rows[12]).toEqual({ index: 12, month: "2027-11", contributed: 1_600_000, interest: 160_950, balance: 1_760_950 });
    // com a taxa digitada ao ano: 10% a.a. por 24 meses -> 10.000 × 1,21 + 500 × 26,3351 = 25.267,56
    expect(futureValue(1_000_000, 50_000, annualToMonthly(0.1), 24)).toBe(2_526_756);
  });

  it("valor já guardado sozinho e aporte zero", () => {
    // só o guardado: 10.000 a 12% a.a. por 2 anos = 10.000 × 1,12² = 12.544,00
    expect(futureValue(1_000_000, 0, annualToMonthly(0.12), 24)).toBe(1_254_400);
    // sem rendimento: só soma
    expect(futureValue(100_000, 10_000, 0, 12)).toBe(220_000);
    // nada guardado e nada aportado: zero para sempre
    expect(futureValue(0, 0, 0.01, 120)).toBe(0);
    expect(monthsToReach(0, 100_000, 0, 0.01)).toBeNull();
    // aporte zero, mas o guardado rende: 10.000 a 1% a.m. passa de 11.000 no 10º mês (1,01^10 = 1,1046)
    expect(monthsToReach(1_000_000, 1_100_000, 0, 0.01)).toBe(10);
  });

  it("aporte necessário para chegar ao valor desejado na data", () => {
    // 20.000 em 12 meses, tendo 10.000, a 1% a.m.: (20.000 − 11.268,25) ÷ 12,6825 = 688,488 -> R$ 688,49 (para cima)
    expect(requiredMonthly(1_000_000, 2_000_000, 0.01, 12)).toBe(68_849);
    expect(futureValue(1_000_000, 68_849, 0.01, 12)).toBeGreaterThanOrEqual(2_000_000);
    expect(futureValue(1_000_000, 68_848, 0.01, 12)).toBeLessThan(2_000_000);
    // o guardado sozinho já chega: não precisa aportar
    expect(requiredMonthly(1_000_000, 1_100_000, 0.01, 12)).toBe(0);
    // sem rendimento: (12.000 − 0) ÷ 12 = 1.000
    expect(requiredMonthly(0, 1_200_000, 0, 12)).toBe(100_000);
    expect(requiredMonthly(0, 1_200_000, 0.01, 0)).toBeNull(); // data que já passou
  });

  it("mês em que o valor desejado é atingido", () => {
    // 1.000/mês a 1% a.m.: 11 meses = 11.566,83; 12 meses = 12.682,50 -> chega a 12.000 no 12º mês
    expect(monthsToReach(0, 1_200_000, 100_000, 0.01)).toBe(12);
    expect(addMonths("2026-11", 12)).toBe("2027-11");
    expect(monthsToReach(500_000, 100_000, 0, 0.01)).toBe(0); // já tem
    expect(monthsToReach(0, 1_200_000, 100_000, 0)).toBe(12); // sem juros: 12 × 1.000
  });

  it("meses e percentuais digitados", () => {
    expect(addMonths("2026-11", 14)).toBe("2028-01");
    expect(addMonths("2026-01", -1)).toBe("2025-12");
    expect(monthsBetween("2026-11", "2031-06")).toBe(55);
    expect(parsePercent("10,5")).toBeCloseTo(0.105);
    expect(parsePercent("")).toBeNull();
    expect(parsePercent("-1")).toBeNull();
    expect(percentText(0.105)).toBe("10,5");
  });
});

describe("a calculadora lembra os últimos valores só neste navegador", () => {
  const empty = { saved: "", monthly: "", rate: "10", unit: "ano" as const, targetMonth: "", goal: "" };
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("guarda, lê e limpa", () => {
    saveCalc({ ...empty, saved: "1.000,00", unit: "mes", targetMonth: "2031-06" });
    expect(loadCalc(empty)).toEqual({ ...empty, saved: "1.000,00", unit: "mes", targetMonth: "2031-06" });
    clearCalc();
    expect(localStorage.getItem(CALC_KEY)).toBeNull();
    expect(loadCalc(empty)).toEqual(empty);
  });

  it("valor corrompido ou navegador sem armazenamento não quebra", () => {
    localStorage.setItem(CALC_KEY, "{isto não é json");
    expect(loadCalc(empty)).toEqual(empty);
    localStorage.setItem(CALC_KEY, JSON.stringify({ saved: 5, targetMonth: "dezembro", unit: "x" }));
    expect(loadCalc(empty)).toEqual(empty);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    expect(() => saveCalc(empty)).not.toThrow();
    expect(loadCalc(empty)).toEqual(empty);
  });
});

describe("frases da tela Plano", () => {
  const bucket = (over: Partial<PatrimonyBucket>): PatrimonyBucket => ({
    bucket: "renda_fixa", label: "Renda fixa", current: 0, current_pct: 0, target_pct: 0.2, target_cents: 200_000, deviation_pct: -0.2,
    deviation_cents: -200_000, suggested: true, cap: false, over_cap: false, state: "abaixo", needs_core: false, members: [], ...over,
  });

  it("cada classe frente ao alvo, sem jargão", () => {
    expect(bucketText(bucket({}), money)).toBe("faltam R$ 2.000");
    expect(bucketText(bucket({ state: "no_alvo" }), money)).toBe("no alvo");
    expect(bucketText(bucket({ state: "acima", bucket: "etf_global" }), money)).toBe("acima do alvo — sem novos aportes");
    // núcleo acima do alvo: uma frase clara
    expect(bucketText(bucket({ state: "acima", bucket: "acoes_nucleo" }), money)).toBe("acima do alvo: aportes vão para as outras classes até equilibrar");
    expect(bucketText(bucket({ bucket: "acoes_nucleo", needs_core: true }), money)).toContain("escolha as empresas do núcleo");
    // FIIs nunca recebem aporte, mesmo abaixo do alvo
    expect(bucketText(bucket({ bucket: "fiis", suggested: false }), money)).toBe("R$ 2.000 abaixo do alvo — sem novos aportes");
    expect(bucketText(bucket({ bucket: "acoes_mantidas", state: "sem_alvo", suggested: false }), money)).toBe("só acompanha — sem aportes e sem alvo");
    expect(bucketText(bucket({ bucket: "satelite", state: "acima_teto", cap: true }), money)).toBe("acima do teto — sem novos aportes");
    expect(bucketText(bucket({ bucket: "satelite", state: "dentro_teto", cap: true }), money)).toBe("dentro do teto — sem aportes");
    for (const state of ["abaixo", "no_alvo", "acima", "dentro_teto", "acima_teto", "sem_alvo"] as const)
      expect(bucketText(bucket({ state }), money)).not.toContain("p.p.");
  });

  it("resumo da Reserva e do Patrimônio em palavras", () => {
    const reserve = { target: 900_000, current: 900_000, gap: 0, complete: true, covered_months: 6.04 } as Plan["reserve"];
    expect(reserveStatus(reserve, money)).toEqual({ status: "Completa", tone: "positive", detail: "R$ 9.000 guardados. Cobre 6 meses de gastos essenciais." });
    expect(reserveStatus({ ...reserve, current: 700_000, gap: 200_000, complete: false, covered_months: 4.7 }, money).status).toBe("Faltam R$ 2.000");
    expect(reserveStatus({ ...reserve, target: null }, money).status).toBe("Valor a definir");
    const patrimony = { target_defined: true, off_target: 2 } as Plan["patrimony"];
    expect(patrimonyStatus(patrimony).status).toBe("2 classes fora do alvo");
    expect(patrimonyStatus({ ...patrimony, off_target: 1 }).status).toBe("1 classe fora do alvo");
    expect(patrimonyStatus({ ...patrimony, off_target: 0 }).status).toBe("No alvo");
    expect(patrimonyStatus({ ...patrimony, target_defined: false }).status).toBe("Alvos a definir");
  });

  it("linha da checklist e capacidade em uma frase, sem número negativo", () => {
    const line = (over: Partial<ChecklistLine>): ChecklistLine => ({ where: "ABCD11", amount: 47_600, detected: 0, shares: 4, price: 11_900, ticker: "ABCD11", done: false, ...over });
    expect(checklistText(line({}))).toBe("ABCD11 ≈ 4 cotas");
    expect(checklistText(line({ shares: 1 }))).toBe("ABCD11 ≈ 1 cota");
    expect(checklistText(line({ where: "renda fixa (Tesouro Selic ou CDB)", ticker: null, shares: null }))).toBe("renda fixa (Tesouro Selic ou CDB)");
    const c = { checklist: [line({})], remaining: 100_000, projected_surplus: 150_000, fits: true } as Plan["contribution"];
    expect(capacityText(c, money)).toBe("Pelos seus gastos até agora, sobram ~R$ 1.500: dá para cumprir a meta.");
    expect(capacityText({ ...c, projected_surplus: 40_000, fits: false }, money)).toBe(
      "Pelos seus gastos até agora, sobram ~R$ 400: não dá para cumprir a meta inteira. Aporte o que couber, na ordem da lista.",
    );
    const negative = capacityText({ ...c, projected_surplus: -271_248, fits: false }, money);
    expect(negative).toContain("não sobra dinheiro novo");
    expect(negative).not.toMatch(/-|−/);
    expect(capacityText({ ...c, checklist: [line({ done: true })] }, money)).toBe("Meta do mês cumprida.");
  });
});
