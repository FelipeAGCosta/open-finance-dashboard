import { ArrowDown, ArrowUp, ArrowUpDown, CalendarClock, Coins, LineChart as LineIcon, PieChart as PieIcon } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState, type ReactNode } from "react";
import { AnimatedMoney, Delta, Money } from "@/components/Money";
import { AreaTrend, ChartFrame, CompareLines, DonutChart, SignedBars, StackedBars } from "@/components/charts";
import { HowCalculated, Term } from "@/components/Help";
import { InTransitNote, WealthTerm } from "@/components/Wealth";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/states";
import { Badge, Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";
import type { Asset, Investments } from "@/lib/api";
import { ASSET_CLASS_ORDER, SERIES, assetClassColor } from "@/lib/colors";
import { formatDate, formatDateTime, formatDayTime, formatMoney, formatMonth, formatNumber, formatPercent } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { useHiddenValues } from "@/lib/preferences";
import { useInvestments } from "@/lib/queries";
import { cn } from "@/lib/utils";

type SortKey = "label" | "class" | "quantity" | "price" | "balance" | "pct" | "variation" | "dividends";

export function InvestmentsPage() {
  const query = useInvestments();
  const [hidden] = useHiddenValues();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton cards={2} />;
  const data = query.data;
  if (!data.snapshot_date) {
    return (
      <Card>
        <EmptyState icon={<PieIcon className="h-5 w-5" />} title="Nenhuma foto da carteira ainda">
          A carteira aparece depois da primeira sincronização com investimentos.
        </EmptyState>
      </Card>
    );
  }
  const format = (v: number) => formatMoney(v, { hidden });
  return (
    <div className="space-y-5">
      <p className="-mt-1 text-[12.5px] text-muted">
        {data.data_as_of ? <>Dados da Pluggy até {formatDateTime(data.data_as_of)} · </> : null}foto da carteira de {formatDate(data.snapshot_date)}
      </p>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <AllocationCard data={data} />
        <Card className="xl:col-span-7">
          <CardHeader title="Evolução da carteira" subtitle="Quanto a carteira valeu em cada dia? (aportes incluídos)" />
          <CardBody className="px-2 pt-2">
            {data.evolution.length >= 3 ? (
              <AreaTrend data={data.evolution} dataKey="value" label="Carteira" formatX={(v) => formatDate(v, "day")} height={392} color="var(--series-1)" />
            ) : (
              <FewDays days={data.evolution.length} needed={3} what="a linha de evolução" />
            )}
          </CardBody>
        </Card>
      </div>

      <PerformanceCard performance={data.performance} aspirational={data.aspirational} />

      <MonthlyCard monthly={data.monthly} />

      <AssetsTable assets={data.assets} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-12">
          <CardHeader title="Renda fixa" subtitle="Quanto cada título rendeu desde a aplicação?" />
          <CardBody className="overflow-x-auto pt-2">
            <FixedIncomeTable rows={data.fixed_income} />
          </CardBody>
        </Card>
        <DividendsCard dividends={data.dividends} format={format} />
      </div>
    </div>
  );
}

function AllocationCard({ data }: { data: Investments }) {
  const [hidden] = useHiddenValues();
  const [view, setView] = useState<"classe" | "lugar">("classe");
  const format = (v: number) => formatMoney(v, { hidden });
  const items =
    view === "classe"
      ? data.allocation.map((a) => ({ name: a.class, value: a.cents, color: assetClassColor(a.class) }))
      : data.allocation_by_place.map((g) => ({ name: g.label, value: g.cents, color: g.color }));
  return (
    <Card className="xl:col-span-5">
      <CardHeader
        title="Alocação"
        subtitle="Onde está o dinheiro?"
        action={
          <Segmented
            label="Ver alocação"
            value={view}
            onChange={setView}
            options={[
              { value: "classe", label: "Por classe" },
              { value: "lugar", label: "Reserva × Patrimônio" },
            ]}
          />
        }
      />
      <CardBody>
        <div className="mb-5">
          <p className="text-[13px] font-medium text-muted">
            <WealthTerm />
          </p>
          <AnimatedMoney cents={data.wealth?.total ?? data.total} className="mt-1 block text-[30px] font-semibold tracking-[-0.03em]" />
          <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[13px] text-muted">
            <Term help={GLOSSARY.bruto}>
              <span>carteira</span>
            </Term>
            <Money cents={data.total} className="text-text-2 tnum" />
            <span>·</span>
            <Term help={GLOSSARY.liquido}>
              <span>
                líquido de IR <Money cents={data.total_net} className="text-text-2 tnum" />
              </span>
            </Term>
          </p>
          <InTransitNote wealth={data.wealth} className="mt-2" />
          {data.bank_view ? <BankView view={data.bank_view} quotesAt={data.data_as_of} /> : null}
        </div>
        <DonutChart
          data={items}
          centerLabel="carteira"
          centerValue={<AnimatedMoney cents={data.total} />}
          formatValue={format}
          size={200}
        />
        {view === "lugar" ? (
          <p className="mt-4 text-[12px] text-muted">Reserva de emergência e Patrimônio: cada real em um lugar só. Os detalhes ficam na tela Plano.</p>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** Os mesmos grupos do app do banco, para conferir os totais em segundos. */
function BankView({ view, quotesAt }: { view: NonNullable<Investments["bank_view"]>; quotesAt: string | null }) {
  const title = view.institution && view.institution !== "Banco" ? `Como no app do ${view.institution}` : "Como no app do banco";
  return (
    <section aria-label={title} className="mt-4 rounded-xl border border-border px-3.5 py-3">
      <p className="text-[12.5px] font-medium text-text">{title}</p>
      <dl className="mt-1.5 space-y-1 text-[13px]">
        {view.groups.map((g) => (
          <div key={g.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-text-2">{g.label}</dt>
            <dd>
              <Money cents={g.cents} className="tnum" />
            </dd>
          </div>
        ))}
        {view.in_transit > 0 ? (
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-text-2">Em trânsito (ainda fora da foto)</dt>
            <dd>
              <Money cents={view.in_transit} className="tnum" />
            </dd>
          </div>
        ) : null}
        <div className="flex items-baseline justify-between gap-3 border-t border-border pt-1 font-semibold">
          <dt>Total investido</dt>
          <dd>
            <Money cents={view.total} className="tnum" />
          </dd>
        </div>
      </dl>
      {quotesAt ? <p className="mt-1.5 text-[12px] text-muted">Cotações de {formatDayTime(quotesAt)} (o app do banco mostra ao vivo).</p> : null}
    </section>
  );
}

function MonthlyCard({ monthly }: { monthly: Investments["monthly"] }) {
  const [hidden] = useHiddenValues();
  const format = (v: number | null | undefined) => formatMoney(v, { hidden });
  const pct = (v: number | null) => formatPercent(v, { precise: true, signed: true });
  if (!monthly.months.length) {
    return (
      <Card>
        <CardHeader title="Rendimento mês a mês" subtitle="Quanto a carteira rendeu em cada mês?" />
        <FewDays days={0} needed={2} what="o rendimento mensal" />
      </Card>
    );
  }
  const note = (m: Investments["monthly"]["months"][number]) =>
    m.partial_since ? `parcial, desde ${formatDate(m.partial_since, "day")}` : m.in_progress ? "em andamento" : "";
  return (
    <Card>
      <CardHeader title="Rendimento mês a mês" subtitle="Quanto a carteira rendeu em cada mês, separando o que foi aporte do que foi ganho?" />
      <CardBody className="pt-2">
        <ChartFrame
          chart={
            <SignedBars
              data={monthly.months.map((m) => ({ key: m.month, value: m.gain, note: note(m) }))}
              formatX={(m) => formatMonth(m, "short")}
              formatValue={(v) => formatMoney(v, { signed: true, hidden })}
              label="Ganho do mês"
            />
          }
          table={{
            headers: ["Mês", "Investido no início", "Aportei", "Resgatei", "Ganho", "Rendimento", "CDI", "IPCA", "Meta"],
            rows: monthly.months.map((m) => [
              `${formatMonth(m.month, "title")}${note(m) ? ` (${note(m)})` : ""}`,
              format(m.start_value),
              format(m.contributions),
              format(m.redemptions),
              formatMoney(m.gain, { signed: true, hidden }),
              pct(m.twr),
              pct(m.cdi),
              m.ipca === null ? "—" : pct(m.ipca),
              pct(m.target),
            ]),
          }}
        />
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MiniStat label="Aportei no período" value={format(monthly.total_contributions)} />
          <MiniStat label="Resgatei no período" value={format(monthly.total_redemptions)} />
          <MiniStat
            label="Saldo (aportei − resgatei)"
            value={formatMoney(monthly.total_contributions - monthly.total_redemptions, { signed: true, hidden })}
          />
          <MiniStat label="Ganho no período" value={formatMoney(monthly.total_gain, { signed: true, hidden })} strong />
        </div>
        {monthly.total_redemptions > monthly.total_contributions ? (
          <p className="mt-2 text-[12.5px] text-warning">No período você resgatou mais do que aportou: o ganho é dos investimentos; o dinheiro novo foi negativo.</p>
        ) : null}
        <HowCalculated>
          <p>Ganho do mês = valor no fim − valor no início − aportes + resgates + proventos pagos na conta.</p>
          <p className="mt-1.5">
            <Term help={GLOSSARY.twr}>
              <span>Rendimento (TWR)</span>
            </Term>{" "}
            do mês: o ganho dividido pelo valor investido, ponderando cada aporte pelos dias em que ficou aplicado. O mês em andamento e o
            primeiro mês (fotos desde o meio do mês) são parciais.
          </p>
          <p className="mt-1.5">Valores brutos (antes do IR), comparáveis com o CDI e o IPCA do mesmo período.</p>
        </HowCalculated>
      </CardBody>
    </Card>
  );
}

function MiniStat({ label, value, strong }: { label: string; value: ReactNode; strong?: boolean }) {
  return (
    <div className={cn("rounded-xl border border-border px-4 py-3", strong ? "bg-accent-soft" : "bg-surface-2")}>
      <p className="text-[12px] text-muted">{label}</p>
      <p className={cn("mt-0.5 text-[17px] font-semibold tnum", strong && "text-accent")}>{value}</p>
    </div>
  );
}

function DividendsCard({ dividends, format }: { dividends: Investments["dividends"]; format: (v: number) => string }) {
  const classes = ASSET_CLASS_ORDER.filter((c) => dividends.by_class.some((m) => (m.by_class[c] ?? 0) > 0));
  const byAsset = new Map<string, number>();
  dividends.by_class.forEach((m) => Object.entries(m.by_asset).forEach(([asset, cents]) => byAsset.set(asset, (byAsset.get(asset) ?? 0) + cents)));
  const assets = [...byAsset.entries()].sort((a, b) => b[1] - a[1]);
  const data = dividends.by_class.map((m) => ({ month: m.month, ...m.by_class }));
  return (
    <Card className="xl:col-span-12">
      <CardHeader title="Proventos" subtitle="Quanto os ativos pagaram em cada mês?" action={<Money cents={dividends.total} className="text-[15px] font-semibold tnum" />} />
      <CardBody className="pt-1">
        {dividends.total === 0 ? (
          <EmptyState icon={<Coins className="h-5 w-5" />} title="Nenhum provento nos últimos 12 meses" className="py-6" />
        ) : (
          <>
            <ChartFrame
              chart={
                <StackedBars
                  data={data}
                  xKey="month"
                  series={classes.map((c) => ({ key: c, label: c, color: assetClassColor(c) }))}
                  formatX={(m) => formatMonth(m, "short")}
                  formatValue={format}
                  height={220}
                />
              }
              table={{
                headers: ["Mês", ...classes, "Total"],
                rows: dividends.by_class.map((m) => [formatMonth(m.month, "title"), ...classes.map((c) => format(m.by_class[c] ?? 0)), format(m.total)]),
              }}
            />
            <p className="mb-1.5 mt-4 text-[12.5px] font-medium text-muted">Por ativo, nos 12 meses</p>
            <ul className="max-h-[190px] space-y-1 overflow-auto pr-1 text-[13px]">
              {assets.map(([asset, cents]) => (
                <li key={asset} className="flex items-center justify-between gap-3">
                  <span>{asset}</span>
                  <span className="tnum text-text-2">{format(cents)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function FewDays({ days, needed, what }: { days: number; needed: number; what: string }) {
  const progress = Math.min(1, days / needed);
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="relative mb-5 grid h-16 w-16 place-items-center">
        <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
          <circle cx="18" cy="18" r="16" fill="none" stroke="var(--surface-3)" strokeWidth="2.5" />
          <motion.circle
            cx="18"
            cy="18"
            r="16"
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={100.5}
            initial={{ strokeDashoffset: 100.5 }}
            animate={{ strokeDashoffset: 100.5 * (1 - progress) }}
            transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
          />
        </svg>
        <CalendarClock className="h-5 w-5 text-accent" />
      </div>
      <p className="text-[15px] font-semibold">
        {days} de {needed} dias de foto
      </p>
      <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">
        {what.charAt(0).toUpperCase() + what.slice(1)} usa as fotos diárias da carteira, que começaram agora. A cada
        sincronização diária entra mais um ponto; em {Math.max(0, needed - days)} dia(s) o gráfico aparece aqui.
      </p>
    </div>
  );
}

function PerformanceCard({ performance, aspirational }: { performance: Investments["performance"]; aspirational: number }) {
  const acc = performance.accumulated;
  const metaLabel = `Meta (${formatPercent(aspirational)} a.a.)`;
  return (
    <Card>
      <CardHeader
        title="Rentabilidade acumulada"
        subtitle={
          performance.first_date
            ? `A carteira rendeu mais que o CDI e a inflação desde ${formatDate(performance.first_date)}?`
            : "A carteira rendeu mais que o CDI e a inflação?"
        }
        action={<Badge tone="neutral">{performance.days} dias de foto</Badge>}
      />
      <CardBody className="pt-2">
        {!performance.enough || !acc ? (
          <FewDays days={performance.days} needed={performance.min_days} what="a rentabilidade" />
        ) : (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_260px]">
            <ChartFrame
              chart={
                <CompareLines
                  data={performance.series}
                  formatX={(v) => formatDate(v, "day")}
                  series={[
                    { key: "twr", label: "Carteira (TWR)", color: SERIES[0] as string, width: 2.5 },
                    { key: "cdi", label: "CDI", color: SERIES[2] as string },
                    { key: "ipca", label: "IPCA", color: SERIES[1] as string },
                    { key: "target", label: metaLabel, color: "var(--text-2)", dashed: true, width: 1.5 },
                  ]}
                />
              }
              table={{
                headers: ["Data", "Carteira (TWR)", "CDI", "IPCA", "Meta"],
                rows: performance.series
                  .filter((_, i, all) => i % 7 === 0 || i === all.length - 1)
                  .map((p) => [
                    formatDate(p.date),
                    formatPercent(p.twr, { precise: true }),
                    formatPercent(p.cdi, { precise: true }),
                    formatPercent(p.ipca, { precise: true }),
                    formatPercent(p.target, { precise: true }),
                  ]),
              }}
            />
            <dl className="grid content-start grid-cols-2 gap-3 xl:grid-cols-1">
              <Metric label={<Term help={GLOSSARY.twr}><span>Carteira (TWR)</span></Term>} value={formatPercent(acc.twr, { precise: true, signed: true })} hint="mede os investimentos, sem o efeito dos aportes" strong />
              <Metric label={<Term help={GLOSSARY.xirr}><span>Seu dinheiro (XIRR)</span></Term>} value={formatPercent(acc.xirr_annual, { precise: true, signed: true })} hint={`ao ano · ${formatPercent(acc.xirr_period, { precise: true, signed: true })} no período`} />
              <Metric label={<Term help={GLOSSARY.cdi}><span>CDI no período</span></Term>} value={formatPercent(acc.cdi, { precise: true, signed: true })} />
              <Metric label={<Term help={GLOSSARY.ipca}><span>IPCA no período</span></Term>} value={formatPercent(acc.ipca, { precise: true, signed: true })} hint={acc.notes.find((n) => n.includes("IPCA"))} />
              <Metric
                label={<Term help={GLOSSARY.metaAspiracional}><span>{metaLabel} no período</span></Term>}
                value={formatPercent(acc.target, { precise: true, signed: true })}
                hint={acc.above_target === null ? undefined : acc.above_target ? "carteira acima da meta ✓" : "carteira abaixo da meta"}
              />
            </dl>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function Metric({ label, value, hint, strong }: { label: ReactNode; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className={cn("rounded-xl border border-border px-4 py-3", strong ? "bg-accent-soft" : "bg-surface-2")}>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className={cn("mt-1 text-[20px] font-semibold tracking-[-0.02em] tnum", strong && "text-accent")}>{value}</dd>
      {hint ? <p className="mt-0.5 text-[11.5px] leading-snug text-muted">{hint}</p> : null}
    </div>
  );
}

function AssetsTable({ assets }: { assets: Asset[] }) {
  const [hidden] = useHiddenValues();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "balance", dir: -1 });
  const sorted = useMemo(() => {
    const value = (a: Asset): number | string => {
      switch (sort.key) {
        case "label":
          return a.label;
        case "class":
          return ASSET_CLASS_ORDER.indexOf(a.class as (typeof ASSET_CLASS_ORDER)[number]);
        case "quantity":
          return a.quantity ?? -Infinity;
        case "price":
          return a.price ?? -Infinity;
        case "pct":
        case "balance":
          return a.balance;
        case "variation":
          return a.variation?.pct ?? -Infinity;
        case "dividends":
          return a.dividends_12m ?? -Infinity;
      }
    };
    return [...assets].sort((x, y) => {
      const a = value(x);
      const b = value(y);
      const cmp = typeof a === "string" && typeof b === "string" ? a.localeCompare(b, "pt-BR") : (a as number) - (b as number);
      return cmp * sort.dir;
    });
  }, [assets, sort]);

  const header = (key: SortKey, label: string, align: "left" | "right" = "right") => {
    const active = sort.key === key;
    const Icon = active ? (sort.dir === 1 ? ArrowUp : ArrowDown) : ArrowUpDown;
    return (
      <th className={cn("px-3 py-2.5 font-medium", align === "right" ? "text-right" : "text-left")} aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
        <button
          type="button"
          onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "label" || key === "class" ? 1 : -1 }))}
          className={cn("inline-flex items-center gap-1 transition-colors hover:text-text", active && "text-text")}
        >
          {label}
          <Icon className={cn("h-3 w-3", !active && "opacity-40")} />
        </button>
      </th>
    );
  };

  return (
    <Card>
      <CardHeader title="Ativos" subtitle="Quanto cada ativo variou desde que aparece nas fotos, sem contar compras e vendas?" action={<LineIcon className="h-4 w-4 text-muted" />} />
      <CardBody className="overflow-x-auto px-3 pt-3 sm:px-4">
        <table className="data-table w-full min-w-[900px] text-[13px]">
          <thead className="text-muted">
            <tr className="border-b border-border">
              {header("label", "Ativo", "left")}
              {header("class", "Classe", "left")}
              {header("quantity", "Quantidade")}
              {header("price", "Preço atual")}
              {header("balance", "Saldo")}
              {header("pct", "% da carteira")}
              {header("variation", "Variação")}
              {header("dividends", "Proventos 12m")}
            </tr>
          </thead>
          <tbody>
            {sorted.map((a) => (
              <tr key={a.id} className="border-b border-border/60 transition-colors last:border-0 hover:bg-surface-2/60">
                <td className="px-3 py-3 font-medium">
                  <span className="flex items-center gap-2.5">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: assetClassColor(a.class) }} />
                    <span className="max-w-[240px] truncate" title={a.label}>
                      {a.label}
                    </span>
                  </span>
                </td>
                <td className="px-3 py-3 text-text-2">
                  {a.class}
                  {a.class_source === "correção manual" ? <Badge className="ml-1.5">manual</Badge> : null}
                </td>
                <td className="px-3 py-3 text-right tnum text-text-2">{a.class === "CDB/RDB" ? "—" : formatNumber(a.quantity)}</td>
                <td className="px-3 py-3 text-right tnum text-text-2">
                  {a.price !== null && a.class !== "Tesouro" && a.class !== "CDB/RDB" ? formatMoney(Math.round(a.price * 100), { hidden }) : "—"}
                </td>
                <td className="px-3 py-3 text-right tnum">
                  <span className="font-semibold">{formatMoney(a.balance, { hidden })}</span>
                  {a.net !== a.balance ? <span className="block text-[11.5px] text-muted">líquido {formatMoney(a.net, { hidden })}</span> : null}
                </td>
                <td className="px-3 py-3 text-right tnum">
                  <span className="inline-flex items-center justify-end gap-2">
                    <span className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-surface-2 lg:block">
                      <span className="block h-full rounded-full" style={{ width: `${(a.pct ?? 0) * 100}%`, background: assetClassColor(a.class) }} />
                    </span>
                    {formatPercent(a.pct)}
                  </span>
                </td>
                <td className="px-3 py-3 text-right">
                  {a.variation ? (
                    <span title={`desde ${formatDate(a.variation.since)}`}>
                      <Delta cents={a.variation.cents} pct={a.variation.pct} className="justify-end" />
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-3 text-right tnum text-text-2">{a.dividends_12m ? formatMoney(a.dividends_12m, { hidden }) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

function FixedIncomeTable({ rows }: { rows: Investments["fixed_income"] }) {
  const [hidden] = useHiddenValues();
  if (!rows.length) return <EmptyState icon={<Coins className="h-5 w-5" />} title="Nenhum título de renda fixa com saldo" className="py-6" />;
  return (
    <table className="data-table w-full min-w-[760px] text-[13px]">
      <thead className="text-left text-muted">
        <tr className="border-b border-border">
          <th className="px-3 py-2.5 font-medium">Título</th>
          <th className="px-3 py-2.5 font-medium">Taxa</th>
          <th className="px-3 py-2.5 text-right font-medium">Aplicado</th>
          <th className="px-3 py-2.5 text-right font-medium">Valor atual (bruto)</th>
          <th className="px-3 py-2.5 text-right font-medium">Rendimento</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className="border-b border-border/60 last:border-0">
            <td className="px-3 py-3">
              <span className="flex items-center gap-2.5 font-medium">
                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: assetClassColor(r.class) }} />
                {r.label}
              </span>
              {r.due_date ? <span className="ml-5 text-[11.5px] text-muted">vence em {formatDate(r.due_date)}</span> : null}
            </td>
            <td className="px-3 py-3 text-text-2">{r.rate || "—"}</td>
            <td className="px-3 py-3 text-right tnum text-text-2">{formatMoney(r.applied, { hidden })}</td>
            <td className="px-3 py-3 text-right tnum">
              <span className="font-semibold">{formatMoney(r.gross, { hidden })}</span>
              <span className="block text-[11.5px] text-muted">líquido {formatMoney(r.net, { hidden })}</span>
            </td>
            <td className="px-3 py-3 text-right">
              <Delta cents={r.profit} pct={r.return_pct} className="justify-end" />
              {r.annualized !== null ? <span className="block text-[11.5px] text-muted tnum">{formatPercent(r.annualized)} a.a.</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
