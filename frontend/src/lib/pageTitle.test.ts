import { describe, expect, it } from "vitest";
import { APP_NAME, pageTitle } from "./pageTitle";

describe("pageTitle", () => {
  it("junta a seção e o nome do app com ponto médio", () => {
    expect(pageTitle("Gastos")).toBe("Gastos · Finanças");
    expect(pageTitle("Visão geral")).toBe("Visão geral · Finanças");
  });

  it("ignora espaços sobrando em volta da seção", () => {
    expect(pageTitle("  Plano ")).toBe("Plano · Finanças");
  });

  it("sem seção, fica só o nome do app", () => {
    expect(pageTitle("")).toBe(APP_NAME);
    expect(pageTitle("   ")).toBe("Finanças");
  });
});
