import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type ClassifyBody,
  type Expenses,
  type Fixed,
  type InTransitAction,
  type Place,
  type PlanKey,
  type PlanSettingValue,
  type RecurringRule,
  type Transaction,
  type UndoPackage,
} from "./api";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });

// placeholderData: ao trocar de mês a tela anterior fica visível (esmaecida) até os novos dados
// chegarem, em vez de piscar o esqueleto.
export const useOverview = (month?: string) =>
  useQuery({ queryKey: ["overview", month], queryFn: () => api.overview(month), placeholderData: keepPreviousData });

export const useExpenses = (month?: string) =>
  useQuery({ queryKey: ["expenses", month], queryFn: () => api.expenses(month), placeholderData: keepPreviousData });

export const useFixed = () => useQuery({ queryKey: ["fixed"], queryFn: api.fixed });
export const useInvestments = () => useQuery({ queryKey: ["investments"], queryFn: api.investments });
export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
export const usePlan = () => useQuery({ queryKey: ["plan"], queryFn: api.plan });

/** Depois de mudar uma classificação, tudo que depende dela é recarregado. */
function invalidateDerived(client: ReturnType<typeof useQueryClient>) {
  return Promise.all(
    ["overview", "expenses", "fixed", "meta", "plan", "investments"].map((key) => client.invalidateQueries({ queryKey: [key] })),
  );
}

/** Ação da lista com escopo (só esta / toda a contraparte). Recalcula tudo no servidor. */
export function useClassifyMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ClassifyBody }) => api.classify(id, body),
    onSettled: () => invalidateDerived(client),
  });
}

/** Desfaz uma ação (o pacote vem da própria ação). */
export function useUndo() {
  const client = useQueryClient();
  return (undo: UndoPackage) => api.undo(undo).finally(() => invalidateDerived(client));
}

export function usePlanSettingMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, month, value }: { key: PlanKey; month: string; value: PlanSettingValue[PlanKey] }) =>
      api.savePlanSetting(key, month, value as never),
    onSettled: () => invalidateDerived(client),
  });
}

/** Compra em trânsito: "já chegou (é o ativo X)", "ignorar" ou de volta ao automático (null). */
export function useInTransitMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, investmentId }: { id: string; action: InTransitAction | null; investmentId?: string }) =>
      api.setInTransit(id, action, investmentId),
    onSettled: () => invalidateDerived(client),
  });
}

export function usePlaceMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, place }: { id: string; place: Place | null }) => api.setPlace(id, place),
    onSettled: () => invalidateDerived(client),
  });
}

/** Trocar categoria / marcar fixo numa transação, com atualização otimista da linha. */
export function useTransactionMutation(month: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: { category?: string | null; fixed?: boolean | null } }) =>
      api.patchTransaction(id, body),
    onMutate: async ({ id, body }) => {
      const key = ["expenses", month];
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Expenses>(key);
      if (previous) {
        client.setQueryData<Expenses>(key, {
          ...previous,
          transactions: previous.transactions.map((t): Transaction =>
            t.id !== id
              ? t
              : {
                  ...t,
                  ...(body.category !== undefined && body.category !== null
                    ? { category: body.category, rule_level: "override" }
                    : {}),
                  ...(body.fixed !== undefined && body.fixed !== null ? { is_fixed: body.fixed, fixed_source: "transacao" } : {}),
                },
          ),
        });
      }
      return { previous, key };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(context.key, context.previous);
    },
    onSettled: () => invalidateDerived(client),
  });
}

/** Interruptor Fixo sim/não de uma regra (gasto fixo ou salário), também otimista. */
export function useRuleMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, mode }: { id: number; mode: "auto" | "sim" | "nao" }) => api.patchRule(id, mode),
    onMutate: async ({ id, mode }) => {
      await client.cancelQueries({ queryKey: ["fixed"] });
      const previous = client.getQueryData<Fixed>(["fixed"]);
      if (previous) {
        const update = (r: RecurringRule): RecurringRule =>
          r.id !== id
            ? r
            : {
                ...r,
                status: mode === "auto" ? "automatico" : mode === "sim" ? "manual_sim" : "manual_nao",
                manual: mode !== "auto",
                active: mode !== "nao",
                state: mode === "nao" ? "desmarcado" : mode === "sim" ? "ativo" : r.state === "desmarcado" ? "ativo" : r.state,
              };
        client.setQueryData<Fixed>(["fixed"], { ...previous, fixed: previous.fixed.map(update), salary: previous.salary.map(update) });
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(["fixed"], context.previous);
    },
    onSettled: () => invalidateDerived(client),
  });
}

export function useSyncMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.sync,
    onSettled: () => client.invalidateQueries(),
  });
}
