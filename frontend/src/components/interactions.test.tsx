import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dismissToast, showToast } from "@/lib/toast";
import { DonutChart } from "./charts";
import { ScopeDialog } from "./Dialog";
import { Toaster } from "./Toast";

const money = (v: number) => `R$ ${(v / 100).toFixed(2)}`;

describe("DonutChart", () => {
  const data = [
    { name: "Moradia", value: 6000, color: "var(--cat-1)" },
    { name: "Mercado", value: 4000, color: "var(--cat-3)" },
  ];

  it("o centro mostra o total e, ao focar uma fatia pela legenda, o nome, o valor e a % dela", async () => {
    const user = userEvent.setup();
    render(<DonutChart data={data} centerLabel="no mês" centerValue="R$ 100,00" formatValue={money} />);
    expect(screen.getByText("no mês")).toBeInTheDocument();
    await user.hover(screen.getByRole("button", { name: /Mercado/ }));
    expect(await screen.findByText("R$ 40.00", { selector: "span.tnum.text-\\[18px\\]" })).toBeInTheDocument();
    expect(screen.queryByText("no mês")).not.toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(); // sem caixa por cima do centro
    await user.unhover(screen.getByRole("button", { name: /Mercado/ }));
    expect(await screen.findByText("no mês")).toBeInTheDocument();
  });

  it("a legenda repete nome, valor e % (a cor não é a única pista)", () => {
    render(<DonutChart data={data} centerLabel="no mês" centerValue="x" formatValue={money} />);
    expect(screen.getByRole("button", { name: "Moradia: R$ 60.00, 60,0%" })).toBeInTheDocument();
  });
});

describe("ScopeDialog", () => {
  it("pergunta o escopo e devolve a escolha", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn();
    render(
      <ScopeDialog open title="Mudar a categoria" change="Padaria" counterparty="PADARIA EXEMPLO" allowCounterparty onChoose={onChoose} onClose={() => {}} />,
    );
    expect(screen.getByRole("dialog", { name: "Mudar a categoria" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Esta e todas de PADARIA EXEMPLO/ }));
    expect(onChoose).toHaveBeenCalledWith("counterparty");
    await user.click(screen.getByRole("button", { name: /Só esta/ }));
    expect(onChoose).toHaveBeenLastCalledWith("one");
  });

  it("sem contraparte identificada só oferece 'Só esta'; Esc fecha", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ScopeDialog open title="Marcar como fixo" change="x" counterparty={null} allowCounterparty={false} onChoose={() => {}} onClose={onClose} />);
    expect(screen.queryByRole("button", { name: /Esta e todas/ })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Toaster", () => {
  afterEach(() => act(() => dismissToast()));

  it("confirma a ação e permite desfazer", async () => {
    const user = userEvent.setup();
    const onUndo = vi.fn(async () => {});
    render(<Toaster />);
    act(() => showToast({ title: "Categoria: Mercado", detail: "Só nesta transação.", onUndo }));
    expect(screen.getByRole("status")).toHaveTextContent("Categoria: Mercado");
    await user.click(screen.getByRole("button", { name: /Desfazer/ }));
    expect(onUndo).toHaveBeenCalledOnce();
    expect(await screen.findByText("Desfeito")).toBeInTheDocument();
  });
});
