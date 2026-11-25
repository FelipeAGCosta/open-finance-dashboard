/** Campos e molduras dos formulários do Plano: dinheiro, percentual, mês/ano, seção recolhida, histórico. */
import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Card, CardBody, CardHeader, Input } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { addMonths } from "@/lib/calc";
import { formatMonth, parseMoneyInput } from "@/lib/format";
import { cn } from "@/lib/utils";

export function MonthPicker({ value, onChange, current }: { value: string; onChange: (month: string) => void; current: string }) {
  const options = Array.from({ length: 25 }, (_, i) => addMonths(current, i - 12)).map((m) => ({ value: m, label: formatMonth(m, "title") }));
  return (
    <label className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
      Vale a partir de
      <Select size="sm" label="Vale a partir de" value={value} onValueChange={onChange} options={options} className="w-[170px]" />
    </label>
  );
}

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** Mês e ano em dois seletores curtos (12 meses, 40 anos): `from` é o primeiro mês aceito. */
export function MonthYearField({ label, value, onChange, from, clearable = false }: { label: string; value: string; onChange: (month: string) => void; from: string; clearable?: boolean }) {
  const firstYear = Number(from.slice(0, 4));
  const [year, month] = value ? [value.slice(0, 4), value.slice(5)] : ["", ""];
  // escolher só um dos dois já vale: o outro assume o primeiro mês/ano possível
  const emit = (y: string, m: string) => {
    if (!y && !m) return onChange("");
    const picked = `${y || String(firstYear)}-${m || from.slice(5)}`;
    onChange(picked < from ? from : picked);
  };
  return (
    <div className="text-[13px]">
      <span className="flex items-center justify-between gap-2">
        <span className="text-muted">{label}</span>
        {clearable && value ? (
          <button type="button" onClick={() => onChange("")} className="text-[12px] text-muted underline-offset-2 hover:text-text hover:underline">
            limpar data
          </button>
        ) : null}
      </span>
      <div className="mt-1 grid grid-cols-[1fr_96px] gap-2">
        <Select
          size="md"
          label={`${label}: mês`}
          placeholder="mês"
          value={month}
          onValueChange={(m) => emit(year, m)}
          options={MONTH_NAMES.map((name, i) => ({ value: String(i + 1).padStart(2, "0"), label: name }))}
        />
        <Select
          size="md"
          label={`${label}: ano`}
          placeholder="ano"
          value={year}
          onValueChange={(y) => emit(y, month)}
          options={Array.from({ length: 40 }, (_, i) => String(firstYear + i)).map((y) => ({ value: y, label: y }))}
        />
      </div>
    </div>
  );
}

export function FormCard({ title, question, children, footer }: { title: ReactNode; question: string; children: ReactNode; footer: ReactNode }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader title={title} subtitle={question} />
      <CardBody className="flex flex-1 flex-col">
        <div className="flex-1">{children}</div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">{footer}</div>
      </CardBody>
    </Card>
  );
}

/** Seção recolhida por padrão; o conteúdo só é montado quando aberta (nenhum formulário escondido na página). */
export function Collapsible({ title, hint, children, id }: { title: string; hint: string; children: ReactNode; id: string }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-labelledby={`${id}-title`} className="rounded-[var(--radius-card)] border border-border bg-surface">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span>
          <span id={`${id}-title`} className="block text-[15px] font-semibold tracking-[-0.01em]">
            {title}
          </span>
          <span className="block text-[12.5px] text-muted">{hint}</span>
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")} />
      </button>
      {open ? (
        <div id={`${id}-body`} className="border-t border-border p-5">
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function MoneyField({ label, value, onChange, placeholder, hint }: { label: ReactNode; value: string; onChange: (v: string) => void; placeholder?: string; hint?: ReactNode }) {
  const invalid = value.trim() !== "" && parseMoneyInput(value) === null;
  return (
    <label className="block text-[13px]">
      <span className="text-muted">{label}</span>
      <div className="relative mt-1">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[13px] text-muted">R$</span>
        <Input inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-invalid={invalid} className={cn("pl-9 tnum", invalid && "border-negative")} />
      </div>
      {invalid ? <span className="mt-1 block text-[12px] text-negative">Use só números, como 1.000,00.</span> : hint ? <span className="mt-1 block text-[12px] text-muted">{hint}</span> : null}
    </label>
  );
}

export function PercentInput({ value, onChange, label, suffix = "%", width = "w-24" }: { value: string; onChange: (v: string) => void; label: string; suffix?: string; width?: string }) {
  const parsed = value.trim() ? Number(value.replace(",", ".")) : null;
  const invalid = parsed !== null && (Number.isNaN(parsed) || parsed < 0 || parsed > 100);
  return (
    <div className={cn("relative", width)}>
      <Input
        inputMode="decimal"
        aria-label={label}
        aria-invalid={invalid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn("text-right tnum", suffix.length > 1 ? "pr-12" : "pr-7", invalid && "border-negative")}
        placeholder="—"
      />
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[13px] text-muted">{suffix}</span>
    </div>
  );
}

export function PercentSum({ sum, ok, empty }: { sum: number; ok: boolean; empty: boolean }) {
  if (empty) return <span className="text-[12.5px] text-muted">Vazio: preencha quando quiser.</span>;
  return (
    <span className={cn("text-[12.5px] font-medium tnum", ok ? "text-positive" : "text-warning")}>
      Soma: {sum.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% {ok ? "✓" : "(precisa dar 100%)"}
    </span>
  );
}

/** Histórico da meta, recolhido: o servidor já manda só as mudanças reais (sem linhas repetidas). */
export function SettingHistory({ history }: { history: { month: string; text: string }[] }) {
  if (history.length < 2) return null;
  return (
    <details className="group mt-3 text-[12px] text-muted">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium hover:text-text">
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" /> Histórico ({history.length} mudanças)
      </summary>
      <ul className="mt-1.5 space-y-0.5 pl-[18px]">
        {[...history].reverse().map((h) => (
          <li key={h.month}>
            desde {formatMonth(h.month, "short")}: {h.text}
          </li>
        ))}
      </ul>
    </details>
  );
}
