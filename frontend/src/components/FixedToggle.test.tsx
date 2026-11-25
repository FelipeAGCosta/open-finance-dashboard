import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Fixed, RecurringRule } from "@/lib/api";
import { useRuleMutation } from "@/lib/queries";
import { FixedToggle } from "./FixedToggle";

const rule = (over: Partial<RecurringRule> = {}): RecurringRule => ({
  id: 7,
  kind: "fixo",
  counterparty: "STREAMING EXEMPLO",
  category: "Assinaturas e serviços digitais",
  status: "automatico",
  manual: false,
  active: true,
  state: "ativo",
  stale: false,
  inactive_after_days: 45,
  avg_monthly: 3990,
  months_count: 6,
  detected: true,
  interval_days: 30,
  paycheck: null,
  schedule: null,
  annual_average: null,
  last_payment: { date: "2026-10-05", cents: 3990 },
  first_payment: "2026-05-05",
  ...over,
});

describe("FixedToggle", () => {
  it("desligar um fixo automático grava a escolha manual 'não'", async () => {
    const user = userEvent.setup();
    const onModeChange = vi.fn();
    render(<FixedToggle rule={rule()} onModeChange={onModeChange} />);
    const toggle = screen.getByRole("switch", { name: "Fixo: STREAMING EXEMPLO" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("automático")).toBeInTheDocument();
    await user.click(toggle);
    expect(onModeChange).toHaveBeenCalledWith("nao");
  });

  it("ligar grava 'sim'; escolha manual mostra 'voltar ao automático'", async () => {
    const user = userEvent.setup();
    const onModeChange = vi.fn();
    render(<FixedToggle rule={rule({ status: "manual_nao", manual: true, active: false })} onModeChange={onModeChange} />);
    await user.click(screen.getByRole("switch"));
    expect(onModeChange).toHaveBeenLastCalledWith("sim");
    await user.click(screen.getByRole("button", { name: /voltar ao automático/ }));
    expect(onModeChange).toHaveBeenLastCalledWith("auto");
  });
});

describe("useRuleMutation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("atualiza a lista na hora (otimista) e envia o modo para a API", async () => {
    let resolve: (value: Response) => void = () => {};
    const fetchMock = vi.fn(() => new Promise<Response>((r) => (resolve = r)));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const initial: Fixed = { fixed: [rule()], salary: [], fixed_monthly: 3990, month: { month: "2026-11", paid: 0, pending: 3990, singles: [] }, commitments: { months: [], total: 0 } };
    client.setQueryData(["fixed"], initial);
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useRuleMutation(), { wrapper });

    act(() => result.current.mutate({ id: 7, mode: "nao" }));
    await waitFor(() => expect(client.getQueryData<Fixed>(["fixed"])?.fixed[0]?.active).toBe(false));
    expect(client.getQueryData<Fixed>(["fixed"])?.fixed[0]?.status).toBe("manual_nao");
    expect(fetchMock).toHaveBeenCalledWith("/api/recurring/7", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ mode: "nao" }) }));

    resolve(new Response(JSON.stringify({ rule: rule({ status: "manual_nao", manual: true, active: false }) }), { status: 200 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("desfaz a mudança se a API recusar", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Regra não encontrada." }), { status: 404 })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["fixed"], { fixed: [rule()], salary: [], fixed_monthly: 3990, month: { month: "2026-11", paid: 0, pending: 3990, singles: [] }, commitments: { months: [], total: 0 } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useRuleMutation(), { wrapper });
    act(() => result.current.mutate({ id: 7, mode: "nao" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Regra não encontrada.");
    expect(client.getQueryData<Fixed>(["fixed"])?.fixed[0]?.active).toBe(true);
  });
});
