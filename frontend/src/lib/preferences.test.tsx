import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { Money } from "@/components/Money";
import { TopBar } from "@/components/Shell";
import { HIDE_KEY, hiddenStore, themeStore } from "./preferences";

function Screen() {
  return (
    <>
      <TopBar title="Teste" demo={false} />
      <p data-testid="valor">
        <Money cents={123456} />
      </p>
    </>
  );
}

describe("esconder valores", () => {
  beforeEach(() => {
    localStorage.clear();
    hiddenStore.reload();
    themeStore.reload();
  });

  it("o botão de olho troca os valores por •••• e lembra a escolha", async () => {
    const user = userEvent.setup();
    render(<Screen />);
    expect(screen.getByTestId("valor")).toHaveTextContent("R$ 1.234,56");

    await user.click(screen.getByRole("button", { name: "Esconder valores" }));
    expect(screen.getByTestId("valor")).toHaveTextContent("R$ ••••");
    expect(screen.getByTestId("valor")).not.toHaveTextContent("1.234");
    expect(localStorage.getItem(HIDE_KEY)).toBe("1");
    expect(screen.getByRole("button", { name: "Mostrar valores" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a escolha vale na próxima sessão", () => {
    localStorage.setItem(HIDE_KEY, "1");
    hiddenStore.reload(); // como se o app abrisse de novo
    render(<Screen />);
    expect(screen.getByTestId("valor")).toHaveTextContent("R$ ••••");
  });

  it("mostrar de novo volta aos valores", async () => {
    const user = userEvent.setup();
    localStorage.setItem(HIDE_KEY, "1");
    hiddenStore.reload();
    render(<Screen />);
    await user.click(screen.getByRole("button", { name: "Mostrar valores" }));
    expect(screen.getByTestId("valor")).toHaveTextContent("R$ 1.234,56");
    expect(localStorage.getItem(HIDE_KEY)).toBe("0");
  });

  it("o tema escolhido vai para a classe do documento", async () => {
    const user = userEvent.setup();
    render(<Screen />);
    await user.click(screen.getByRole("button", { name: "Usar tema claro" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Usar tema escuro" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
