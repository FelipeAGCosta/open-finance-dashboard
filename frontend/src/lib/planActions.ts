/** Salvar metas do Plano com aviso de confirmação e "Desfazer". */
import type { PlanKey, PlanSettingValue } from "./api";
import { formatMonth } from "./format";
import { usePlanSettingMutation, useUndo } from "./queries";
import { showToast } from "./toast";

export function useSaveSetting() {
  const mutation = usePlanSettingMutation();
  const undo = useUndo();
  return {
    pending: mutation.isPending,
    save: <K extends PlanKey>(key: K, month: string, value: PlanSettingValue[K], what: string, onDone?: () => void) =>
      mutation.mutate(
        { key, month, value },
        {
          onSuccess: (result) => {
            onDone?.();
            const previous = result.undo;
            if (previous === null) showToast({ title: `${what}: nada mudou`, detail: "O valor já era esse; nada foi gravado." });
            else showToast({ title: `${what}: salvo`, detail: `Vale de ${formatMonth(month)} em diante.`, onUndo: () => undo(previous) });
          },
          onError: (error) => showToast({ title: "Não foi possível salvar", detail: error.message, tone: "error" }),
        },
      ),
  };
}
