/**
 * Gráficos (Recharts) com o mesmo vocabulário visual:
 * linhas de 2px com curva suave, área com degradê, barras com cantos de 4px na ponta,
 * roscas finas com 2px de espaço entre fatias (o centro mostra a fatia em foco), grade em linha fina
 * contínua, tooltip próprio OPACO e afastado do cursor,
 * animação de entrada suave (desligada com prefers-reduced-motion) e valores mascarados
 * quando o botão de olho está ativo.
 */
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useId, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Table2, BarChart3 } from "lucide-react";
import { axisMoneyFormatter, axisPercentFormatter, formatAxisMoney, formatMoney, formatPercent, niceTicks, paddedDomain } from "@/lib/format";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";
import { Button } from "./ui/primitives";

const AXIS = { fill: "var(--muted)", fontSize: 11.5 };
const ANIMATION = 900;

function useChartMotion() {
  const reduced = useReducedMotion();
  return { isAnimationActive: !reduced, animationDuration: ANIMATION, animationEasing: "ease-out" as const };
}

// ------------------------------------------------------------------ tooltip

interface TooltipRow {
  label: string;
  value: string;
  color?: string;
  icon?: ReactNode;
}

export function TooltipCard({ title, rows }: { title: ReactNode; rows: TooltipRow[] }) {
  return (
    <div className="min-w-[180px] rounded-xl border border-border-strong bg-surface-2 px-3.5 py-2.5 shadow-card">
      <p className="mb-1.5 text-[12px] font-medium text-muted">{title}</p>
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between gap-5 text-[13px]">
            <span className="flex items-center gap-2 text-text-2">
              {row.color ? <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: row.color }} /> : null}
              {row.icon}
              {row.label}
            </span>
            <span className="font-semibold text-text tnum">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface RechartsTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: ReadonlyArray<{ value?: unknown; name?: unknown; dataKey?: unknown; color?: string; payload?: { color?: unknown } }>;
}

// ------------------------------------------------------------------ moldura com visão em tabela

