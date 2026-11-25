/**
 * "Ajustar o plano": todos os formulários (meta de aporte e extra da 5ª segunda, Reserva, alvos da carteira,
 * Núcleo / Manter / Satélite, meta de rentabilidade). Fica recolhido: a tela principal não mostra formulários.
 */
import { AlertTriangle, Save } from "lucide-react";
import { useState } from "react";
import { Term } from "@/components/Help";
import { Button, Input, Segmented } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { Bucket, CoreWeights, Plan, StockRole } from "@/lib/api";
import { parsePercent, percentText } from "@/lib/calc";
import { formatMoney, formatMoneyInput, formatPercent, parseMoneyInput } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { percentState } from "@/lib/percent";
import { useSaveSetting } from "@/lib/planActions";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";
import { FormCard, MoneyField, MonthPicker, PercentInput, PercentSum, SettingHistory } from "./fields";

const BUCKETS: Bucket[] = ["renda_fixa", "etf_global", "etf_brasil", "acoes_nucleo", "fiis", "satelite"];
const BUCKET_NOTES: Partial<Record<Bucket, string>> = { fiis: "sem novos aportes", satelite: "teto" };

// ------------------------------------------------------------------ meta de aporte e pagamento extra do salário

export function MonthlyTargetForm({ plan }: { plan: Plan }) {
  const setting = plan.settings.aporte_mensal;
  const cushion = plan.settings.colchao;
  const [value, setValue] = useState(formatMoneyInput(setting.value.cents));
  const [extra, setExtra] = useState(setting.value.extra_paycheck);
  const [cushionValue, setCushionValue] = useState(formatMoneyInput(cushion.value.cents));
  const [month, setMonth] = useState(plan.month);
  const { save, pending } = useSaveSetting();
  const cents = parseMoneyInput(value);
  const cushionCents = parseMoneyInput(cushionValue);
  const targetChanged = cents !== setting.value.cents || extra !== setting.value.extra_paycheck;
  const changed = targetChanged || cushionCents !== cushion.value.cents;
  const paycheck = plan.contribution.extra.paycheck;
  return (
    <FormCard
      title="Meta de aporte mensal"
      question="Quanto você quer investir por mês?"
      footer={
        <>
          <MonthPicker value={month} onChange={setMonth} current={plan.month} />
          <Button
            variant="primary"
            size="sm"
            disabled={!changed || cents === null || cushionCents === null || pending}
            onClick={() => {
              if (cents !== null && targetChanged) save("aporte_mensal", month, { cents, extra_paycheck: extra }, "Meta de aporte");
              if (cushionCents !== null && cushionCents !== cushion.value.cents) save("colchao", month, { cents: cushionCents }, "Colchão mínimo");
            }}
          >
            <Save className="h-3.5 w-3.5" /> Salvar
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <MoneyField label="Meta base por mês" value={value} onChange={setValue} />
        <MoneyField label="Colchão mínimo na conta" value={cushionValue} onChange={setCushionValue} hint="Fica na conta; não conta como disponível." />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-2.5 text-[13px]">
        <span>
          <Term help={GLOSSARY.pagamentoExtra}>
            <span>Pagamento extra do salário</span>
          </Term>
          <span className="block text-[12px] text-muted">
            {paycheck
              ? `Nos meses com um pagamento a mais, +${formatMoney(paycheck)} na meta.`
              : "Vale para salário semanal ou quinzenal reconhecido."}
          </span>
        </span>
        <Switch checked={extra} onCheckedChange={setExtra} label="Pagamento extra do salário" />
      </div>
      <SettingHistory
        history={setting.history.map((h) => ({ month: h.effective_month, text: `${formatMoney(h.value.cents)}${h.value.extra_paycheck ? " + pagamento extra" : ""}` }))}
      />
    </FormCard>
  );
}

// ------------------------------------------------------------------ Reserva: valor e onde fica

const ORDER_OPTIONS = [
  { value: "CDB/RDB,Tesouro", label: "CDB/RDB, depois Tesouro Selic" },
  { value: "Tesouro,CDB/RDB", label: "Tesouro Selic, depois CDB/RDB" },
  { value: "CDB/RDB", label: "Só CDB/RDB" },
  { value: "Tesouro", label: "Só Tesouro Selic" },
];

export function ReserveForm({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const r = plan.reserve;
  const setting = plan.settings.reserva;
  const [value, setValue] = useState(formatMoneyInput(r.target));
  const [order, setOrder] = useState(r.order.join(","));
  const { save, pending } = useSaveSetting();
  const cents = value.trim() ? parseMoneyInput(value) : null;
  const changed = cents !== r.target || order !== r.order.join(",");
  return (
    <FormCard
      title={
        <Term help={GLOSSARY.reserva}>
          <span>Reserva de emergência</span>
        </Term>
      }
      question="Qual o valor da Reserva e onde ela fica?"
      footer={
        <>
          <span className="text-[12.5px] text-muted">Vale a partir deste mês.</span>
          <Button
            variant="primary"
            size="sm"
            disabled={!changed || (value.trim() !== "" && cents === null) || pending}
            onClick={() => save("reserva", plan.month, { cents, order: order.split(",") }, "Reserva de emergência")}
          >
            <Save className="h-3.5 w-3.5" /> Salvar
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <MoneyField label="Valor da reserva" value={value} onChange={setValue} placeholder="ex.: 10.000,00" />
        <label className="block text-[13px]">
          <span className="text-muted">Onde fica</span>
          <Select size="md" label="Composição da reserva" value={order} onValueChange={setOrder} options={ORDER_OPTIONS} className="mt-1 w-full" />
        </label>
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-text-2">
        É um valor fixo que você escolhe. A renda fixa entra nela nessa ordem até completar o valor; o que passar é Patrimônio.
        {r.essential_average ? ` Seus gastos essenciais são de ${formatMoney(r.essential_average, { hidden })}/mês (média dos últimos ${r.essential_months.length} meses fechados).` : ""}
      </p>
      <SettingHistory
        history={setting.history.map((h) => ({ month: h.effective_month, text: `${h.value.cents === null ? "sem valor" : formatMoney(h.value.cents)} · ${h.value.order.join(", depois ")}` }))}
      />
    </FormCard>
  );
}

// ------------------------------------------------------------------ alvos da carteira

export function PatrimonyTargetForm({ plan }: { plan: Plan }) {
  const setting = plan.settings.alvo_patrimonio;
  const labels = Object.fromEntries(plan.patrimony.buckets.map((b) => [b.bucket, b.label])) as Record<Bucket, string>;
  const initial = () => Object.fromEntries(BUCKETS.map((b) => [b, setting.value.classes[b] === null ? "" : String(setting.value.classes[b]).replace(".", ",")])) as Record<Bucket, string>;
  const [values, setValues] = useState<Record<Bucket, string>>(initial);
  const [global, setGlobal] = useState(setting.value.etf_global ?? "");
  const [brasil, setBrasil] = useState(setting.value.etf_brasil ?? "");
  const [month, setMonth] = useState(plan.month);
  const { save, pending } = useSaveSetting();
  const state = percentState(BUCKETS.map((b) => values[b]));
  const tickerOk = (t: string) => t.trim() === "" || /^[A-Z0-9]{4,12}$/.test(t.trim().toUpperCase());
  const valid = state.ok && tickerOk(global) && tickerOk(brasil);
  const start = initial();
  const changed = BUCKETS.some((b) => values[b] !== start[b]) || global !== (setting.value.etf_global ?? "") || brasil !== (setting.value.etf_brasil ?? "");
  return (
    <FormCard
      title="Alvos da carteira"
      question="Que porcentagem do Patrimônio cada classe deve ter?"
      footer={
        <>
          <MonthPicker value={month} onChange={setMonth} current={plan.month} />
          <div className="flex items-center gap-3">
            <PercentSum sum={state.sum} ok={state.ok} empty={state.empty} />
            <Button
              variant="primary"
              size="sm"
              disabled={!valid || !changed || pending}
              onClick={() =>
                save(
                  "alvo_patrimonio",
                  month,
                  {
                    classes: Object.fromEntries(BUCKETS.map((b, i) => [b, state.nums[i] ?? null])) as Record<Bucket, number | null>,
                    etf_global: global.trim().toUpperCase() || null,
                    etf_brasil: brasil.trim().toUpperCase() || null,
                  },
                  "Alvos da carteira",
                )
              }
            >
              <Save className="h-3.5 w-3.5" /> Salvar
            </Button>
          </div>
        </>
      }
    >
      <ul className="space-y-2.5">
        {BUCKETS.map((b) => (
          <li key={b} className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
            <span>
              {labels[b]}
              {BUCKET_NOTES[b] ? <span className="ml-1 text-[12px] text-muted">({BUCKET_NOTES[b]})</span> : null}
            </span>
            <span className="flex items-center gap-2">
              {b === "etf_global" || b === "etf_brasil" ? (
                <Input
                  aria-label={`Código do ${labels[b]} para comprar`}
                  value={b === "etf_global" ? global : brasil}
                  onChange={(e) => (b === "etf_global" ? setGlobal : setBrasil)(e.target.value.toUpperCase())}
                  placeholder="código"
                  className={cn("h-9 w-24 uppercase", !tickerOk(b === "etf_global" ? global : brasil) && "border-negative")}
                />
              ) : null}
              <PercentInput label={`Percentual-alvo de ${labels[b]}`} value={values[b]} onChange={(v) => setValues((s) => ({ ...s, [b]: v }))} />
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] text-muted">O código de cada ETF é o que a lista do mês manda comprar. As ações mantidas não têm alvo: só acompanham.</p>
      <SettingHistory history={setting.history.map((h) => ({ month: h.effective_month, text: BUCKETS.map((b) => `${h.value.classes[b] ?? "—"}`).join(" / ") }))} />
    </FormCard>
  );
}

// ------------------------------------------------------------------ Núcleo / Manter / Satélite e pesos do núcleo

const ROLE_HELP: Record<StockRole, string> = {
  nucleo: "Núcleo: empresas para muitos anos; recebem aporte dentro do alvo do núcleo.",
  manter: "Manter: só acompanha; fica na carteira sem aporte e sem alvo (como os FIIs).",
  satelite: "Satélite: oportunidades; têm um teto e nunca recebem aporte.",
};
const WEIGHT_OPTIONS: { value: CoreWeights; label: string }[] = [
  { value: "iguais", label: "Iguais" },
  { value: "atual", label: "Manter a proporção atual" },
  { value: "personalizado", label: "Personalizados" },
];

export function RolesForm({ plan }: { plan: Plan }) {
  const [hidden] = useHiddenValues();
  const setting = plan.settings.nucleo.value;
  const rows = plan.holdings.filter((h) => h.role !== null && h.ticker);
  const tickers = [...new Set(rows.map((h) => h.ticker as string))];
  const [roles, setRoles] = useState<Record<string, StockRole>>(() => Object.fromEntries(rows.map((h) => [h.ticker as string, h.role as StockRole])));
  const [mode, setMode] = useState<CoreWeights>(setting.weights);
  const [custom, setCustom] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(setting.custom).map(([t, p]) => [t, String(p).replace(".", ",")])));
  const { save, pending } = useSaveSetting();
  if (!rows.length) return null;

  const core = tickers.filter((t) => roles[t] === "nucleo");
  // marcações de ações que não estão mais na carteira continuam valendo
  const absent = (list: string[]) => list.filter((t) => !tickers.includes(t));
  const corePct = plan.settings.alvo_patrimonio.value.classes.acoes_nucleo;
  const weights = percentState(core.map((t) => custom[t] ?? ""));
  const customOk = mode !== "personalizado" || (weights.ok && weights.nums.every((n) => n !== null && n > 0));
  const value = {
    tickers: [...core, ...absent(setting.tickers)].sort(),
    satellite: [...tickers.filter((t) => roles[t] === "satelite"), ...absent(setting.satellite)].sort(),
    weights: mode,
    custom: mode === "personalizado" ? Object.fromEntries(core.map((t, i) => [t, weights.nums[i] ?? 0])) : {},
  };
  const changed = JSON.stringify(value) !== JSON.stringify({ ...setting, tickers: [...setting.tickers].sort(), satellite: [...setting.satellite].sort() });
  const each = corePct !== null && core.length ? corePct / core.length : null;
  return (
    <FormCard
      title="Núcleo, Manter ou Satélite"
      question="Qual o papel de cada ação ou BDR na carteira?"
      footer={
        <>
          <span className="text-[12.5px] text-muted">Vale a partir deste mês.</span>
          <Button variant="primary" size="sm" disabled={!changed || !customOk || pending} onClick={() => save("nucleo", plan.month, value, "Papel das ações")}>
            <Save className="h-3.5 w-3.5" /> Salvar
          </Button>
        </>
      }
    >
      <ul className="space-y-0.5 text-[12.5px] leading-relaxed text-text-2">
        {(Object.keys(ROLE_HELP) as StockRole[]).map((r) => (
          <li key={r}>{ROLE_HELP[r]}</li>
        ))}
      </ul>
      <ul className="mt-3 divide-y divide-border">
        {rows.map((h) => (
          <li key={h.investment_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 py-2 text-[13px]">
            <span className="min-w-0">
              <span className="block font-medium">{h.ticker}</span>
              <span className="block text-[12px] text-muted">
                {h.class} · {formatMoney(h.value, { hidden })}
              </span>
            </span>
            <Segmented
              label={`Papel de ${h.ticker}`}
              value={roles[h.ticker as string] ?? "manter"}
              onChange={(v) => setRoles((s) => ({ ...s, [h.ticker as string]: v }))}
              options={[
                { value: "nucleo", label: "Núcleo" },
                { value: "manter", label: "Manter" },
                { value: "satelite", label: "Satélite" },
              ]}
            />
          </li>
        ))}
      </ul>
      <p className={cn("mt-3 flex gap-2 text-[12.5px] leading-relaxed", core.length > 5 ? "text-warning" : "text-muted")}>
        {core.length > 5 ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : null}
        <span>
          Sugestão: de 3 a 5 empresas no núcleo.
          {core.length > 5 && each !== null
            ? ` Com ${core.length} empresas, cada uma fica com ${each.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% da carteira em pesos iguais: os aportes ficam muito divididos.`
            : each !== null && core.length
              ? ` Com ${core.length}, cada uma fica com ${each.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% da carteira em pesos iguais.`
              : ""}
        </span>
      </p>

      {core.length ? (
        <div className="mt-3 rounded-xl border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
            <span className="font-medium">Pesos dentro do núcleo</span>
            <Segmented label="Pesos dentro do núcleo" value={mode} onChange={setMode} options={WEIGHT_OPTIONS} />
          </div>
          <p className="mt-1.5 text-[12px] text-muted">
            {mode === "iguais"
              ? "Cada empresa tem o mesmo peso: a que está mais abaixo recebe primeiro."
              : mode === "atual"
                ? "Cada empresa recebe na proporção do que já tem hoje: a divisão atual é mantida."
                : "Você define o peso de cada empresa; a soma precisa dar 100%."}
          </p>
          {mode === "personalizado" ? (
            <>
              <ul className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
                {core.map((t) => (
                  <li key={t} className="flex items-center justify-between gap-2 text-[13px]">
                    {t}
                    <PercentInput label={`Peso de ${t} no núcleo`} value={custom[t] ?? ""} onChange={(v) => setCustom((s) => ({ ...s, [t]: v }))} />
                  </li>
                ))}
              </ul>
              <div className="mt-2 text-right">
                <PercentSum sum={weights.sum} ok={weights.ok} empty={weights.empty} />
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </FormCard>
  );
}

// ------------------------------------------------------------------ meta de rentabilidade (linha dos gráficos)

export function ReturnsForm({ plan }: { plan: Plan }) {
  const setting = plan.settings.rentabilidade;
  const [aspirational, setAspirational] = useState(percentText(setting.value.aspirational));
  const { save, pending } = useSaveSetting();
  const parsed = parsePercent(aspirational, 50);
  return (
    <FormCard
      title={
        <Term help={GLOSSARY.metaAspiracional}>
          <span>Meta de rentabilidade</span>
        </Term>
      }
      question="Quanto você gostaria que a carteira rendesse por ano?"
      footer={
        <>
          <span className="text-[12.5px] text-muted">Vale a partir deste mês.</span>
          <Button
            variant="primary"
            size="sm"
            disabled={parsed === null || parsed === setting.value.aspirational || pending}
            onClick={() => parsed !== null && save("rentabilidade", plan.month, { assumed: setting.value.assumed, aspirational: parsed }, "Meta de rentabilidade")}
          >
            <Save className="h-3.5 w-3.5" /> Salvar
          </Button>
        </>
      }
    >
      <div className="flex items-center justify-between gap-3 text-[13.5px]">
        <span>
          Meta ao ano
          <span className="block text-[12px] text-muted">Aparece como linha nos gráficos de Investimentos.</span>
        </span>
        <PercentInput label="Meta de rentabilidade ao ano" value={aspirational} onChange={setAspirational} suffix="% a.a." width="w-28" />
      </div>
      <SettingHistory history={setting.history.map((h) => ({ month: h.effective_month, text: `${formatPercent(h.value.aspirational)} ao ano` }))} />
    </FormCard>
  );
}
