import { RotateCcw, Sparkles, UserCheck } from "lucide-react";
import type { RecurringRule } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Switch } from "./ui/switch";

/**
 * Interruptor "Fixo sim/não" de uma regra. A detecção vale sozinha ("automático"); mexer no
 * interruptor grava uma escolha manual, que vence o algoritmo. "Voltar ao automático" desfaz.
 */
export function FixedToggle({
  rule,
  onModeChange,
  label,
  disabled,
  align = "end",
  onLabel,
}: {
  rule: Pick<RecurringRule, "id" | "active" | "manual" | "counterparty">;
  onModeChange: (mode: "auto" | "sim" | "nao") => void;
  label?: string;
  disabled?: boolean;
  /** "between": origem à esquerda e interruptor à direita, numa linha própria. */
  align?: "end" | "between";
  /** Texto ao lado do interruptor (ex.: "É salário"). */
  onLabel?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", align === "between" ? "justify-between" : "justify-end")}>
      <div className={cn("text-right", align === "between" ? "text-left" : "hidden sm:block")}>
        {rule.manual ? (
          <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-accent">
            <UserCheck className="h-3 w-3" /> escolha manual
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[11.5px] text-muted">
            <Sparkles className="h-3 w-3" /> automático
          </span>
        )}
        {rule.manual ? (
          <button
            type="button"
            onClick={() => onModeChange("auto")}
            disabled={disabled}
            className="mt-0.5 flex items-center gap-1 text-[11.5px] text-muted underline-offset-2 hover:text-text hover:underline"
          >
            <RotateCcw className="h-3 w-3" /> voltar ao automático
          </button>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        {onLabel ? <span className="text-[12.5px] text-text-2">{onLabel}</span> : null}
        <Switch
          checked={rule.active}
          disabled={disabled}
          onCheckedChange={(checked) => onModeChange(checked ? "sim" : "nao")}
          label={label ?? `Fixo: ${rule.counterparty ?? "regra"}`}
        />
      </div>
    </div>
  );
}
