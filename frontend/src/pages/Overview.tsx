import { AlertOctagon, AlertTriangle, ArrowRight, CalendarClock, CheckCircle2, Info, LineChart, PiggyBank, ShieldCheck, Sparkles, Target, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { AnimatedMoney, Delta, Money } from "@/components/Money";
import { AreaTrend, ChartFrame, DonutChart, GroupedBars, ProgressBar } from "@/components/charts";
import { FlowsLine } from "@/components/Flows";
import { InTransitNote, WEALTH_LABEL, WealthTerm } from "@/components/Wealth";
import { CalcLine, HowCalculated, Term } from "@/components/Help";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/states";
import { FlowIcon, StatTile } from "@/components/Stat";
import { Badge, Button, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import type { Alert, InvestmentsMonth, MonthData, Overview as OverviewData, PlanSummary, SalaryMonth } from "@/lib/api";
import { EXPENSE, INCOME, categoryColorResolver, foldCategories } from "@/lib/colors";
import { formatDate, formatDateTime, formatMoney, formatMonth, formatPercent } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { useHiddenValues } from "@/lib/preferences";
import { useMeta, useOverview } from "@/lib/queries";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.05 } } };
const rise = { hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const } } };

export function OverviewPage({ month }: { month: string }) {
  const meta = useMeta();
  const query = useOverview(month);
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton />;
  const data = query.data;
  const colorOf = categoryColorResolver(meta.data);
  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className={cn("space-y-5 transition-opacity duration-300", query.isPlaceholderData && "opacity-60")}
    >
      <AlertStrip alerts={data.alerts.filter((a) => a.level !== "info")} />
      {data.data_as_of ? (
        <p className="-mt-2 text-[12.5px] text-muted">Dados da Pluggy até {formatDateTime(data.data_as_of)}</p>
      ) : null}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <motion.div variants={rise} className="xl:col-span-7">
          <NetWorthCard data={data} />
        </motion.div>
        <motion.div variants={rise} className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:col-span-5">
          <StatTile
            label="Receitas"
            tone="income"
            icon={<FlowIcon direction="in" />}
            value={<AnimatedMoney cents={data.month.income} />}
            footer={
              <>
                + <Money cents={data.month.investment_income} /> de renda de investimentos
              </>
            }
          />
          <StatTile
            label="Despesas"
            tone="expense"
            icon={<FlowIcon direction="out" />}
            value={<AnimatedMoney cents={data.month.expenses} />}
            footer={<ExpensesSplit month={data.month} />}
          />
          <StatTile
            label="Sobra do mês"
            tone="accent"
            icon={<Wallet className="h-4 w-4" />}
            value={<AnimatedMoney cents={data.month.result} signed />}
            footer={
              data.month.extraordinary.cents > 0 ? (
                <>
                  sem extraordinários: <Money cents={data.month.result_everyday} signed className="tnum" />
                </>
              ) : (
                "o que entrou menos o que saiu"
              )
            }
          />
          <StatTile
            label="Taxa de poupança"
            icon={<PiggyBank className="h-4 w-4" />}
            value={formatPercent(data.month.savings_rate)}
            footer={
              data.month.extraordinary.cents > 0 ? (
                <>sem extraordinários: {formatPercent(data.month.savings_rate_everyday)}</>
              ) : (
                <SavingsHint rate={data.month.savings_rate} />
              )
            }
          />
        </motion.div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 2xl:grid-cols-4">
        <motion.div variants={rise}>
          <SalaryCard salaries={data.month.salaries} month={data.month.month} />
        </motion.div>
        <motion.div variants={rise}>
          <ContributionSummary plan={data.plan} />
        </motion.div>
        <motion.div variants={rise}>
          <InvestmentsMonthCard data={data.investments_month} month={data.month} />
        </motion.div>
        <motion.div variants={rise}>
          <AlertsCard alerts={data.alerts} />
        </motion.div>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <motion.div variants={rise} className="xl:col-span-8">
          <HistoryCard history={data.history} />
        </motion.div>
        <motion.div variants={rise} className="xl:col-span-4">
          <Card className="h-full">
            <CardHeader title="Despesas por categoria" subtitle={`Para onde foi o dinheiro em ${formatMonth(data.month.month)}?`} />
            <CardBody>
              {data.month.categories.length ? (
                <CategoryDonut categories={data.month.categories} total={data.month.expenses} colorOf={colorOf} />
              ) : (
                <EmptyState icon={<Sparkles className="h-5 w-5" />} title="Nenhum gasto neste mês" />
              )}
            </CardBody>
          </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}

