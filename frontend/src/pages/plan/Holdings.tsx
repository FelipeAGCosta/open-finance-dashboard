/** "Onde está cada investimento" e o histórico de aportes. */
import { ChevronDown, Sparkles, Target } from "lucide-react";
import { HowCalculated } from "@/components/Help";
import { Money } from "@/components/Money";
import { ChartFrame, DonutChart, GroupedBars } from "@/components/charts";
import { EmptyState } from "@/components/states";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import type { Place, Plan } from "@/lib/api";
import { assetClassColor } from "@/lib/colors";
import { formatMoney, formatMonth } from "@/lib/format";
import { useHiddenValues } from "@/lib/preferences";
import { usePlaceMutation, useUndo } from "@/lib/queries";
import { showToast } from "@/lib/toast";

export function HoldingsCard({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const mutation = usePlaceMutation();
  const undo = useUndo();
  const total = plan.places.reduce((s, p) => s + p.cents, 0);
  const options = [
    { value: "reserva", label: "Reserva" },
    { value: "patrimonio", label: "Patrimônio" },
  ];
  const labelOf = (place: string) => options.find((o) => o.value === place)?.label ?? place;
  return (
    <Card className="h-full">
      <CardHeader title="Onde está cada investimento" subtitle="Cada real conta para a Reserva de emergência ou para o Patrimônio?" />
      <CardBody className="pt-2">
        <DonutChart
          layout="stack"
          size={180}
          thickness={14}
          data={plan.places.map((p) => ({ name: p.label, value: p.cents, color: p.color }))}
          centerLabel="investido"
          centerValue={<Money cents={total} />}
          formatValue={(v) => formatMoney(v, { hidden })}
        />
        <p className="mt-4 text-[12.5px] leading-relaxed text-text-2">
          Automático: a <strong>Reserva</strong> fica com a renda fixa até o valor definido; todo o resto é <strong>Patrimônio</strong> (inclusive a
          renda fixa que passa da Reserva). Nenhum real conta duas vezes.
        </p>
        <details className="group mt-3 rounded-xl border border-border">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 text-[13px] font-medium">
            Ajustar à mão ({plan.holdings.filter((h) => h.manual).length} escolhido{plan.holdings.filter((h) => h.manual).length === 1 ? "" : "s"} por você)
            <ChevronDown className="h-4 w-4 text-muted transition-transform group-open:rotate-180" />
          </summary>
          <ul className="divide-y divide-border border-t border-border px-3">
            {plan.holdings.map((h) => (
              <li key={h.investment_id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 text-[13px]">
                <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: assetClassColor(h.class) }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{h.label}</span>
                  <span className="block text-[12px] text-muted">
                    {h.class} · {h.parts.length > 1 ? h.parts.map((p) => `${formatMoney(p.cents, { hidden })} em ${p.label}`).join(" e ") : h.reason}
                  </span>
                </span>
                <Money cents={h.value} className="tnum text-text-2" />
                <Select
                  size="sm"
                  label={`Onde conta ${h.label}`}
                  value={h.manual ? h.place : "auto"}
                  className="w-full sm:w-[200px]"
                  options={[{ value: "auto", label: `Automático (${h.parts.map((p) => p.label).join(" + ")})` }, ...options]}
                  onValueChange={(value) =>
                    mutation.mutate(
                      { id: h.investment_id, place: value === "auto" ? null : (value as Place) },
                      {
                        onSuccess: (result) =>
                          showToast({ title: `${h.label}: ${value === "auto" ? "automático" : labelOf(value)}`, onUndo: () => undo(result.undo) }),
                        onError: (error) => showToast({ title: "Não foi possível salvar", detail: error.message, tone: "error" }),
                      },
                    )
                  }
                />
              </li>
            ))}
          </ul>
        </details>
        <HowCalculated label="Como funciona o automático">
          A renda fixa entra na Reserva na ordem escolhida no formulário da Reserva (do maior título para o menor) até completar o valor; um título
          pode ficar dividido. O que passa é Patrimônio. Renda variável fica no Patrimônio. A sua escolha manual sempre vence e vale para o
          investimento inteiro.
        </HowCalculated>
      </CardBody>
    </Card>
  );
}

export function HistoryCard({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const data = plan.history.map((h) => ({ month: h.month, contributed: Math.max(0, h.contributed), target: h.target ?? 0 }));
  if (!plan.history.length) {
    return (
      <Card className="h-full">
        <CardHeader title="Histórico de aportes" />
        <EmptyState icon={<Target className="h-5 w-5" />} title="Ainda sem meses com dados" />
      </Card>
    );
  }
  return (
    <Card className="h-full">
      <CardHeader title="Histórico de aportes" subtitle="Quanto você aportou em cada mês, frente à meta da época?" />
      <CardBody className="pt-1">
        <ChartFrame
          chart={
            <GroupedBars
              data={data}
              xKey="month"
              height={280}
              formatX={(m) => formatMonth(m, "short")}
              series={[
                { key: "contributed", label: "Saldo do mês (aportei − resgatei)", color: "var(--accent)", icon: <Sparkles className="h-3 w-3" /> },
                { key: "target", label: "Meta da época", color: "var(--series-other)" },
              ]}
            />
          }
          table={{
            headers: ["Mês", "Aportei", "Resgatei", "Saldo do mês", "Meta"],
            rows: plan.history.map((h) => [
              `${formatMonth(h.month, "title")}${h.in_progress ? " (em andamento)" : ""}`,
              formatMoney(h.contributions, { hidden }),
              formatMoney(h.redemptions, { hidden }),
              formatMoney(h.contributed, { signed: true, hidden }),
              h.target === null ? "—" : formatMoney(h.target, { hidden }),
            ]),
          }}
        />
        <p className="mt-2 text-[12px] text-muted">Meses em que o saldo foi negativo (resgatei mais do que aportei) aparecem como zero no gráfico; o valor exato está na tabela.</p>
      </CardBody>
    </Card>
  );
}