/** Todo gráfico tem um "gêmeo" em tabela (acessibilidade e leitura exata dos valores). */
export function ChartFrame({
  chart,
  table,
  className,
  toolbar,
}: {
  chart: ReactNode;
  table: { headers: string[]; rows: ReactNode[][] };
  className?: string;
  toolbar?: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <div className={cn("relative", className)}>
      <div className="mb-2 flex items-center justify-end gap-2">
        {toolbar}
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={asTable}
          onClick={() => setAsTable((v) => !v)}
          title={asTable ? "Ver gráfico" : "Ver como tabela"}
        >
          {asTable ? <BarChart3 className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
          <span className="sr-only sm:not-sr-only">{asTable ? "Gráfico" : "Tabela"}</span>
        </Button>
      </div>
      {asTable ? (
        <div className="max-h-[300px] overflow-auto rounded-xl border border-border">
          <table className="data-table w-full text-[13px]">
            <thead className="sticky top-0 bg-surface-2 text-left text-muted">
              <tr>
                {table.headers.map((h, i) => (
                  <th key={h} className={cn("px-3 py-2 font-medium", i > 0 && "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, r) => (
                <tr key={r} className="border-t border-border">
                  {row.map((cell, c) => (
                    <td key={c} className={cn("px-3 py-2 text-text-2", c > 0 && "text-right tnum")}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        chart
      )}
    </div>
  );
}

// ------------------------------------------------------------------ área (patrimônio, carteira)

export function AreaTrend({
  data,
  dataKey,
  xKey = "date",
  color = "var(--accent)",
  height = 240,
  formatX,
  label,
}: {
  data: Record<string, unknown>[];
  dataKey: string;
  xKey?: string;
  color?: string;
  height?: number;
  formatX: (value: string) => string;
  label: string;
}) {
  const id = useId().replace(/:/g, "");
  const [hidden] = useHiddenValues();
  const motionProps = useChartMotion();
  // eixo: folga proporcional e marcas redondas com rótulos sempre distintos (variação pequena nunca repete o mesmo rótulo)
  const [lo, hi] = paddedDomain(data.map((d) => Number(d[dataKey])));
  const ticks = niceTicks(lo, hi, 5);
  const formatY = axisMoneyFormatter(ticks, hidden);
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: color, stopOpacity: 0.32 }} />
              <stop offset="100%" style={{ stopColor: color, stopOpacity: 0 }} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={false} tickFormatter={formatX} minTickGap={36} dy={6} />
          <YAxis
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            width={hidden ? 44 : 92}
            domain={[lo, hi]}
            ticks={ticks}
            interval={0}
            allowDataOverflow
            tickFormatter={formatY}
            className="tnum"
          />
          <Tooltip
            offset={18}
            isAnimationActive={false}
            wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            content={(props: RechartsTooltipProps) =>
              props.active && props.payload?.length ? (
                <TooltipCard
                  title={formatX(String(props.label))}
                  rows={[{ label, value: formatMoney(Number(props.payload[0]?.value), { hidden }), color }]}
                />
              ) : null
            }
          />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            fill={`url(#grad-${id})`}
            activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--surface)", fill: color }}
            {...motionProps}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ------------------------------------------------------------------ barras agrupadas (receitas × despesas)

export function GroupedBars({
  data,
  series,
  xKey,
  formatX,
  height = 260,
}: {
  data: Record<string, unknown>[];
  series: { key: string; label: string; color: string; icon?: ReactNode }[];
  xKey: string;
  formatX: (value: string) => string;
  height?: number;
}) {
  const [hidden] = useHiddenValues();
  const motionProps = useChartMotion();
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-[12.5px] text-text-2" aria-hidden>
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
            {s.icon}
            {s.label}
          </span>
        ))}
      </div>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} barGap={2} barCategoryGap="28%" margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} tickFormatter={formatX} dy={6} />
            <YAxis
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={hidden ? 44 : 78}
              tickFormatter={(v: number) => formatAxisMoney(v, hidden)}
            />
            <Tooltip
              offset={18}
              isAnimationActive={false}
              wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
              cursor={{ fill: "var(--surface-2)", radius: 6 }}
              content={(props: RechartsTooltipProps) =>
                props.active && props.payload?.length ? (
                  <TooltipCard
                    title={formatX(String(props.label))}
                    rows={series.map((s) => ({
                      label: s.label,
                      color: s.color,
                      icon: s.icon,
                      value: formatMoney(Number(props.payload?.find((p) => p.dataKey === s.key)?.value ?? 0), { hidden }),
                    }))}
                  />
                ) : null
              }
            />
            {series.map((s) => (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={18} {...motionProps} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ rosca (um componente para todas as telas)

export interface DonutDatum {
  name: string;
  value: number;
  color: string;
  /** Texto extra na legenda (ex.: categorias agrupadas em "Outras"). */
  detail?: string;
}

/**
 * Rosca fina em SVG. Sem caixa flutuante: ao passar o mouse (ou focar a legenda), o CENTRO mostra a
 * fatia em foco (nome, valor, %) e ela ganha leve destaque; ao sair, volta o total. A legenda ao lado
 * repete nome, valor e % (a cor nunca é a única pista) e controla o mesmo foco.
 */
export function DonutChart({
  data,
  centerLabel,
  centerValue,
  formatValue,
  size = 210,
  thickness = 16,
  onSelect,
  layout = "stack",
  legendLimit,
}: {
  data: DonutDatum[];
  centerLabel: string;
  centerValue: ReactNode;
  formatValue: (value: number) => string;
  size?: number;
  thickness?: number;
  onSelect?: (name: string) => void;
  layout?: "stack" | "side";
  legendLimit?: number;
}) {
  const [focus, setFocus] = useState<number | null>(null);
  const total = data.reduce((sum, d) => sum + Math.max(0, d.value), 0);
  const focused = focus !== null ? data[focus] : undefined;
  return (
    <div className={cn("flex w-full gap-6", layout === "side" ? "flex-col items-center sm:flex-row" : "flex-col items-center")}>
      <DonutRing data={data} total={total} size={size} thickness={thickness} focus={focus} onFocus={setFocus} onSelect={onSelect}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={focused ? focused.name : "__total"}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
            className="flex max-w-[70%] flex-col items-center"
          >
            {focused ? (
              <>
                <span className="flex max-w-full items-center gap-1.5 text-[12px] text-muted">
                  <span className="h-2 w-2 shrink-0 rounded-[3px]" style={{ background: focused.color }} />
                  <span className="truncate">{focused.name}</span>
                </span>
                <span className="mt-0.5 text-[18px] font-semibold tracking-[-0.02em] text-text tnum">{formatValue(focused.value)}</span>
                <span className="text-[12px] text-muted tnum">{formatPercent(total ? focused.value / total : null)}</span>
              </>
            ) : (
              <>
                <span className="text-[12px] text-muted">{centerLabel}</span>
                <span className="mt-0.5 text-[19px] font-semibold tracking-[-0.02em] text-text">{centerValue}</span>
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </DonutRing>
      <ul className="w-full min-w-0 flex-1 space-y-1" onMouseLeave={() => setFocus(null)}>
        {data.slice(0, legendLimit ?? data.length).map((item, index) => (
          <li key={item.name}>
            <button
              type="button"
              onClick={onSelect ? () => onSelect(item.name) : undefined}
              onMouseEnter={() => setFocus(index)}
              onFocus={() => setFocus(index)}
              onBlur={() => setFocus(null)}
              title={item.detail}
              aria-label={`${item.name}: ${formatValue(item.value)}, ${formatPercent(total ? item.value / total : null)}`}
              className={cn(
                "group flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors",
                focus === index ? "bg-surface-2" : "hover:bg-surface-2",
                !onSelect && "cursor-default",
              )}
            >
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: item.color }} />
              <span className="min-w-0 flex-1 truncate text-text-2 group-hover:text-text">{item.name}</span>
              <span className="tnum font-medium text-text">{formatValue(item.value)}</span>
              <span className="w-12 text-right tnum text-muted">{formatPercent(total ? item.value / total : null)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DonutRing({
  data,
  total,
  size,
  thickness,
  focus,
  onFocus,
  onSelect,
  children,
}: {
  data: DonutDatum[];
  total: number;
  size: number;
  thickness: number;
  focus: number | null;
  onFocus: (index: number | null) => void;
  onSelect?: (name: string) => void;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  const [drawn, setDrawn] = useState(Boolean(reduced));
  useEffect(() => {
    const frame = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const radius = (size - thickness) / 2 - 3; // folga para o destaque não cortar
  const circumference = 2 * Math.PI * radius;
  const gap = data.length > 1 ? 2.5 : 0; // 2px de superfície entre fatias
  const lengths = data.map((d) => (total ? (Math.max(0, d.value) / total) * circumference : 0));
  const arcs = data.map((d, index) => ({
    ...d,
    index,
    start: lengths.slice(0, index).reduce((sum, l) => sum + l, 0),
    length: Math.max(0, (lengths[index] ?? 0) - gap),
  }));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} onMouseLeave={() => onFocus(null)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--surface-2)" strokeWidth={thickness} />
        {arcs.map((arc) => {
          const active = focus === arc.index;
          const dimmed = focus !== null && !active;
          return (
            <circle
              key={arc.name}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={active ? thickness + 6 : thickness}
              strokeDasharray={`${drawn ? arc.length : 0} ${circumference}`}
              strokeDashoffset={-arc.start}
              style={{
                opacity: dimmed ? 0.35 : 1,
                cursor: onSelect ? "pointer" : "default",
                transition: reduced
                  ? undefined
                  : "stroke-dasharray 900ms cubic-bezier(0.16,1,0.3,1), stroke-width 180ms ease, opacity 180ms ease",
              }}
              pointerEvents="stroke"
              onMouseEnter={() => onFocus(arc.index)}
              onClick={onSelect ? () => onSelect(arc.name) : undefined}
            />
          );
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center">{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ barras horizontais (categorias)

export function HorizontalBars({
  data,
  formatValue,
  onSelect,
  selected,
}: {
  data: { name: string; value: number; color: string; count?: number }[];
  formatValue: (value: number) => string;
  onSelect?: (name: string) => void;
  selected?: string | null;
}) {
  const max = Math.max(...data.map((d) => d.value), 1);
  const reduced = useReducedMotion();
  return (
    <ul className="space-y-2.5">
      {data.map((d, index) => (
        <li key={d.name}>
          <button
            type="button"
            onClick={onSelect ? () => onSelect(d.name) : undefined}
            className={cn(
              "group w-full rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-2",
              selected === d.name && "bg-surface-2",
            )}
          >
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="flex min-w-0 items-center gap-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: d.color }} />
                <span className="truncate text-text-2 group-hover:text-text">{d.name}</span>
                {d.count !== undefined ? <span className="text-[11.5px] text-muted">{d.count}</span> : null}
              </span>
              <span className="shrink-0 whitespace-nowrap tnum font-medium text-text">{formatValue(d.value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(2, (d.value / max) * 100)}%`,
                  background: d.color,
                  transition: reduced ? undefined : `width 900ms cubic-bezier(0.16,1,0.3,1) ${index * 40}ms`,
                }}
              />
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ barra segmentada (fixo × variável)

export function SegmentedMeter({
  segments,
  formatValue,
}: {
  segments: { label: string; value: number; color: string; icon?: ReactNode }[];
  formatValue: (value: number) => string;
}) {
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  return (
    <div>
      <div className="flex h-3 gap-[2px] overflow-hidden rounded-full bg-surface-2">
        {segments.map((s) =>
          s.value > 0 ? (
            <div
              key={s.label}
              className="h-full first:rounded-l-full last:rounded-r-full transition-[width] duration-700"
              style={{ width: `${(s.value / (total || 1)) * 100}%`, background: s.color }}
              title={`${s.label}: ${formatValue(s.value)}`}
            />
          ) : null,
        )}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(120px,1fr))]">
        {segments.map((s) => (
          <div key={s.label} className="min-w-0">
            <div className="flex items-center gap-1.5 text-[12.5px] text-muted">
              <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
              {s.icon}
              {s.label}
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-[17px] font-semibold tracking-[-0.01em] tnum">{formatValue(s.value)}</span>
              <span className="text-[12px] text-muted tnum">{formatPercent(total ? s.value / total : null)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ linhas (TWR × CDI × IPCA)

export function CompareLines({
  data,
  series,
  formatX,
  height = 280,
}: {
  data: Record<string, unknown>[];
  series: { key: string; label: string; color: string; width?: number; dashed?: boolean }[];
  formatX: (value: string) => string;
  height?: number;
}) {
  const motionProps = useChartMotion();
  const last = data[data.length - 1] ?? {};
  const [lo, hi] = paddedDomain(data.flatMap((d) => series.map((s) => d[s.key])).filter((v): v is number => typeof v === "number"), 0.01);
  const ticks = niceTicks(lo, hi, 5);
  const formatY = axisPercentFormatter(ticks);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px]">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-2 text-text-2">
            <span
              className="h-[3px] w-4 rounded-full"
              style={s.dashed ? { background: `repeating-linear-gradient(90deg, ${s.color} 0 5px, transparent 5px 8px)` } : { background: s.color }}
            />
            {s.label}
            <span className="font-semibold text-text tnum">{formatPercent(last[s.key] as number | null, { precise: true, signed: true })}</span>
          </span>
        ))}
      </div>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={formatX} minTickGap={40} dy={6} />
            <YAxis
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={64}
              domain={[lo, hi]}
              ticks={ticks}
              interval={0}
              tickFormatter={formatY}
            />
            <Tooltip
              offset={18}
              isAnimationActive={false}
              wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
              cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
              content={(props: RechartsTooltipProps) =>
                props.active && props.payload?.length ? (
                  <TooltipCard
                    title={formatX(String(props.label))}
                    rows={series.map((s) => ({
                      label: s.label,
                      color: s.color,
                      value: formatPercent(
                        (props.payload?.find((p) => p.dataKey === s.key)?.value as number | undefined) ?? null,
                        { precise: true, signed: true },
                      ),
                    }))}
                  />
                ) : null
              }
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={s.width ?? 2}
                strokeDasharray={s.dashed ? "6 4" : undefined}
                dot={false}
                activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--surface)", fill: s.color }}
                connectNulls
                {...motionProps}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ mini barras (proventos por mês)

export function MiniBars({
  data,
  color,
  formatX,
  formatValue,
  height = 150,
}: {
  data: { key: string; value: number }[];
  color: string;
  formatX: (value: string) => string;
  formatValue: (value: number) => string;
  height?: number;
}) {
  const motionProps = useChartMotion();
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="22%">
          <XAxis dataKey="key" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} tickFormatter={formatX} interval="preserveStartEnd" dy={6} />
          <Tooltip
            offset={18}
            isAnimationActive={false}
            wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
            cursor={{ fill: "var(--surface-2)", radius: 6 }}
            content={(props: RechartsTooltipProps) =>
              props.active && props.payload?.length ? (
                <TooltipCard title={formatX(String(props.label))} rows={[{ label: "Proventos", value: formatValue(Number(props.payload[0]?.value)), color }]} />
              ) : null
            }
          />
          <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} maxBarSize={22} {...motionProps} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ------------------------------------------------------------------ barras empilhadas (proventos por classe)

export function StackedBars({
  data,
  series,
  xKey,
  formatX,
  formatValue,
  height = 240,
}: {
  data: Record<string, unknown>[];
  series: { key: string; label: string; color: string }[];
  xKey: string;
  formatX: (value: string) => string;
  formatValue: (value: number) => string;
  height?: number;
}) {
  const [hidden] = useHiddenValues();
  const motionProps = useChartMotion();
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-text-2">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }} barCategoryGap="26%">
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--axis)" }} tickFormatter={formatX} dy={6} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={hidden ? 44 : 84} tickFormatter={(v: number) => formatAxisMoney(v, hidden)} />
            <Tooltip
              offset={18}
              isAnimationActive={false}
              wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
              cursor={{ fill: "var(--surface-2)", radius: 6 }}
              content={(props: RechartsTooltipProps) => {
                if (!props.active || !props.payload?.length) return null;
                const rows = series
                  .map((s) => ({ s, value: Number(props.payload?.find((p) => p.dataKey === s.key)?.value ?? 0) }))
                  .filter((r) => r.value > 0);
                const total = rows.reduce((sum, r) => sum + r.value, 0);
                return (
                  <TooltipCard
                    title={formatX(String(props.label))}
                    rows={[
                      ...rows.map((r) => ({ label: r.s.label, color: r.s.color, value: formatValue(r.value) })),
                      { label: "Total", value: formatValue(total) },
                    ]}
                  />
                );
              }}
            />
            {series.map((s, index) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                stackId="total"
                fill={s.color}
                stroke="var(--surface)"
                strokeWidth={1}
                radius={index === series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                maxBarSize={26}
                {...motionProps}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ barras com sinal (ganho do mês)

export function SignedBars({
  data,
  formatX,
  formatValue,
  label,
  height = 220,
}: {
  data: { key: string; value: number; note?: string }[];
  formatX: (value: string) => string;
  formatValue: (value: number) => string;
  label: string;
  height?: number;
}) {
  const [hidden] = useHiddenValues();
  const motionProps = useChartMotion();
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }} barCategoryGap="30%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="key" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={formatX} dy={6} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={hidden ? 44 : 84} tickFormatter={(v: number) => formatAxisMoney(v, hidden)} />
          <ReferenceLine y={0} stroke="var(--axis)" />
          <Tooltip
            offset={18}
            isAnimationActive={false}
            wrapperStyle={{ zIndex: 30, pointerEvents: "none" }}
            cursor={{ fill: "var(--surface-2)", radius: 6 }}
            content={(props: RechartsTooltipProps) => {
              const item = props.payload?.[0];
              if (!props.active || !item) return null;
              const value = Number(item.value);
              const note = (item.payload as { note?: string } | undefined)?.note;
              return (
                <TooltipCard
                  title={`${formatX(String(props.label))}${note ? ` · ${note}` : ""}`}
                  rows={[{ label, value: formatValue(value), color: value >= 0 ? "var(--income)" : "var(--expense)" }]}
                />
              );
            }}
          />
          <Bar dataKey="value" radius={[4, 4, 4, 4]} maxBarSize={30} {...motionProps}>
            {data.map((d) => (
              <Cell key={d.key} fill={d.value >= 0 ? "var(--income)" : "var(--expense)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ------------------------------------------------------------------ barra de progresso (planejado × feito)

export function ProgressBar({ value, max, color = "var(--accent)", label }: { value: number; max: number; color?: string; label: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) : value > 0 ? 1 : 0;
  return (
    <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${pct * 100}%` }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}
