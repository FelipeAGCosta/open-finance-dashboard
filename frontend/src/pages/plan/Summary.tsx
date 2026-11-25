/** "Resumo": dois cartões pequenos (Reserva e Patrimônio) com valor e situação em palavras; clicar leva à seção. */
import { ArrowDown, ShieldCheck, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { Money } from "@/components/Money";
import { ProgressBar } from "@/components/charts";
import { InTransitNote, WealthTerm } from "@/components/Wealth";
import { Badge } from "@/components/ui/primitives";
import type { Plan } from "@/lib/api";
import { PATRIMONY_COLOR, RESERVE_COLOR } from "@/lib/colors";
import { formatMoney } from "@/lib/format";
import { patrimonyStatus, reserveStatus } from "@/lib/planText";
import { useHiddenValues } from "@/lib/preferences";

function SummaryCard({ href, icon, title, cents, status, tone, detail, children }: {
  href: string; icon: ReactNode; title: string; cents: number; status: string; tone: "positive" | "warning" | "neutral"; detail: string; children?: ReactNode;
}) {
  return (
    <a
      href={href}
      onClick={(event) => {
        // o roteador usa o hash: rola até a seção sem trocar de tela
        event.preventDefault();
        document.getElementById(href.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
      }}
      className="group block rounded-[var(--radius-card)] border border-border bg-surface p-5 transition-colors hover:border-border-strong"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[13px] font-medium text-muted">
          {icon}
          {title}
        </span>
        <Badge tone={tone}>{status}</Badge>
      </div>
      <Money cents={cents} className="mt-2.5 block text-[26px] font-semibold tracking-[-0.03em]" />
      {children}
      <p className="mt-2 flex items-center justify-between gap-2 text-[12.5px] text-text-2">
        <span>{detail}</span>
        <ArrowDown className="h-3.5 w-3.5 shrink-0 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
      </p>
    </a>
  );
}

export function SummaryRow({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const format = (v: number | null) => formatMoney(v, { hidden });
  const reserve = reserveStatus(plan.reserve, format);
  const patrimony = patrimonyStatus(plan.patrimony);
  return (
    <div>
      {plan.wealth ? (
        <div className="mb-3 px-1">
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px] text-text-2">
            <WealthTerm className="font-medium text-text" />
            <Money cents={plan.wealth.total} className="text-[17px] font-semibold text-text tnum" />
            <span className="text-[12.5px] text-muted">
              = Reserva {format(plan.reserve.current)} + Patrimônio {format(plan.patrimony.current)}
              {plan.wealth.in_transit.cents > 0 ? ` + em trânsito ${format(plan.wealth.in_transit.cents)}` : ""}
            </span>
          </p>
          <InTransitNote wealth={plan.wealth} className="mt-1" />
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
      <SummaryCard
        href="#plano-ajustar"
        icon={<ShieldCheck className="h-4 w-4" style={{ color: RESERVE_COLOR }} />}
        title="Reserva de emergência"
        cents={plan.reserve.current}
        status={reserve.status}
        tone={reserve.tone}
        detail={reserve.detail}
      >
        {plan.reserve.target !== null ? (
          <div className="mt-2.5">
            <ProgressBar value={plan.reserve.current} max={plan.reserve.target} color={RESERVE_COLOR} label="Reserva de emergência" />
          </div>
        ) : null}
      </SummaryCard>
      <SummaryCard
        href="#plano-carteira"
        icon={<Wallet className="h-4 w-4" style={{ color: PATRIMONY_COLOR }} />}
        title="Patrimônio"
        cents={plan.patrimony.current}
        status={patrimony.status}
        tone={patrimony.tone}
        detail={patrimony.detail}
      />
      </div>
    </div>
  );
}
