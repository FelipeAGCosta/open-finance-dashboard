/** "Sua carteira × alvo": uma linha por classe, com barra atual × alvo e uma frase simples. */
import { ChevronDown } from "lucide-react";
import { HowCalculated, Term } from "@/components/Help";
import { Money } from "@/components/Money";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";
import type { Plan } from "@/lib/api";
import { PATRIMONY_COLOR } from "@/lib/colors";
import { formatMoney, formatPercent } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { bucketText } from "@/lib/planText";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";

const HELP: Partial<Record<string, string>> = { acoes_nucleo: GLOSSARY.nucleo, acoes_mantidas: GLOSSARY.manter, satelite: GLOSSARY.satelite };

/** Barra horizontal: preenchimento = hoje; traço = alvo (mesma escala para todas as linhas). */
function TargetBar({ current, target, scale, warn, label }: { current: number | null; target: number | null; scale: number; warn?: boolean; label: string }) {
  const width = (v: number | null) => `${Math.min(100, ((v ?? 0) / scale) * 100)}%`;
  return (
    <div className="relative h-2.5 rounded-full bg-surface-2" role="img" aria-label={label}>
      <div className="h-full rounded-full" style={{ width: width(current), background: warn ? "var(--warning)" : PATRIMONY_COLOR }} />
      {target !== null ? <span aria-hidden className="absolute -top-1 h-[18px] w-[2px] rounded-full bg-text" style={{ left: `calc(${width(target)} - 1px)` }} /> : null}
    </div>
  );
}

export function PortfolioCard({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const p = plan.patrimony;
  const format = (v: number | null | undefined) => formatMoney(v, { hidden });
  const rows = p.buckets.filter((b) => b.current > 0 || (b.target_pct ?? 0) > 0);
  const scale = Math.max(0.01, ...rows.map((b) => Math.max(b.current_pct ?? 0, b.target_pct ?? 0)));
  const coreScale = Math.max(0.01, ...p.core.map((c) => Math.max(c.current_pct ?? 0, c.target_pct ?? 0)));
  return (
    <Card>
      <CardHeader
        title={
          <Term help={GLOSSARY.patrimonio}>
            <span>Sua carteira × alvo</span>
          </Term>
        }
        subtitle="Cada classe do Patrimônio está perto da porcentagem que você definiu?"
        action={<Money cents={p.current} className="text-[15px] font-semibold tnum" />}
      />
      <CardBody>
        {!p.target_defined ? (
          <p className="mb-4 rounded-xl border border-dashed border-border-strong px-3 py-2.5 text-[12.5px] text-muted">
            Defina os alvos da carteira em “Ajustar o plano” para comparar o atual com o alvo.
          </p>
        ) : null}
        <ul className="space-y-4" aria-label="Atual × alvo por classe">
          {rows.map((b) => {
            const warn = b.state === "acima_teto";
            const pending = b.state === "abaixo" && b.suggested;
            return (
              <li key={b.bucket}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-[13.5px]">
                  <span className="font-medium">
                    {HELP[b.bucket] ? (
                      <Term help={HELP[b.bucket] as string}>
                        <span>{b.label}</span>
                      </Term>
                    ) : (
                      b.label
                    )}
                    <span className="ml-2 text-[12.5px] font-normal text-muted tnum">
                      {formatPercent(b.current_pct)}
                      {b.target_pct !== null ? ` · ${b.cap ? "teto" : "alvo"} ${formatPercent(b.target_pct)}` : ""}
                    </span>
                  </span>
                  <span className={cn("text-[13px]", warn ? "font-medium text-warning" : pending ? "font-medium text-text" : "text-text-2")}>{bucketText(b, format)}</span>
                </div>
                <div className="mt-1.5">
                  <TargetBar
                    current={b.current_pct}
                    target={b.target_pct}
                    scale={scale}
                    warn={warn}
                    label={`${b.label}: ${formatPercent(b.current_pct)} hoje${b.target_pct !== null ? `, ${b.cap ? "teto" : "alvo"} ${formatPercent(b.target_pct)}` : ""}`}
                  />
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[12px] text-muted">A barra mostra quanto da carteira está na classe hoje; o traço marca o alvo.</p>

        {p.core.length ? (
          <details className="group mt-4 rounded-xl border border-border">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 text-[13px] font-medium">
              Empresas do núcleo ({p.core.length})
              <ChevronDown className="h-4 w-4 text-muted transition-transform group-open:rotate-180" />
            </summary>
            <ul className="space-y-2.5 border-t border-border p-3">
              {p.core.map((c) => (
                <li key={c.ticker}>
                  <div className="flex justify-between gap-3 text-[12.5px]">
                    <span className="font-medium">{c.ticker}</span>
                    <span className="tnum text-text-2">
                      {format(c.current)} · {formatPercent(c.current_pct)} da carteira · peso {formatPercent(c.target_pct)}
                    </span>
                  </div>
                  <div className="mt-1">
                    <TargetBar current={c.current_pct} target={c.target_pct} scale={coreScale} label={`${c.ticker}: ${formatPercent(c.current_pct)} do Patrimônio`} />
                  </div>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <HowCalculated>
          <p>
            Percentuais sobre o Patrimônio (tudo o que está investido menos a Reserva de emergência). “Faltam R$ X” = alvo × total do Patrimônio − valor de
            hoje. Até 2 pontos percentuais de distância conta como “no alvo”.
          </p>
          <p className="mt-1.5">
            Classes: renda fixa acima da Reserva; ETFs pela região; ações e BDRs marcadas como núcleo (recebem aporte); FIIs e ações mantidas (só
            acompanham); satélite (oportunidades, com teto). O peso de cada empresa do núcleo é{" "}
            {p.core_weights === "iguais" ? "igual" : p.core_weights === "atual" ? "a proporção que ela já tem hoje" : "o que você definiu"}.
          </p>
          <ul className="mt-2">
            {p.buckets.filter((b) => b.deviation_pct !== null).map((b) => (
              <li key={b.bucket} className="flex justify-between gap-3 py-0.5 tnum">
                <span>{b.label}</span>
                <span>
                  {formatPercent(b.current_pct)} − {formatPercent(b.target_pct)} = {((b.deviation_pct ?? 0) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1, signDisplay: "exceptZero" })} p.p. (
                  {formatMoney(b.deviation_cents, { hidden, signed: true })})
                </span>
              </li>
            ))}
          </ul>
        </HowCalculated>
      </CardBody>
    </Card>
  );
}
