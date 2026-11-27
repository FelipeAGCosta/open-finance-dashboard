import { describe, expect, it } from "vitest";
import { percentState } from "./percent";

describe("percentState: campos vazios", () => {
  it("todos vazios valem como não preenchido (ok e empty)", () => {
    const state = percentState(["", "", ""]);
    expect(state).toEqual({ nums: [null, null, null], sum: 0, ok: true, empty: true, complete: false, invalid: false });
  });

  it("null conta como vazio, igual ao texto vazio", () => {
    const state = percentState([null, "", null]);
    expect(state.nums).toEqual([null, null, null]);
    expect(state.ok).toBe(true);
    expect(state.empty).toBe(true);
  });
});

describe("percentState: todos preenchidos", () => {
  it("soma de 100 vale", () => {
    const state = percentState(["20", "40", "40"]);
    expect(state).toEqual({ nums: [20, 40, 40], sum: 100, ok: true, empty: false, complete: true, invalid: false });
  });

  it("aceita número além de texto e os limites 0 e 100", () => {
    expect(percentState([60, "40"]).ok).toBe(true);
    const edges = percentState(["100", "0"]);
    expect(edges.ok).toBe(true);
    expect(edges.invalid).toBe(false);
  });

  it("aceita vírgula decimal", () => {
    const state = percentState(["33,5", "33,5", "33"]);
    expect(state.nums).toEqual([33.5, 33.5, 33]);
    expect(state.sum).toBe(100);
    expect(state.ok).toBe(true);
  });

  it("aceita ponto decimal", () => {
    expect(percentState(["33.5", "66.5"]).ok).toBe(true);
  });
});

describe("percentState: tolerância de 0,01 na soma", () => {
  it.each([
    [["33,33", "33,33", "33,34"]],
    [["50", "49,995"]],
    [["50", "50,005"]],
  ])("%j vale (diferença menor que 0,01)", (values) => {
    const state = percentState(values);
    expect(Math.abs(state.sum - 100)).toBeLessThan(0.01);
    expect(state.ok).toBe(true);
  });

  it.each([
    [["50", "49,98"]],
    [["50", "50,02"]],
  ])("%j não vale (diferença maior que 0,01)", (values) => {
    const state = percentState(values);
    expect(state.complete).toBe(true);
    expect(state.invalid).toBe(false);
    expect(state.ok).toBe(false);
  });
});

describe("percentState: soma diferente de 100", () => {
  it("abaixo de 100 não vale", () => {
    const state = percentState(["50", "30", "10"]);
    expect(state.sum).toBe(90);
    expect(state.complete).toBe(true);
    expect(state.invalid).toBe(false);
    expect(state.ok).toBe(false);
  });

  it("acima de 100 não vale, mesmo com cada valor dentro de 0..100", () => {
    const state = percentState(["60", "60"]);
    expect(state.sum).toBe(120);
    expect(state.invalid).toBe(false);
    expect(state.ok).toBe(false);
  });
});

describe("percentState: preenchimento incompleto", () => {
  it("campo vazio no meio não vale, mesmo com os outros somando 100", () => {
    const state = percentState(["50", "", "50"]);
    expect(state.nums).toEqual([50, null, 50]);
    expect(state.sum).toBe(100);
    expect(state.empty).toBe(false);
    expect(state.complete).toBe(false);
    expect(state.invalid).toBe(false);
    expect(state.ok).toBe(false);
  });

  it("um único campo preenchido não vale", () => {
    const state = percentState(["100", null, ""]);
    expect(state.empty).toBe(false);
    expect(state.complete).toBe(false);
    expect(state.ok).toBe(false);
  });
});

describe("percentState: valor inválido", () => {
  it("negativo não vale, mesmo com a soma fechando em 100", () => {
    const state = percentState(["-10", "60", "50"]);
    expect(state.sum).toBe(100);
    expect(state.invalid).toBe(true);
    expect(state.ok).toBe(false);
  });

  it("acima de 100 não vale, mesmo com a soma fechando em 100", () => {
    const state = percentState(["120", "-20"]);
    expect(state.sum).toBe(100);
    expect(state.invalid).toBe(true);
    expect(state.ok).toBe(false);
  });

  it("um valor acima de 100 sozinho já invalida", () => {
    const state = percentState(["100,01", "0"]);
    expect(state.invalid).toBe(true);
    expect(state.ok).toBe(false);
  });

  it("texto não vale e deixa a soma sem número", () => {
    const state = percentState(["abc", "50", "50"]);
    expect(state.nums[0]).toBeNaN();
    expect(state.sum).toBeNaN();
    expect(state.complete).toBe(true);
    expect(state.invalid).toBe(true);
    expect(state.ok).toBe(false);
  });

  it("inválido prevalece sobre o preenchimento incompleto", () => {
    const state = percentState(["dez", "", ""]);
    expect(state.empty).toBe(false);
    expect(state.complete).toBe(false);
    expect(state.invalid).toBe(true);
    expect(state.ok).toBe(false);
  });
});
