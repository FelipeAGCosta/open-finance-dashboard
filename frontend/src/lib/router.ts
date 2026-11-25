/** Roteamento mínimo por hash (#/gastos): o app é uma página só, servida pelo FastAPI local. */
import { useSyncExternalStore } from "react";

export const ROUTES = ["visao-geral", "gastos", "fixos", "investimentos", "plano", "status"] as const;
export type Route = (typeof ROUTES)[number];

function current(): Route {
  const value = window.location.hash.replace(/^#\/?/, "").split("?")[0] as Route;
  return ROUTES.includes(value) ? value : "visao-geral";
}

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, current, () => "visao-geral");
}

export function navigate(route: Route) {
  window.location.hash = `/${route}`;
}
