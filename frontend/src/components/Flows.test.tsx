import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowsLine } from "./Flows";

describe("Aportei · Resgatei · Saldo do mês", () => {
  it("mostra sempre os três valores, nunca só o líquido", () => {
    render(<FlowsLine flows={{ contributions: 150_000, redemptions: 50_000, net: 100_000 }} />);
    expect(screen.getByText(/Aportei/)).toHaveTextContent("Aportei R$ 1.500,00");
    expect(screen.getByText(/Resgatei/)).toHaveTextContent("Resgatei R$ 500,00");
    expect(screen.getByText(/Saldo do mês/)).toHaveTextContent("Saldo do mês +R$ 1.000,00");
    expect(screen.queryByText(/resgatou mais do que aportou/)).not.toBeInTheDocument();
  });

  it("quando o saldo é negativo, explica em linguagem simples", () => {
    render(<FlowsLine flows={{ contributions: 100_000, redemptions: 250_000, net: -150_000 }} />);
    expect(screen.getByText(/Saldo do mês/)).toHaveTextContent("-R$ 1.500,00");
    expect(screen.getByText(/resgatou mais do que aportou/)).toHaveTextContent("saíram R$ 1.500,00 dos investimentos");
  });
});
