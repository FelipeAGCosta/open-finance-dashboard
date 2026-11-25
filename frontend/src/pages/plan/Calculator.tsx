/** Calculadora de investimento: independente do Plano, nada é salvo no servidor (só lembra neste navegador). */
import { Calculator as CalculatorIcon, ChevronDown, Eraser } from "lucide-react";
import { useEffect, useState } from "react";
import { HowCalculated, Term } from "@/components/Help";
import { StackedBars } from "@/components/charts";
import { Button, Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";
import {
  type CalcInputs,
  clearCalc,
  convertRateText,
  loadCalc,
  monthlyRateOf,
  monthlyToAnnual,
  monthsBetween,
  monthsToReach,
  percentText,
  requiredMonthly,
  saveCalc,
  simulate,
  addMonths,
  defaultCalc,
} from "@/lib/calc";
import { formatMoney, parseMoneyInput } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { MoneyField, MonthYearField, PercentInput } from "./fields";

const monthYear = (month: string) => `${month.slice(5)}/${month.slice(0, 4)}`;
const money = (cents: number) => formatMoney(cents);

export function CalculatorCard({ month, defaultRate }: { month: string; defaultRate: number }) {
  const empty: CalcInputs = defaultCalc(month, percentText(defaultRate));
  const [inputs, setInputs] = useState<CalcInputs>(() => loadCalc(empty, month));
  const [showTable, setShowTable] = useState(false);
  useEffect(() => saveCalc(inputs), [inputs]);
  const set = <K extends keyof CalcInputs>(key: K, value: CalcInputs[K]) => setInputs((v) => ({ ...v, [key]: value }));

  const saved = inputs.saved.trim() ? parseMoneyInput(inputs.saved) : 0;
  const monthly = inputs.monthly.trim() ? parseMoneyInput(inputs.monthly) : 0;
  const goal = inputs.goal.trim() ? parseMoneyInput(inputs.goal) : null;
  const rate = monthlyRateOf(inputs.rate, inputs.unit);
  const months = inputs.targetMonth ? monthsBetween(month, inputs.targetMonth) : null;
  const problems: string[] = [];
  if (saved === null || monthly === null || (inputs.goal.trim() && (goal === null || goal <= 0))) problems.push("Confira os valores em reais.");
  if (rate === null) problems.push(inputs.unit === "ano" ? "Rentabilidade: use de 0 a 100% ao ano." : "Rentabilidade: use de 0 a 10% ao mês.");
  if (months !== null && months <= 0) problems.push("A data-alvo precisa ser depois deste mês.");
  const ready = problems.length === 0 && saved !== null && monthly !== null && rate !== null && months !== null;

  const rows = ready ? simulate(saved, monthly, rate, months, month) : [];
  const last = rows[rows.length - 1];
  const needed = ready && goal ? requiredMonthly(saved, goal, rate, months) : null;
  const reach = ready && goal ? monthsToReach(saved, goal, monthly, rate) : null;
  // no gráfico: mês a mês até 2 anos; depois, um ponto por ano (e sempre o mês final)
  const step = rows.length > 25 ? 12 : 1;
  const points = rows.filter((r) => r.index > 0 && (r.index % step === 0 || r.index === rows.length - 1));

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent-soft text-accent">
              <CalculatorIcon className="h-4 w-4" />
            </span>
            Calculadora
          </span>
        }
        subtitle="Quanto vou ter numa data, e quanto preciso guardar por mês?"
        action={
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              clearCalc();
              setInputs(empty);
              setShowTable(false);
            }}
          >
            <Eraser className="h-3.5 w-3.5" /> Limpar
          </Button>
        }
      />
      <CardBody>
        <p className="text-[12.5px] text-muted">Uma simulação à parte: não muda o seu plano e não é salva (só lembra os últimos valores neste navegador).</p>
        <div className="mt-4 grid grid-cols-1 gap-5 xl:grid-cols-12">
          <div className="grid grid-cols-1 content-start gap-3 sm:grid-cols-2 xl:col-span-5">
            <MoneyField label="Valor já guardado" value={inputs.saved} onChange={(v) => set("saved", v)} placeholder="0,00" />
            <MoneyField label="Aporte mensal" value={inputs.monthly} onChange={(v) => set("monthly", v)} placeholder="0,00" />
            <div className="text-[13px] sm:col-span-2">
              <span className="text-muted">
                <Term help={GLOSSARY.jurosCompostos}>
                  <span>Rentabilidade</span>
                </Term>
              </span>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <PercentInput label={`Rentabilidade ao ${inputs.unit === "ano" ? "ano" : "mês"}`} value={inputs.rate} onChange={(v) => set("rate", v)} width="w-28" />
                <Segmented
                  label="Unidade da rentabilidade"
                  value={inputs.unit}
                  onChange={(unit) => setInputs((v) => ({ ...v, unit, rate: convertRateText(v.rate, v.unit, unit) }))}
                  options={[
                    { value: "ano", label: "ao ano" },
                    { value: "mes", label: "ao mês" },
                  ]}
                />
              </div>
              {rate !== null ? (
                <span className="mt-1 block text-[12px] text-muted">
                  = {inputs.unit === "ano" ? `${percentText(rate, 4)}% ao mês` : `${percentText(monthlyToAnnual(rate), 2)}% ao ano`}
                </span>
              ) : null}
            </div>
            <MonthYearField label="Data-alvo" value={inputs.targetMonth} onChange={(v) => set("targetMonth", v)} from={addMonths(month, 1)} clearable />
            <MoneyField label="Valor que quero juntar (opcional)" value={inputs.goal} onChange={(v) => set("goal", v)} placeholder="opcional" />
          </div>

          <div className="xl:col-span-7">
            {months === null ? null : !ready || !last ? (
              <ul className="rounded-xl border border-dashed border-border-strong px-4 py-3.5 text-[13px] text-muted" aria-label="O que corrigir">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : (
              <div aria-live="polite">
                <p className="text-[15px] leading-relaxed">
                  Em {monthYear(inputs.targetMonth)}, você terá <strong className="tnum text-[20px] font-semibold tracking-[-0.02em]">{money(last.balance)}</strong>.
                </p>
                <p className="mt-0.5 text-[13px] text-text-2">
                  São {money(last.contributed)} do seu bolso{saved > 0 ? ` (${money(saved)} que já tinha + ${money(last.contributed - saved)} de aportes)` : ""} e{" "}
                  <strong className="text-text">{money(last.interest)} de juros</strong>.
                </p>
                {goal && needed !== null ? (
                  <ul className="mt-3 space-y-1.5 rounded-xl border border-border bg-surface-2/60 px-3.5 py-3 text-[13.5px]">
                    <li>
                      {needed === 0 ? (
                        <>Para chegar a {money(goal)} em {monthYear(inputs.targetMonth)}, o que você já tem guardado basta: nem precisa aportar.</>
                      ) : (
                        <>
                          Para chegar a {money(goal)} em {monthYear(inputs.targetMonth)}, aporte <strong className="tnum">{money(needed)}/mês</strong>.
                        </>
                      )}
                    </li>
                    <li className="text-text-2">
                      {reach === 0
                        ? `Você já tem ${money(goal)} guardados.`
                        : reach === null
                          ? `Com ${money(monthly)}/mês, você não chega a ${money(goal)} (nem em 100 anos).`
                          : `Com ${money(monthly)}/mês, você chega a ${money(goal)} em ${monthYear(addMonths(month, reach))}.`}
                    </li>
                  </ul>
                ) : null}
                {last.balance <= 0 ? (
                  <p className="mt-2 text-[12.5px] text-muted">Preencha o valor guardado ou o aporte mensal para ver o gráfico.</p>
                ) : (
                <>
                <div className="mt-4">
                  <StackedBars
                    data={points.map((r) => ({ month: r.month, contributed: r.contributed, interest: Math.max(0, r.interest) }))}
                    xKey="month"
                    height={220}
                    formatX={(m) => `${m.slice(5)}/${m.slice(2, 4)}`}
                    formatValue={money}
                    series={[
                      { key: "contributed", label: "Do seu bolso (guardado + aportes)", color: "var(--series-1)" },
                      { key: "interest", label: "Juros acumulados", color: "var(--series-2)" },
                    ]}
                  />
                </div>
                <button
                  type="button"
                  aria-expanded={showTable}
                  onClick={() => setShowTable((v) => !v)}
                  className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-muted hover:text-text"
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showTable ? "rotate-180" : ""}`} />
                  {showTable ? "Esconder a tabela mês a mês" : "Ver a tabela mês a mês"}
                </button>
                {showTable ? (
                  <div className="mt-2 max-h-[320px] overflow-auto rounded-xl border border-border">
                    <table className="data-table w-full text-[13px]">
                      <thead className="sticky top-0 bg-surface-2 text-left text-muted">
                        <tr>
                          <th className="px-3 py-2 font-medium">Mês</th>
                          <th className="px-3 py-2 text-right font-medium">Do seu bolso</th>
                          <th className="px-3 py-2 text-right font-medium">Juros</th>
                          <th className="px-3 py-2 text-right font-medium">Saldo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.index} className="border-t border-border">
                            <td className="px-3 py-1.5 text-text-2">{r.index === 0 ? "hoje" : monthYear(r.month)}</td>
                            <td className="px-3 py-1.5 text-right tnum text-text-2">{money(r.contributed)}</td>
                            <td className="px-3 py-1.5 text-right tnum text-text-2">{money(r.interest)}</td>
                            <td className="px-3 py-1.5 text-right tnum font-medium">{money(r.balance)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                </>
                )}
              </div>
            )}
            <HowCalculated>
              <p>
                Juros compostos, mês a mês: o saldo de cada mês rende a taxa mensal e depois entra o aporte (no fim do mês, a partir do mês que vem).
                Taxa ao mês = (1 + taxa ao ano)^(1/12) − 1; taxa ao ano = (1 + taxa ao mês)^12 − 1.
              </p>
              <p className="mt-1.5">Aporte necessário = (valor desejado − guardado corrigido até a data) × taxa ÷ ((1 + taxa)^meses − 1), arredondado para cima.</p>
              <p className="mt-1.5 text-muted">A rentabilidade é uma suposição sua (não é garantia) e não desconta inflação nem imposto: use uma taxa já líquida se quiser.</p>
            </HowCalculated>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
