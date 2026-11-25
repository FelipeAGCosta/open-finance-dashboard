/**
 * Aportes claros: sempre "Aportei · Resgatei · Saldo do mês", nunca só o líquido, com uma frase
 * simples quando o saldo é negativo.
 */
import { TrendingDown } from "lucide-react";
import type { Flows } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";

export function FlowsLine({ flows, className, compact }: { flows: Flows; className?: string; compact?: boolean }) {
  const [hidden] = useHiddenValues();
  const format = (v: number, signed = false) => formatMoney(v, { hidden, signed });
  const negative = flows.net < 0;
  return (
    <div className={cn("text-[13px]", className)}>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-text-2">
        <span>
          Aportei <strong className="font-semibold text-text tnum">{format(flows.contributions)}</strong>
        </span>
        <span aria-hidden className="text-muted">·</span>
        <span>
          Resgatei <strong className="font-semibold text-text tnum">{format(flows.redemptions)}</strong>
        </span>
        <span aria-hidden className="text-muted">·</span>
        <span>
          Saldo do mês{" "}
          <strong className={cn("font-semibold tnum", negative ? "text-negative" : flows.net > 0 ? "text-positive" : "text-text")}>
            {format(flows.net, true)}
          </strong>
        </span>
      </p>
      {negative && !compact ? (
        <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-warning">
          <TrendingDown className="h-3.5 w-3.5 shrink-0" />
          Você resgatou mais do que aportou: saíram {format(-flows.net)} dos investimentos neste mês.
        </p>
      ) : null}
    </div>
  );
}