/** Total sempre visível; dia a dia e extraordinários separados. */
function ExpensesSplit({ month }: { month: MonthData }) {
  if (!month.extraordinary.cents) return <>{month.expenses_count} gastos no mês</>;
  return (
    <>
      dia a dia <Money cents={month.everyday} className="tnum" /> ·{" "}
      <Term help={GLOSSARY.extraordinario}>
        <span>extraordinários</span>
      </Term>{" "}
      <Money cents={month.extraordinary.cents} className="tnum" />
    </>
  );
}

function SavingsHint({ rate }: { rate: number | null }) {
  if (rate === null) return <>sem receitas no mês</>;
  if (rate >= 0.2) return <span className="text-positive">acima de 20%: ótimo ritmo</span>;
  if (rate >= 0) return <>meta de referência: 20%</>;
  return <span className="text-negative">gastos acima das receitas</span>;
}

function NetWorthCard({ data }: { data: OverviewData }) {
  const worth = data.wealth;
  if (!worth) {
    return (
      <Card className="h-full">
        <CardHeader title={WEALTH_LABEL} />
        <EmptyState icon={<Wallet className="h-5 w-5" />} title="Ainda sem fotos diárias">
          O patrimônio aparece depois da primeira sincronização com a carteira de investimentos.
        </EmptyState>
      </Card>
    );
  }
  const enough = worth.series.length >= 3;
  return (
    <Card className="relative h-full overflow-hidden">
      <span aria-hidden className="pointer-events-none absolute -left-16 -top-24 h-64 w-64 rounded-full bg-accent opacity-[0.07] blur-3xl" />
      <div className="relative px-6 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13px] font-medium text-muted">
            <WealthTerm /> hoje
          </p>
          <span className="text-[12px] text-muted">foto de {formatDate(worth.date)}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <AnimatedMoney cents={worth.total} className="text-[40px] font-semibold leading-none tracking-[-0.04em] sm:text-[46px]" duration={1.1} />
          {worth.series.length > 1 ? (
            <span className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
              <Delta cents={worth.change.cents} pct={worth.change.pct} />
              <Term help={GLOSSARY.variacaoPatrimonio}>
                <span>desde {formatDate(worth.change.since).slice(0, 5)} (inclui aportes e resgates)</span>
              </Term>
            </span>
          ) : null}
        </div>
        <p className="mt-1.5 text-[12.5px] text-muted">Só o que está investido, como no app do banco.</p>
        <InTransitNote wealth={worth} className="mt-3" />
        {data.accounts ? (
          <p className="mt-2 text-[12px] text-muted">
            Fora do patrimônio: conta <Money cents={data.accounts.bank} className="text-text-2 tnum" /> · fatura em aberto{" "}
            <Money cents={data.accounts.card_bill} className="text-text-2 tnum" />
          </p>
        ) : null}
      </div>
      <div className="mt-2 px-2 pb-3">
        {enough ? (
          <AreaTrend data={worth.series} dataKey="total" label={WEALTH_LABEL} formatX={(v) => formatDate(v, "day")} height={210} />
        ) : (
          <div className="mx-4 mb-3 mt-4 flex items-center gap-3 rounded-xl border border-dashed border-border-strong px-4 py-5 text-[13px] text-muted">
            <CalendarClock className="h-5 w-5 shrink-0 text-accent" />
            A linha de evolução ganha forma a cada sincronização diária ({worth.series.length} de 3 fotos para começar).
          </div>
        )}
      </div>
    </Card>
  );
}

