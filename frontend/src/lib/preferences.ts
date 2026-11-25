/**
 * Preferências do usuário lembradas entre sessões (localStorage): esconder valores e tema.
 * Um store mínimo com useSyncExternalStore: todos os componentes reagem à mesma fonte.
 */
import { useSyncExternalStore } from "react";

type Listener = () => void;

function createStore<T extends string>(key: string, fallback: T, allowed: readonly T[], onChange?: (value: T) => void) {
  const listeners = new Set<Listener>();
  const read = (): T => {
    try {
      const value = localStorage.getItem(key) as T | null;
      return value && allowed.includes(value) ? value : fallback;
    } catch {
      return fallback;
    }
  };
  let current = read();
  return {
    get: () => current,
    set(value: T) {
      current = value;
      try {
        localStorage.setItem(key, value);
      } catch {
        /* armazenamento indisponível: vale só nesta sessão */
      }
      onChange?.(value);
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: Listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    /** Relê o localStorage (usado nos testes). */
    reload() {
      current = read();
      listeners.forEach((listener) => listener());
    },
  };
}

export const HIDE_KEY = "findash:hide-values";
export const THEME_KEY = "findash:theme";

export const hiddenStore = createStore<"1" | "0">(HIDE_KEY, "0", ["1", "0"]);

export const themeStore = createStore<"dark" | "light">(THEME_KEY, "dark", ["dark", "light"], (theme) => {
  document.documentElement.classList.toggle("dark", theme === "dark");
});

export function useHiddenValues(): [boolean, () => void] {
  const value = useSyncExternalStore(hiddenStore.subscribe, hiddenStore.get, hiddenStore.get);
  return [value === "1", () => hiddenStore.set(value === "1" ? "0" : "1")];
}

export function useTheme(): ["dark" | "light", () => void] {
  const value = useSyncExternalStore(themeStore.subscribe, themeStore.get, themeStore.get);
  return [value, () => themeStore.set(value === "dark" ? "light" : "dark")];
}
