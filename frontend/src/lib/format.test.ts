import { describe, expect, it } from "vitest";
import { HIDDEN, formatDate, formatMoney, formatMonth, formatNumber, formatPercent } from "./format";

describe("formatMoney", () => {
  it("formata centavos em reais no padrão brasileiro", () => {
    expect(formatMoney(123456)).toBe("R$ 1.234,56");
    expect(formatMoney(5)).toBe("R$ 0,05");
    expect(formatMoney(0)).toBe("R$ 0,00");
  });

  it("negativos com hífen e positivos com + quando pedido", () => {
    expect(formatMoney(-9990)).toBe("-R$ 99,90");
    expect(formatMoney(9990, { signed: true })).toBe("+R$ 99,90");
    expect(formatMoney(-9990, { signed: true })).toBe("-R$ 99,90");
    expect(formatMoney(0, { signed: true })).toBe("R$ 0,00");
  });

  it("formato compacto para eixos", () => {
    expect(formatMoney(2_651_358, { compact: true })).toBe("R$ 26,5 mil");
    expect(formatMoney(150_000_000, { compact: true })).toBe("R$ 1,5 mi");
  });

  it("esconde o valor com o botão de olho", () => {
    expect(formatMoney(123456, { hidden: true })).toBe(`R$ ${HIDDEN}`);
    expect(formatMoney(-1, { hidden: true, signed: true })).toBe("R$ ••••");
  });

  it("ausente vira travessão", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("usa vírgula decimal e sinal opcional", () => {
    expect(formatPercent(0.177)).toBe("17,7%");
    expect(formatPercent(0.0526, { precise: true, signed: true })).toBe("+5,26%");
    expect(formatPercent(-0.0123, { precise: true })).toBe("-1,23%");
    expect(formatPercent(-0.000001, { precise: true })).toBe("0,00%"); // sem "-0,00%"
    expect(formatPercent(null)).toBe("—");
  });
});

describe("datas e meses", () => {
  it("datas de calendário não mudam com o fuso", () => {
    expect(formatDate("2026-11-03")).toBe("03/11/2026");
    expect(formatDate("2026-11-03", "day")).toBe("03 de nov");
    expect(formatDate("2026-11-03", "long")).toBe("3 de novembro de 2026");
  });

  it("meses por extenso e curtos", () => {
    expect(formatMonth("2026-10")).toBe("outubro de 2026");
    expect(formatMonth("2026-10", "title")).toBe("Outubro de 2026");
    expect(formatMonth("2026-03", "short")).toBe("mar/26");
  });

  it("quantidades com casas decimais", () => {
    expect(formatNumber(0.25999)).toBe("0,25999");
    expect(formatNumber(1500)).toBe("1.500");
  });
});