function SalaryCard({ salaries, month }: { salaries: SalaryMonth[]; month: string }) {
  const [hidden] = useHiddenValues();
  const salary = salaries[0];
  return (
    <Card className="h-full">
      <CardHeader
        title="Salário"
        subtitle="O salário do mês chegou como esperado?"
        action={
          salary ? (
            salary.divergent ? (
              <Badge tone="warning">
                <AlertTriangle className="h-3 w-3" /> diferente do esperado
              </Badge>
            ) : (
              <Badge tone="positive">
                <CheckCircle2 className="h-3 w-3" /> {salary.in_progress ? "em dia até agora" : "recebido"}
              </Badge>
            )
          ) : null
        }
      />
      <CardBody>
        {!salary ? (
          <EmptyState icon={<CalendarClock className="h-5 w-5" />} title="Nenhum salário reconhecido" className="py-6">
            Créditos que seguem a agenda de config/settings.yaml (semanal, quinzenal ou mensal) são reconhecidos
            automaticamente.
          </EmptyState>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <AnimatedMoney cents={salary.received} className="text-[28px] font-semibold tracking-[-0.03em]" />
              <span className="text-[13px] text-muted">
                de <Money cents={salary.expected} className="font-medium text-text-2" />
              </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="presentation">
              <motion.div
                className="h-full rounded-full"
                style={{ background: salary.divergent ? "var(--warning)" : "var(--income)" }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(100, salary.expected ? (salary.received / salary.expected) * 100 : 0)}%` }}
                transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
              />
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5 text-[13px]">
              <dt className="text-muted">Cada pagamento ({salary.schedule})</dt>
              <dd className="text-right font-medium tnum">{formatMoney(salary.paycheck, { hidden })}</dd>
              <dt className="text-muted">Pagamentos no mês</dt>
              <dd className="text-right font-medium tnum">
                {salary.in_progress ? `${salary.due_paydays} de ${salary.paydays}` : salary.paydays}
              </dd>
              <dt className="text-muted">Média ao longo do ano</dt>
              <dd className="text-right font-medium tnum">{formatMoney(salary.annual_average, { hidden })}/mês</dd>
            </dl>
            {salary.divergent ? (
              <p className="mt-4 rounded-xl bg-[color-mix(in_oklab,var(--warning)_12%,transparent)] px-3 py-2.5 text-[12.5px] leading-relaxed text-text-2">
                <AlertTriangle className="mr-1 inline h-3.5 w-3.5 text-warning" />
                Diferença de <strong className="tnum">{formatMoney(salary.difference, { signed: true, hidden })}</strong>
                {salary.missing_paydays.length
                  ? ` — sem pagamento em ${salary.missing_paydays.map((d) => formatDate(d, "day")).join(", ")}.`
                  : "."}
              </p>
            ) : salary.in_progress ? (
              <p className="mt-4 text-[12.5px] text-muted">
                Mês em andamento: esperado até agora <Money cents={salary.expected_due} className="text-text-2" />.
              </p>
            ) : (
              <p className="mt-4 text-[12.5px] text-muted">
                {formatMonth(month, "title")} fechado com o valor esperado.
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function ContributionSummary({ plan }: { plan: PlanSummary | null }) {
  const [hidden] = useHiddenValues();
  if (!plan) {
    return (
      <Card className="h-full">
        <CardHeader title="Seu aporte deste mês" />
        <EmptyState icon={<PiggyBank className="h-5 w-5" />} title="Sem dados para o plano ainda" className="py-6" />
      </Card>
    );
  }
  const format = (v: number) => formatMoney(v, { hidden });
  return (
    <Card className="h-full">
      <CardHeader
        title="Seu aporte deste mês"
        subtitle="Quanto investir e para onde vai?"
        action={
          <Button size="sm" variant="ghost" onClick={() => navigate("plano")}>
            Plano <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        }
      />
      <CardBody>
        <div className="flex items-baseline gap-2">
          <AnimatedMoney cents={plan.total} className="text-[28px] font-semibold tracking-[-0.03em] text-accent" />
          <span className="text-[13px] text-muted">meta do mês{plan.extra > 0 ? ` (inclui ${format(plan.extra)} de extra)` : ""}</span>
        </div>
        <ul className="mt-3 space-y-1 text-[12.5px]">
          {plan.places.map((p) => (
            <li key={p.label} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2 text-text-2">
                <span className="h-2 w-2 shrink-0 rounded-[3px]" style={{ background: p.color }} />
                <span className="truncate">{p.label}</span>
              </span>
              <span className="tnum">{format(p.planned)}</span>
            </li>
          ))}
        </ul>
        <FlowsLine flows={plan.flows} compact className="mt-3 text-[12.5px]" />
        <div className="mt-1.5">
          <ProgressBar value={plan.flows.net} max={plan.total} label="Saldo aportado no mês" />
        </div>
        <p className="mt-1.5 text-[12.5px] text-muted">{plan.remaining > 0 ? `Falta aportar ${format(plan.remaining)}.` : "Meta do mês cumprida."}</p>
        {plan.reserve_priority ? (
          <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-text-2">
            <ShieldCheck className="h-3.5 w-3.5" style={{ color: "var(--goal-reserva)" }} /> A Reserva vem primeiro até completar o valor.
          </p>
        ) : null}
        {!plan.fits && plan.remaining > 0 ? (
          <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-warning">
            <CalendarClock className="h-3.5 w-3.5" /> A capacidade do mês ({format(plan.capacity)}) não cobre o que falta.
          </p>
        ) : null}
        <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-muted">
          <Target className="h-3 w-3" />
          <Term help={GLOSSARY.capacidade}>
            <span>Cálculo a partir das suas metas — não é recomendação.</span>
          </Term>
        </p>
      </CardBody>
    </Card>
  );
}

/** B2 + C3: quanto os investimentos mudaram no mês e de onde veio; quanto das despesas saiu de resgates. */
function InvestmentsMonthCard({ data, month }: { data: InvestmentsMonth | null; month: MonthData }) {
  const [hidden] = useHiddenValues();
  const format = (v: number | null | undefined, signed = false) => formatMoney(v, { hidden, signed });
  return (
    <Card className="h-full">
      <CardHeader
        title="Seus investimentos no mês"
        subtitle="Quanto mudaram e de onde veio a mudança?"
        action={
          <Button size="sm" variant="ghost" onClick={() => navigate("investimentos")}>
            <LineChart className="h-3.5 w-3.5" />
          </Button>
        }
      />
      <CardBody>
        {data ? (
          <>
            <AnimatedMoney cents={data.change} signed className={cn("text-[28px] font-semibold tracking-[-0.03em]", data.change < 0 ? "text-negative" : "text-text")} />
            <dl className="mt-3 space-y-1.5 text-[13px]">
              <div className="flex justify-between gap-3">
                <dt className="text-text-2">Dinheiro novo (aportes − resgates)</dt>
                <dd className="font-medium tnum">{format(data.net_flows, true)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-text-2">Rendimento</dt>
                <dd className={cn("font-medium tnum", data.growth < 0 ? "text-negative" : "text-positive")}>{format(data.growth, true)}</dd>
              </div>
            </dl>
            {data.partial_since ? <p className="mt-1.5 text-[12px] text-muted">Desde {formatDate(data.partial_since, "day")} (início das fotos diárias).</p> : null}
          </>
        ) : (
          <p className="text-[13px] text-muted">Aparece quando houver fotos da carteira neste mês.</p>
        )}
        <FlowsLine flows={month.flows} className="mt-3 border-t border-border pt-3 text-[12.5px]" />
        {month.paid_with_redemptions > 0 ? (
          <p className="mt-2 text-[12.5px] text-text-2">
            <Term help={GLOSSARY.pagosComResgates}>
              <span>Pagos com resgates</span>
            </Term>
            : <strong className="tnum text-text">{format(month.paid_with_redemptions)}</strong> das despesas deste mês.
          </p>
        ) : null}
        {data ? (
          <HowCalculated>
            <CalcLine label={`Carteira em ${formatDate(data.start, "day")}`} value={format(data.start_value)} />
            <CalcLine sign="+" label={`Aportes − resgates (${format(data.contributions)} − ${format(data.redemptions)})`} value={format(data.net_flows, true)} />
            <CalcLine sign="+" label="Rendimento (o resto da variação)" value={format(data.growth, true)} />
            <CalcLine sign="=" label={`Carteira em ${formatDate(data.end, "day")}`} value={format(data.end_value)} strong />
            {data.income ? <p className="mt-2 text-muted">Proventos pagos na conta ({format(data.income)}) não entram: saíram da carteira.</p> : null}
            <p className="mt-2 text-muted">
              Pagos com resgates = o menor entre (despesas − receitas do mês) e (resgates − aportes): {format(month.paid_with_redemptions)}.
            </p>
          </HowCalculated>
        ) : null}
      </CardBody>
    </Card>
  );
}

const ALERT_ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;
const ALERT_TONE = { critical: "text-negative", warning: "text-warning", info: "text-accent" } as const;
const ROUTE_OF = { status: "status", overview: "visao-geral", expenses: "gastos", plan: "plano" } as const;

function AlertStrip({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return null;
  return (
    <div className="space-y-2">
      {alerts.map((alert) => {
        const Icon = ALERT_ICON[alert.level];
        return (
          <motion.button
            key={alert.title}
            variants={rise}
            onClick={() => navigate(ROUTE_OF[alert.target])}
            className={cn(
              "flex w-full items-center gap-3 rounded-2xl border px-4 py-3 text-left text-[13.5px] transition-colors",
              alert.level === "critical"
                ? "border-[color-mix(in_oklab,var(--negative)_40%,var(--border))] bg-[color-mix(in_oklab,var(--negative)_10%,var(--surface))]"
                : "border-[color-mix(in_oklab,var(--warning)_35%,var(--border))] bg-[color-mix(in_oklab,var(--warning)_8%,var(--surface))]",
            )}
          >
            <Icon className={cn("h-4.5 w-4.5 shrink-0", ALERT_TONE[alert.level])} />
            <span className="font-semibold">{alert.title}</span>
            <span className="truncate text-muted">{alert.detail}</span>
          </motion.button>
        );
      })}
    </div>
  );
}

function AlertsCard({ alerts }: { alerts: Alert[] }) {
  const [hidden] = useHiddenValues();
  return (
    <Card className="h-full">
      <CardHeader title="Alertas" subtitle="O que pede atenção agora?" />
      <CardBody className="pt-3">
        {alerts.length === 0 ? (
          <EmptyState icon={<CheckCircle2 className="h-5 w-5" />} title="Tudo em ordem" className="py-6">
            Sincronização em dia, consentimento válido e nada para classificar.
          </EmptyState>
        ) : (
          <ul className="space-y-1.5">
            {alerts.map((alert) => {
              const Icon = ALERT_ICON[alert.level];
              return (
                <li key={alert.title}>
                  <button
                    onClick={() => navigate(ROUTE_OF[alert.target])}
                    className="flex w-full items-start gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors hover:bg-surface-2"
                  >
                    <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", ALERT_TONE[alert.level])} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-medium">{alert.title}</span>
                      <span className="block text-[12.5px] leading-snug text-muted">
                        {alert.target === "overview" && alert.cents !== undefined
                          ? `Diferença de ${formatMoney(alert.cents, { signed: true, hidden })} no mês.`
                          : alert.detail}
                      </span>
                    </span>
                    {alert.cents !== undefined && alert.target === "expenses" ? (
                      <Money cents={alert.cents} className="text-[13px] font-medium tnum text-text-2" />
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function HistoryCard({ history }: { history: OverviewData["history"] }) {
  const [hidden] = useHiddenValues();
  return (
    <Card className="h-full">
      <CardHeader title="Receitas × despesas" subtitle="Sobrou dinheiro nos últimos 12 meses?" />
      <CardBody className="pt-1">
        <ChartFrame
          chart={
            <GroupedBars
              data={history}
              xKey="month"
              height={420}
              formatX={(m) => formatMonth(m, "short")}
              series={[
                { key: "income", label: "Receitas", color: INCOME, icon: <FlowIcon direction="in" /> },
                { key: "expenses", label: "Despesas", color: EXPENSE, icon: <FlowIcon direction="out" /> },
              ]}
            />
          }
          table={{
            headers: ["Mês", "Receitas", "Despesas", "Sobra"],
            rows: history.map((h) => [
              formatMonth(h.month, "title"),
              formatMoney(h.income, { hidden }),
              formatMoney(h.expenses, { hidden }),
              formatMoney(h.income + h.investment_income - h.expenses, { signed: true, hidden }),
            ]),
          }}
        />
      </CardBody>
    </Card>
  );
}

function CategoryDonut({
  categories,
  total,
  colorOf,
}: {
  categories: { name: string; cents: number }[];
  total: number;
  colorOf: (name: string) => string;
}) {
  const [hidden] = useHiddenValues();
  const folded = foldCategories(categories, colorOf);
  return (
    <DonutChart
      data={folded.map((c) => ({
        name: c.name,
        value: c.cents,
        color: c.color,
        detail: c.members.length > 1 ? c.members.join(", ") : undefined,
      }))}
      centerLabel="no mês"
      centerValue={<AnimatedMoney cents={total} />}
      formatValue={(v) => formatMoney(v, { hidden })}
      size={200}
      onSelect={() => navigate("gastos")}
    />
  );
}
