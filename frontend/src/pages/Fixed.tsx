import { CalendarRange, Layers, MoonStar, Repeat, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { AnimatedMoney, Money } from "@/components/Money";
import { ChartFrame, MiniBars } from "@/components/charts";
import { FixedToggle } from "@/components/FixedToggle";
import { HowCalculated, Term } from "@/components/Help";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/states";
import { StatTile } from "@/components/Stat";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import type { Fixed, RecurringRule } from "@/lib/api";
import { categoryColorResolver } from "@/lib/colors";
import { formatDate, formatMoney, formatMonth } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { useHiddenValues } from "@/lib/preferences";
import { useFixed, useMeta, useRuleMutation } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function FixedPage() {
  const meta = useMeta();
  const query = useFixed();
  const mutation = useRuleMutation();
  const [hidden] = useHiddenValues();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton cards={3} />;
  const data = query.data;
  const colorOf = categoryColorResolver(meta.data);
  const change = (id: number, mode: "auto" | "sim" | "nao") => mutation.mutate({ id, mode });
  const active = data.fixed.filter((f) => f.state === "ativo");
  const inactive = data.fixed.filter((f) => f.state !== "ativo");

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <StatTile
          label={`Fixos de ${formatMonth(data.month.month)}`}
          icon={<Repeat className="h-4 w-4" />}
          tone="accent"
          value={<AnimatedMoney cents={data.month.paid + data.month.pending} />}
          footer={
            <>
              <Money cents={data.month.paid} /> já pagos · <Money cents={data.month.pending} /> a vencer
            </>
          }
        />
        <StatTile
          label="Total mensal dos fixos ativos"
          icon={<CalendarRange className="h-4 w-4" />}
          value={<AnimatedMoney cents={data.fixed_monthly} />}
          footer={`${active.length} fixo(s) ativo(s), pela média de cada um`}
        />
        <StatTile
          label="Parcelas a vencer"
          icon={<Layers className="h-4 w-4" />}
          tone="expense"
          value={<AnimatedMoney cents={data.commitments.total} />}
          footer={`${data.commitments.months.length} mês(es) com parcelas`}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,400px)]">
        <Card className="min-w-0">
          <CardHeader
            title={
              <Term help={GLOSSARY.fixo}>
                <span>Gastos fixos</span>
              </Term>
            }
            subtitle="O que se repete todo mês? A sua escolha manual sempre vence e não é desfeita por novas sincronizações."
          />
          <CardBody className="px-3 pt-3 sm:px-4">
            {data.fixed.length === 0 ? (
              <EmptyState icon={<Repeat className="h-5 w-5" />} title="Nenhum gasto fixo ainda">
                Cobranças da mesma empresa em 3 meses (ou 2 meses seguidos, para assinaturas) aparecem aqui; você também pode marcar na lista de Gastos.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-border">
                {[...active, ...inactive].map((rule) => (
                  <RuleRow key={rule.id} rule={rule} color={rule.category ? colorOf(rule.category) : undefined} onModeChange={(mode) => change(rule.id, mode)} />
                ))}
              </ul>
            )}
            <SinglesList data={data} />
            <HowCalculated>
              <p>
                <strong>Já pagos</strong>: soma das transações fixas do mês — é o mesmo número de “Fixo” na tela Gastos.
              </p>
              <p className="mt-1.5">
                <strong>A vencer</strong>: fixos ativos que ainda não cobraram neste mês, pela média de cada um.
              </p>
              <p className="mt-1.5">
                <strong>Inativo</strong>: fixo automático sem pagamento há mais de 45 dias (ou 1,5× o intervalo típico): sai do total. Se você marcou
                “sim” à mão, ele continua contando.
              </p>
            </HowCalculated>
          </CardBody>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Salário" subtitle="Qual entrada é o seu salário? Desmarque se não for." />
            <CardBody className="px-4 pt-3">
              {data.salary.length === 0 ? (
                <EmptyState icon={<Wallet className="h-5 w-5" />} title="Nenhum salário detectado" className="py-6" />
              ) : (
                <ul className="space-y-3">
                  {data.salary.map((rule) => (
                    <SalaryItem key={rule.id} rule={rule} onModeChange={(mode) => change(rule.id, mode)} />
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Parcelas futuras" subtitle="Quanto já está comprometido nos próximos meses?" />
            <CardBody className="pt-1">
              {data.commitments.months.length === 0 ? (
                <EmptyState icon={<CalendarRange className="h-5 w-5" />} title="Nenhuma parcela a vencer" className="py-6" />
              ) : (
                <ChartFrame
                  chart={
                    <MiniBars
                      data={data.commitments.months.map((m) => ({ key: m.month, value: m.cents }))}
                      color="var(--expense)"
                      formatX={(m) => formatMonth(m, "short")}
                      formatValue={(v) => formatMoney(v, { hidden })}
                      height={170}
                    />
                  }
                  table={{
                    headers: ["Mês", "Parcelas"],
                    rows: data.commitments.months.map((m) => [formatMonth(m.month, "title"), formatMoney(m.cents, { hidden })]),
                  }}
                />
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

function SinglesList({ data }: { data: Fixed }) {
  const [hidden] = useHiddenValues();
  if (!data.month.singles.length) return null;
  return (
    <div className="mt-4 rounded-xl border border-dashed border-border-strong px-3 py-3">
      <p className="text-[13px] font-medium">Marcados como fixo só em {formatMonth(data.month.month)}</p>
      <p className="text-[12px] text-muted">Entram no “já pago” do mês, mas não no total mensal. Para valer todo mês, use “todas desta contraparte” na lista de Gastos.</p>
      <ul className="mt-2 space-y-1 text-[13px]">
        {data.month.singles.map((s) => (
          <li key={s.key} className="flex items-center justify-between gap-3">
            <span className="truncate">{s.counterparty ?? "Sem nome"}</span>
            <span className="shrink-0 tnum">{formatMoney(s.paid, { hidden })}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StateBadge({ rule }: { rule: RecurringRule }) {
  if (rule.state === "inativo")
    return (
      <Badge tone="neutral">
        <MoonStar className="h-3 w-3" /> inativo
      </Badge>
    );
  if (rule.state === "desmarcado") return <Badge tone="neutral">não é fixo</Badge>;
  return null;
}

function RuleRow({ rule, color, onModeChange }: { rule: RecurringRule; color?: string; onModeChange: (mode: "auto" | "sim" | "nao") => void }) {
  const [hidden] = useHiddenValues();
  const thisMonth = rule.this_month;
  return (
    <motion.li layout="position" className={cn("flex items-center gap-4 rounded-xl px-2 py-3.5 transition-opacity duration-300", rule.state !== "ativo" && "opacity-60")}>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border bg-surface-2">
        <span className="h-3 w-3 rounded-[4px]" style={{ background: color ?? "var(--series-other)" }} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 truncate text-[14px] font-medium">
          <span className="truncate">{rule.counterparty}</span>
          <StateBadge rule={rule} />
        </p>
        <p className="truncate text-[12.5px] text-muted">
          {rule.category ?? "Sem categoria"}
          {rule.last_payment ? <> · último em {formatDate(rule.last_payment.date, "day")}</> : null}
          {rule.state === "inativo" ? <> · sem pagamento há mais de {rule.inactive_after_days} dias, fora do total</> : null}
          {rule.state === "ativo" && rule.stale ? <> · sem pagamento recente, mas você marcou como fixo</> : null}
        </p>
      </div>
      <div className="hidden text-right sm:block">
        <p className="whitespace-nowrap text-[14px] font-semibold tnum">{formatMoney(rule.avg_monthly, { hidden })}</p>
        <p className="text-[11.5px] text-muted">
          {thisMonth && thisMonth.paid > 0 ? "pago este mês" : thisMonth && thisMonth.pending > 0 ? "a vencer este mês" : "média/mês"}
        </p>
      </div>
      {/* ligado = conta no total; um inativo aparece desligado e, ao ligar, volta a contar (escolha manual) */}
      <FixedToggle rule={{ ...rule, active: rule.state === "ativo" }} onModeChange={onModeChange} label={`Fixo: ${rule.counterparty ?? ""}`} />
    </motion.li>
  );
}

/** Cartão do salário em blocos empilhados: nada espremido numa coluna estreita. */
function SalaryItem({ rule, onModeChange }: { rule: RecurringRule; onModeChange: (mode: "auto" | "sim" | "nao") => void }) {
  const [hidden] = useHiddenValues();
  return (
    <li className={cn("rounded-xl border border-border bg-surface-2/50 p-3.5 transition-opacity", !rule.active && "opacity-60")}>
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-border bg-surface">
          <Wallet className="h-4 w-4 text-income" />
        </span>
        <p className="min-w-0 flex-1 text-[14px] font-medium leading-snug [overflow-wrap:anywhere]">{rule.counterparty}</p>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
        <div>
          <dt className="text-[12px] text-muted">{rule.schedule ? `Pagamento (${rule.schedule})` : "Por mês"}</dt>
          <dd className="font-semibold tnum">{formatMoney(rule.paycheck ?? rule.avg_monthly, { hidden })}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-muted">Média mensal no ano</dt>
          <dd className="font-semibold tnum">{formatMoney(rule.annual_average ?? rule.avg_monthly, { hidden })}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-muted">Desde</dt>
          <dd className="tnum">{formatDate(rule.first_payment)}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-muted">Último</dt>
          <dd className="tnum">{rule.last_payment ? formatDate(rule.last_payment.date) : "—"}</dd>
        </div>
      </dl>
      <div className="mt-3 border-t border-border pt-3">
        <FixedToggle rule={rule} onModeChange={onModeChange} label={`Salário: ${rule.counterparty ?? ""}`} align="between" onLabel="É salário" />
      </div>
    </li>
  );
}
