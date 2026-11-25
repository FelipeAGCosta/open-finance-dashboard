/** "O que fazer este mês": meta, quanto já foi investido, a checklist de compras e a capacidade em uma frase. */
import { ArrowRight, CalendarPlus, Check, Circle } from "lucide-react";
import { CalcLine, HowCalculated, Term } from "@/components/Help";
import { AnimatedMoney } from "@/components/Money";
import { ProgressBar } from "@/components/charts";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import type { MonthPlan, Plan } from "@/lib/api";
import { formatDate, formatMoney, formatMonth } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { capacityText, checklistText } from "@/lib/planText";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";

function Checklist({ plan, label }: { plan: MonthPlan; label: string }) {
  const [hidden] = useHiddenValues();
  if (!plan.checklist.length) return <p className="text-[13px] text-muted">Nada a comprar: a meta deste mês é zero.</p>;
  return (
    <ul aria-label={label} className="divide-y divide-border rounded-xl border border-border">
      {plan.checklist.map((line) => (
        <li key={line.where} className="flex items-center gap-3 px-3.5 py-3 text-[14px]">
          {line.done ? (
            <span role="img" aria-label="Feito" className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-positive text-surface">
              <Check className="h-3.5 w-3.5" strokeWidth={3} />
            </span>
          ) : (
            <Circle role="img" aria-label="A fazer" className="h-5 w-5 shrink-0 text-border-strong" />
          )}
          <span className={cn("flex min-w-0 flex-wrap items-baseline gap-x-2", line.done && "text-muted")}>
            <strong className={cn("tnum font-semibold", line.done && "font-medium line-through decoration-1")}>{formatMoney(line.amount, { hidden })}</strong>
            <ArrowRight aria-hidden className="h-3.5 w-3.5 shrink-0 self-center text-muted" />
            <span className="sr-only">para</span>
            <span className="min-w-0 break-words">{checklistText(line)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ThisMonthCard({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const c = plan.contribution;
  const cap = plan.capacity;
  const format = (v: number | null | undefined) => formatMoney(v, { hidden });
  return (
    <Card className="relative overflow-hidden">
      <span aria-hidden className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-accent opacity-[0.08] blur-3xl" />
      <CardHeader title="O que fazer este mês" subtitle={`Quanto investir em ${formatMonth(plan.month)} e onde comprar?`} action={<Badge tone="accent">{formatMonth(plan.month, "title")}</Badge>} />
      <CardBody className="relative">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <AnimatedMoney cents={c.total} className="text-[36px] font-semibold leading-none tracking-[-0.04em]" />
          <span className="text-[13px] text-muted">meta do mês</span>
        </div>
        {c.extra.active ? (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-text-2">
            <CalendarPlus className="h-4 w-4 text-accent" />
            {format(c.base)} da meta + {format(c.extra.cents)} de{" "}
            <Term help={GLOSSARY.pagamentoExtra}>
              <span>pagamento extra do salário</span>
            </Term>
          </p>
        ) : null}
        <div className="mt-4">
          <ProgressBar value={c.invested} max={c.total} label="Investido no mês frente à meta" />
        </div>
        <p className="mt-1.5 text-[13px] text-text-2">
          Já investido neste mês: <strong className="tnum text-text">{format(c.invested)}</strong>
          <span className="ml-1.5 text-[12px] text-muted">
            (aportei {format(c.flows.contributions)} · resgatei {format(c.flows.redemptions)})
          </span>
        </p>

        <div className="mt-4">
          <Checklist plan={c} label="Lista de compras do mês" />
        </div>
        <p className="mt-3 text-[13.5px] text-text-2">{capacityText(c, format)}</p>

        {c.next ? (
          <div className="mt-5 rounded-xl border border-dashed border-border-strong p-3.5">
            <p className="mb-2.5 text-[13px] font-medium">
              Prévia: plano de {formatMonth(c.next.month)} <span className="font-normal text-muted">· meta de {format(c.next.total)}</span>
            </p>
            <Checklist plan={c.next} label="Prévia da lista do próximo mês" />
            <p className="mt-2 text-[12px] text-muted">Calculada com a carteira de hoje; pode mudar até lá.</p>
          </div>
        ) : null}

        <p className="mt-4 text-[11.5px] text-muted">Cálculo a partir das metas que você definiu — não é recomendação de investimento.</p>
        <HowCalculated>
          <p>
            Meta do mês = meta base ({format(c.base)}){c.extra.enabled ? " + o pagamento extra do salário nos meses que têm um a mais" : ""}. Primeiro a Reserva de emergência, só se
            estiver abaixo do valor definido{c.reserve_priority.active ? ` (faltam ${format(c.reserve_priority.gap)}: ${format(c.reserve_priority.cents)} deste mês vão para ela)` : ""};
            o resto vai para o Patrimônio.
          </p>
          <p className="mt-1.5">
            No Patrimônio, <Term help={GLOSSARY.rebalancear}><span>sem vender nada</span></Term>: o dinheiro vai primeiro para a classe mais abaixo do alvo, até as classes
            ficarem na mesma distância do alvo. FIIs, ações mantidas e satélite nunca recebem. Cotas ≈ valor ÷ última cotação, arredondando para baixo; o que
            não fecha uma cota passa para a compra seguinte e, no fim, para a renda fixa. Um item vira ✓ quando o app encontra aportes do mês que somam pelo
            menos 95% do valor.
          </p>
          {c.patrimony.buckets.length ? (
            <div className="mt-2">
              <p className="font-medium text-text">Patrimônio deste mês ({format(c.patrimony.amount)}) por classe</p>
              {c.patrimony.buckets.filter((b) => b.amount > 0).map((b) => (
                <CalcLine key={b.bucket} label={b.label} value={format(b.amount)} />
              ))}
              {c.patrimony.leftover > 0 ? <CalcLine label="Não fecha uma cota (fica para o mês que vem)" value={format(c.patrimony.leftover)} /> : null}
            </div>
          ) : null}
          <div className="mt-3 border-t border-border pt-2">
            <p className="font-medium text-text">Quanto sobra neste mês (capacidade)</p>
            <CalcLine sign="+" label="Receitas já recebidas no mês" value={format(cap.income)} />
            <CalcLine sign="+" label={`Salário ainda esperado (${cap.salary_remaining_paydays.map((d) => formatDate(d, "day")).join(", ") || "nenhum"})`} value={format(cap.salary_remaining)} />
            <CalcLine sign="−" label="Despesas já feitas" value={format(cap.expenses)} />
            <CalcLine sign="−" label="Fixos ativos que ainda não caíram" value={format(cap.fixed_pending)} />
            <CalcLine sign="−" label={`Gastos do dia a dia previstos: ${format(cap.variable_daily)}/dia × ${cap.days_remaining} dias`} value={format(cap.variable_estimate)} />
            <CalcLine sign="=" label="Sobra projetada do mês" value={format(cap.projected_surplus)} strong />
            <CalcLine sign="−" label={`Saldo já investido no mês (aportei ${format(cap.contributions)} − resgatei ${format(cap.redemptions)})`} value={formatMoney(cap.contributions_net, { hidden, signed: true })} />
            <CalcLine sign="=" label="Ainda dá para investir" value={formatMoney(cap.capacity, { hidden, signed: true })} strong />
            <p className="mt-2 text-muted">
              Média diária dos gastos do dia a dia (sem fixos e sem extraordinários) de {cap.variable_months.map((m) => formatMonth(m.month, "short")).join(", ")}.
              Hoje a conta tem {format(cap.cash_available)} livres (saldo de {formatDate(cap.balance_date, "day")} − fatura em aberto − colchão de {format(cap.cushion)})
              {cap.depends_on_future_salary ? "; parte da sobra depende de salários que ainda vão cair" : ""}.
            </p>
          </div>
        </HowCalculated>
      </CardBody>
    </Card>
  );
}
