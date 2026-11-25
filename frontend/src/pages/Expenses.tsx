import { ArrowLeftRight, Check, CreditCard, HandCoins, Landmark, Loader2, Search, SearchX, Sparkles, X, Zap } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { memo, useDeferredValue, useMemo, useState } from "react";
import { AnimatedMoney, Money } from "@/components/Money";
import { ChartFrame, HorizontalBars, SegmentedMeter } from "@/components/charts";
import { Dialog, ScopeDialog, type Scope } from "@/components/Dialog";
import { HowCalculated, Term } from "@/components/Help";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/states";
import { FlowIcon } from "@/components/Stat";
import { Badge, Button, Card, CardBody, CardHeader, Input } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { ClassifyBody, Expenses, Meta, MovementKind, Transaction } from "@/lib/api";
import { OTHER, categoryColorResolver } from "@/lib/colors";
import { formatDate, formatMoney, formatMonth, formatPercent } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { KIND_CHOICES, MOVEMENT_LABELS, NEUTRAL_TYPES, RULE_LABELS } from "@/lib/labels";
import { useHiddenValues } from "@/lib/preferences";
import { useClassifyMutation, useExpenses, useMeta, useUndo } from "@/lib/queries";
import { navigate } from "@/lib/router";
import { showToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

type FixedFilter = "todos" | "fixos" | "variaveis" | "extraordinarios";

/** Mudança pedida na linha, aguardando a escolha do escopo. */
interface PendingChange {
  tx: Transaction;
  title: string;
  body: Omit<ClassifyBody, "scope">;
  what: string;
}

function rowTitle(tx: Transaction): string {
  // "Transferência enviada pelo Pix|FULANO" -> "FULANO"
  const parts = (tx.description ?? "").split("|");
  return (parts.length > 1 ? parts[parts.length - 1] : parts[0]) || tx.counterparty || "Transação";
}

export function ExpensesPage({ month }: { month: string }) {
  const meta = useMeta();
  const query = useExpenses(month);
  const mutation = useClassifyMutation();
  const undo = useUndo();
  const [hidden] = useHiddenValues();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [category, setCategory] = useState("todas");
  const [type, setType] = useState("despesa");
  const [account, setAccount] = useState("todas");
  const [fixed, setFixed] = useState<FixedFilter>("todos");
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [kindFor, setKindFor] = useState<Transaction | null>(null);
  const colorOf = categoryColorResolver(meta.data);

  const transactions = query.data?.transactions;
  const filtered = useMemo(() => {
    if (!transactions) return [];
    const needle = deferredSearch.trim().toLocaleLowerCase("pt-BR");
    return transactions.filter((t) => {
      if (type === "entradas" ? t.amount <= 0 : type !== "todos" && t.movement_type !== type) return false;
      if (category !== "todas" && (t.category ?? "") !== category) return false;
      if (account !== "todas" && t.account !== account) return false;
      if (fixed === "fixos" && !t.is_fixed) return false;
      if (fixed === "variaveis" && t.is_fixed) return false;
      if (fixed === "extraordinarios" && !t.extraordinary) return false;
      if (!needle) return true;
      return [t.description, t.counterparty, t.category].some((v) => v?.toLocaleLowerCase("pt-BR").includes(needle));
    });
  }, [transactions, deferredSearch, type, category, account, fixed]);

  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton cards={3} />;
  const data = query.data;
  const format = (v: number) => formatMoney(v, { hidden });
  const types = Array.from(new Set(data.transactions.map((t) => t.movement_type)));
  const filtersActive = category !== "todas" || type !== "despesa" || account !== "todas" || fixed !== "todos" || search !== "";

  const apply = (change: PendingChange, scope: Scope) => {
    setPending(null);
    mutation.mutate(
      { id: change.tx.id, body: { scope, ...change.body } },
      {
        onSuccess: (result) =>
          showToast({
            title: change.what,
            detail:
              scope === "one"
                ? "Só nesta transação."
                : `Regra pessoal para ${change.tx.counterparty ?? "a contraparte"}: ${result.affected} transação(ões), passadas e futuras.`,
            onUndo: () => undo(result.undo),
          }),
        onError: (error) => showToast({ title: "Não foi possível salvar", detail: error.message, tone: "error" }),
      },
    );
  };

  return (
    <div className={cn("space-y-5 transition-opacity duration-300", query.isPlaceholderData && "opacity-60")}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="p-5">
          <p className="flex items-center gap-2 text-[13px] font-medium text-muted">
            <FlowIcon direction="out" /> Despesas do mês
          </p>
          <AnimatedMoney cents={data.total} className="mt-2.5 block text-[28px] font-semibold tracking-[-0.03em]" />
          <p className="mt-2 text-[12.5px] text-muted">
            {data.count} gastos em {formatMonth(month)} · estornos e reembolsos já descontados
          </p>
          <EverydaySplit data={data} />
          <NeutralLine data={data} />
        </Card>
        <Card className="p-5">
          <p className="mb-4 flex items-center justify-between gap-2 text-[13px] font-medium text-muted">
            <Term help={GLOSSARY.fixo}>
              <span>Fixo × variável</span>
            </Term>
            <button type="button" onClick={() => navigate("fixos")} className="text-[12px] font-normal text-muted underline-offset-2 hover:text-text hover:underline">
              ver na tela Fixos
            </button>
          </p>
          <SegmentedMeter
            formatValue={format}
            segments={[
              { label: "Fixo", value: data.fixed.fixed, color: "var(--series-1)" },
              { label: "Variável", value: data.fixed.variable, color: "var(--series-4)" },
            ]}
          />
          {data.fixed.pending > 0 ? <p className="mt-3 text-[12px] text-muted">Ainda vão cair {format(data.fixed.pending)} de fixos neste mês.</p> : null}
        </Card>
        <Card className="p-5">
          <p className="mb-4 text-[13px] font-medium text-muted">Essencial × não essencial</p>
          <SegmentedMeter
            formatValue={format}
            segments={[
              { label: "Essencial", value: data.essential.essential, color: "var(--series-3)" },
              { label: "Não essencial", value: data.essential.non_essential, color: "var(--series-5)" },
              ...(data.essential.no_flag > 0 ? [{ label: "Sem classificação", value: data.essential.no_flag, color: OTHER }] : []),
            ]}
          />
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(300px,340px)_1fr]">
        <div className="space-y-5">
          <Card className="h-fit">
            <CardHeader title="Por categoria" subtitle="Onde o dinheiro foi gasto? Clique para filtrar a lista." />
            <CardBody className="pt-2">
              {data.by_category.length ? (
                <ChartFrame
                  chart={
                    <HorizontalBars
                      data={data.by_category.filter((c) => c.cents > 0).map((c) => ({ name: c.name, value: c.cents, count: c.count, color: colorOf(c.name) }))}
                      formatValue={format}
                      selected={category === "todas" ? null : category}
                      onSelect={(name) => {
                        setType("despesa");
                        setCategory((current) => (current === name ? "todas" : name));
                      }}
                    />
                  }
                  table={{
                    headers: ["Categoria", "Gastos", "Valor"],
                    rows: data.by_category.map((c) => [c.name, String(c.count), format(c.cents)]),
                  }}
                />
              ) : (
                <EmptyState icon={<Sparkles className="h-5 w-5" />} title="Nenhum gasto neste mês" />
              )}
            </CardBody>
          </Card>
          <LoansCard data={data} />
        </div>

        <Card className="min-w-0">
          <CardHeader
            title="Transações"
            subtitle={`${filtered.length} de ${data.transactions.length} no mês · mude categoria, fixo ou tipo direto na linha`}
            action={
              filtersActive ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setSearch("");
                    setCategory("todas");
                    setType("despesa");
                    setAccount("todas");
                    setFixed("todos");
                  }}
                >
                  <X className="h-3.5 w-3.5" /> Limpar filtros
                </Button>
              ) : null
            }
          />
          <div className="flex flex-wrap gap-2 px-6 pt-4">
            <div className="relative min-w-[200px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar descrição ou contraparte…" className="pl-9" aria-label="Buscar" />
            </div>
            <Select
              label="Categoria"
              value={category}
              onValueChange={setCategory}
              className="w-[190px]"
              options={[{ value: "todas", label: "Todas as categorias" }, ...(meta.data?.categories ?? []).map((c) => ({ value: c.name, label: c.name }))]}
            />
            <Select
              label="Tipo"
              value={type}
              onValueChange={setType}
              className="w-[190px]"
              options={[
                { value: "todos", label: "Todos os tipos" },
                { value: "entradas", label: "Todas as entradas" },
                ...types.map((t) => ({ value: t, label: MOVEMENT_LABELS[t] ?? t })),
              ]}
            />
            <Select
              label="Conta"
              value={account}
              onValueChange={setAccount}
              className="w-[140px]"
              options={[
                { value: "todas", label: "Conta e cartão" },
                { value: "conta", label: "Conta" },
                { value: "cartao", label: "Cartão" },
              ]}
            />
            <Select
              label="Fixo"
              value={fixed}
              onValueChange={(v) => setFixed(v as FixedFilter)}
              className="w-[150px]"
              options={[
                { value: "todos", label: "Fixos e variáveis" },
                { value: "fixos", label: "Só fixos" },
                { value: "variaveis", label: "Só variáveis" },
                { value: "extraordinarios", label: "Só extraordinários" },
              ]}
            />
          </div>
          <CardBody className="px-3 pt-3 sm:px-4">
            {filtered.length === 0 ? (
              <EmptyState icon={<SearchX className="h-5 w-5" />} title="Nada encontrado">
                Ajuste a busca ou os filtros para ver mais transações.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-border">
                <AnimatePresence initial={false}>
                  {filtered.map((t) => (
                    <TransactionRow
                      key={t.id}
                      tx={t}
                      meta={meta.data}
                      color={t.category ? colorOf(t.category) : OTHER}
                      busy={mutation.isPending && mutation.variables?.id === t.id}
                      saved={mutation.isSuccess && mutation.variables?.id === t.id}
                      onCategory={(value) =>
                        setPending({ tx: t, title: "Mudar a categoria", body: { category: value }, what: `Categoria: ${value}` })
                      }
                      onFixed={(value) =>
                        setPending({ tx: t, title: value ? "Marcar como fixo" : "Marcar como variável", body: { fixed: value }, what: value ? "Marcado como fixo" : "Marcado como variável" })
                      }
                      onKind={() => setKindFor(t)}
                      onExtraordinary={(value) =>
                        setPending({
                          tx: t,
                          title: value ? "Marcar como extraordinário" : "Voltar para o dia a dia",
                          body: { extraordinary: value },
                          what: value ? "Marcado como extraordinário" : "De volta ao dia a dia",
                        })
                      }
                    />
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <ScopeDialog
        open={pending !== null}
        title={pending?.title ?? ""}
        change={pending ? <ChangeSummary change={pending} /> : null}
        counterparty={pending?.tx.counterparty ?? null}
        allowCounterparty={Boolean(pending?.tx.has_counterparty)}
        counterpartyHint={
          pending && "fixed" in pending.body
            ? "Vira um gasto fixo: aparece na tela Fixos e entra no total mensal."
            : pending && "extraordinary" in pending.body
              ? "Cria uma regra pessoal: os gastos desta contraparte, passados e futuros, ficam fora do dia a dia."
              : "Cria uma regra pessoal: vale para as passadas e para as que vierem."
        }
        onChoose={(scope) => pending && apply(pending, scope)}
        onClose={() => setPending(null)}
      />
      <KindDialog
        tx={kindFor}
        meta={meta.data}
        onClose={() => setKindFor(null)}
        onApply={(tx, body, scope) => {
          setKindFor(null);
          apply({ tx, title: "Mudar o tipo", body, what: `Tipo: ${KIND_CHOICES[body.kind as MovementKind].label}` }, scope);
        }}
      />
    </div>
  );
}

function ChangeSummary({ change }: { change: PendingChange }) {
  const [hidden] = useHiddenValues();
  return (
    <span>
      {rowTitle(change.tx)} · {formatDate(change.tx.date, "day")} · {formatMoney(change.tx.amount, { signed: true, hidden })}
      {!change.tx.has_counterparty ? <span className="mt-1 block">Sem contraparte identificada: só dá para mudar esta.</span> : null}
    </span>
  );
}

/** C2/C3: total sempre visível; dia a dia × extraordinários; sobra e poupança com e sem; pagos com resgates. */
function EverydaySplit({ data }: { data: Expenses }) {
  const [hidden] = useHiddenValues();
  const format = (v: number, signed = false) => formatMoney(v, { hidden, signed });
  const extra = data.extraordinary.cents;
  return (
    <div className="mt-4 space-y-2 border-t border-border pt-3 text-[12.5px]">
      {extra > 0 ? (
        <SegmentedMeter
          formatValue={(v) => format(v)}
          segments={[
            { label: "Dia a dia", value: data.everyday, color: "var(--series-4)" },
            { label: "Extraordinários", value: extra, color: "var(--series-6)" },
          ]}
        />
      ) : (
        <p className="text-muted">
          Nenhum gasto{" "}
          <Term help={GLOSSARY.extraordinario}>
            <span>extraordinário</span>
          </Term>{" "}
          neste mês. Marque na lista com <Zap className="inline h-3 w-3" />.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
        <dt className="text-muted">Sobra do mês</dt>
        <dd className={cn("text-right font-medium tnum", data.result < 0 && "text-negative")}>{format(data.result, true)}</dd>
        {extra > 0 ? (
          <>
            <dt className="text-muted">sem extraordinários</dt>
            <dd className={cn("text-right tnum", data.result_everyday < 0 && "text-negative")}>{format(data.result_everyday, true)}</dd>
          </>
        ) : null}
        <dt className="text-muted">Taxa de poupança</dt>
        <dd className="text-right tnum">
          {formatPercent(data.savings_rate)}
          {extra > 0 ? <span className="text-muted"> · sem: {formatPercent(data.savings_rate_everyday)}</span> : null}
        </dd>
        {data.paid_with_redemptions > 0 ? (
          <>
            <dt className="text-muted">
              <Term help={GLOSSARY.pagosComResgates}>
                <span>Pagos com resgates</span>
              </Term>
            </dt>
            <dd className="text-right font-medium text-warning tnum">{format(data.paid_with_redemptions)}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function NeutralLine({ data }: { data: Expenses }) {
  const [hidden] = useHiddenValues();
  const parts: string[] = [];
  if (data.reimbursements) parts.push(`${formatMoney(data.reimbursements, { hidden })} de reembolsos já abatidos`);
  if (data.neutral.loans_out) parts.push(`${formatMoney(data.neutral.loans_out, { hidden })} emprestados`);
  if (data.neutral.loans_in) parts.push(`${formatMoney(data.neutral.loans_in, { hidden })} de empréstimos devolvidos`);
  if (data.neutral.own_transfers) parts.push(`${formatMoney(data.neutral.own_transfers, { hidden })} de outra conta sua`);
  if (!parts.length) return null;
  return (
    <p className="mt-2 text-[12px] text-muted">
      <Term help={GLOSSARY.neutro}>
        <span>Fora das contas:</span>
      </Term>{" "}
      {parts.join(" · ")}
    </p>
  );
}

function LoansCard({ data }: { data: Expenses }) {
  const [hidden] = useHiddenValues();
  if (!data.loans.length) return null;
  const open = data.loans.filter((l) => l.open > 0).reduce((s, l) => s + l.open, 0);
  return (
    <Card>
      <CardHeader title="Empréstimos em aberto" subtitle="Quanto ainda vão me devolver?" action={<Money cents={open} className="text-[15px] font-semibold tnum" />} />
      <CardBody className="pt-2">
        <ul className="divide-y divide-border text-[13px]">
          {data.loans.map((loan) => (
            <li key={loan.key} className="flex items-center justify-between gap-3 py-2.5">
              <span className="flex min-w-0 items-center gap-2.5">
                <HandCoins className="h-4 w-4 shrink-0 text-muted" />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{loan.counterparty ?? "Sem nome"}</span>
                  <span className="block text-[12px] text-muted">
                    emprestado {formatMoney(loan.lent, { hidden })} · devolvido {formatMoney(loan.returned, { hidden })}
                  </span>
                </span>
              </span>
              <span className="shrink-0 text-right">
                {loan.open > 0 ? (
                  <Money cents={loan.open} className="font-semibold tnum" />
                ) : loan.open === 0 ? (
                  <Badge tone="positive">quitado</Badge>
                ) : (
                  <Badge tone="neutral" title="Há devoluções sem o empréstimo marcado">devolvido a mais</Badge>
                )}
              </span>
            </li>
          ))}
        </ul>
        <HowCalculated label="Como funciona">
          Em aberto = Pix marcados como “Empréstimo (vou receber de volta)” − entradas marcadas como “Devolução de empréstimo”, por pessoa, em todo o
          histórico. Os dois são neutros: não mudam receitas nem despesas.
        </HowCalculated>
      </CardBody>
    </Card>
  );
}

function sourceText(tx: Transaction): string {
  if (tx.source === "manual") return "Você escolheu (só esta)";
  if (tx.source === "regra_pessoal") return "Regra pessoal";
  const label = tx.rule_level ? (RULE_LABELS[tx.rule_level] ?? "Regra automática") : "Automático";
  return tx.rule_pattern && tx.rule_level !== "a_classificar" ? `${label}: “${tx.rule_pattern.toLowerCase()}”` : label;
}

const TransactionRow = memo(function TransactionRow({
  tx,
  meta,
  color,
  busy,
  saved,
  onCategory,
  onFixed,
  onKind,
  onExtraordinary,
}: {
  tx: Transaction;
  meta: Meta | undefined;
  color: string;
  busy: boolean;
  saved: boolean;
  onCategory: (value: string) => void;
  onFixed: (value: boolean) => void;
  onKind: () => void;
  onExtraordinary: (value: boolean) => void;
}) {
  const [hidden] = useHiddenValues();
  const incoming = tx.amount > 0;
  const title = rowTitle(tx);
  const parts = (tx.description ?? "").split("|");
  const channel = parts.length > 1 ? parts[0] : null;
  const canFix = tx.movement_type === "despesa" || tx.movement_type === "estorno";
  const kindLabel = KIND_CHOICES[tx.movement_type as MovementKind]?.label ?? MOVEMENT_LABELS[tx.movement_type] ?? tx.movement_type;
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      className="group grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-2 rounded-xl px-2 py-3 transition-colors hover:bg-surface-2/60 md:grid-cols-[44px_minmax(0,1fr)_232px_92px_132px]"
    >
      <div className="hidden text-[12px] leading-tight text-muted md:block">
        <span className="block text-[15px] font-semibold text-text-2 tnum">{tx.date.slice(8, 10)}</span>
        {formatDate(tx.date, "day").split(" ").pop()}
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-border bg-surface-2 text-muted">
          {tx.account === "cartao" ? <CreditCard className="h-4 w-4" /> : <Landmark className="h-4 w-4" />}
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface" style={{ background: color }} />
        </span>
        <div className="min-w-0">
          <p className="truncate text-[13.5px] font-medium text-text" title={tx.description ?? undefined}>
            {title}
          </p>
          <p className="flex min-w-0 items-center gap-1.5 truncate text-[12px] text-muted">
            <span className="md:hidden">{formatDate(tx.date, "day")} ·</span>
            {channel ? <span className="truncate">{channel} ·</span> : null}
            {tx.installment ? <Badge>{tx.installment}</Badge> : null}
            {NEUTRAL_TYPES.has(tx.movement_type) ? <Badge>neutro</Badge> : null}
            {tx.extraordinary ? <Badge tone="warning">extraordinário</Badge> : null}
            <span className={cn("truncate", tx.source === "regra_pessoal" && "text-accent")}>{sourceText(tx)}</span>
          </p>
        </div>
      </div>
      <div className="col-span-3 flex items-center gap-1.5 md:col-span-1">
        {tx.category_editable ? (
          <Select
            size="sm"
            label={`Categoria de ${title}`}
            value={tx.category ?? "A classificar"}
            onValueChange={onCategory}
            className={cn("min-w-0 flex-1", tx.category === "A classificar" && "border-[color-mix(in_oklab,var(--warning)_45%,var(--border))]")}
            options={(meta?.categories ?? []).map((c) => ({ value: c.name, label: c.name }))}
          />
        ) : tx.kind_options.length ? (
          <button
            type="button"
            onClick={onKind}
            className="flex h-8 min-w-0 flex-1 items-center justify-between gap-2 rounded-xl border border-border bg-surface-2 px-2.5 text-left text-[13px] transition-colors hover:border-border-strong"
          >
            <span className="truncate">{kindLabel}</span>
            <ArrowLeftRight className="h-3.5 w-3.5 shrink-0 text-muted" />
          </button>
        ) : (
          <span className="text-[12.5px] text-muted">{MOVEMENT_LABELS[tx.movement_type] ?? tx.movement_type}</span>
        )}
        {tx.category_editable && tx.kind_options.length ? (
          <button
            type="button"
            onClick={onKind}
            title="É um gasto ou um empréstimo?"
            aria-label={`Mudar o tipo de ${title} (gasto ou empréstimo)`}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-xl border border-border bg-surface-2 text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            <HandCoins className="h-3.5 w-3.5" />
          </button>
        ) : null}
        {canFix ? (
          <button
            type="button"
            onClick={() => onExtraordinary(!tx.extraordinary)}
            title={tx.extraordinary ? "Extraordinário (fora do dia a dia). Clique para voltar ao dia a dia." : "Marcar como extraordinário (fora do dia a dia)"}
            aria-label={`Extraordinário: ${title}`}
            aria-pressed={tx.extraordinary}
            className={cn(
              "grid h-8 w-8 shrink-0 place-items-center rounded-xl border transition-colors",
              tx.extraordinary
                ? "border-[color-mix(in_oklab,var(--warning)_50%,var(--border))] bg-[color-mix(in_oklab,var(--warning)_14%,transparent)] text-warning"
                : "border-border bg-surface-2 text-muted hover:border-border-strong hover:text-text",
            )}
          >
            <Zap className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      <div className="col-start-1 row-start-3 flex items-center gap-2 md:col-start-auto md:row-start-auto">
        {canFix ? (
          <>
            <Switch checked={tx.is_fixed} onCheckedChange={onFixed} label={`Fixo: ${title}`} />
            <span className="text-[12px] text-muted">{tx.is_fixed ? "Fixo" : "Variável"}</span>
          </>
        ) : null}
      </div>
      <div className="col-start-3 row-start-1 flex items-center justify-end gap-2 md:col-start-auto md:row-start-auto">
        <AnimatePresence>
          {busy ? (
            <motion.span key="p" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />
            </motion.span>
          ) : saved ? (
            <motion.span key="s" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>
              <Check className="h-3.5 w-3.5 text-positive" />
            </motion.span>
          ) : null}
        </AnimatePresence>
        <FlowIcon direction={incoming ? "in" : "out"} />
        <span className={cn("whitespace-nowrap text-[14px] font-semibold tnum", incoming ? "text-income" : "text-text")}>
          {formatMoney(tx.amount, { signed: true, hidden })}
        </span>
      </div>
    </motion.li>
  );
});

/** Escolha do tipo de uma entrada na conta ou de um Pix enviado, já com o escopo. */
function KindDialog({
  tx,
  meta,
  onClose,
  onApply,
}: {
  tx: Transaction | null;
  meta: Meta | undefined;
  onClose: () => void;
  onApply: (tx: Transaction, body: Omit<ClassifyBody, "scope">, scope: Scope) => void;
}) {
  const [choice, setChoice] = useState<MovementKind | null>(null);
  const [reimbursed, setReimbursed] = useState("nenhuma");
  const [hidden] = useHiddenValues();
  const current = tx ? (tx.movement_type as MovementKind) : null;
  const selected = choice ?? current;
  const close = () => {
    setChoice(null);
    setReimbursed("nenhuma");
    onClose();
  };
  const body = (): Omit<ClassifyBody, "scope"> =>
    selected === "reembolso" && reimbursed !== "nenhuma" ? { kind: selected, category: reimbursed } : { kind: selected as MovementKind };
  return (
    <Dialog
      open={tx !== null}
      title={tx && tx.amount > 0 ? "O que é esta entrada?" : "Este Pix é um gasto ou um empréstimo?"}
      description={tx ? `${rowTitle(tx)} · ${formatDate(tx.date, "day")} · ${formatMoney(tx.amount, { signed: true, hidden })}` : null}
      onClose={close}
    >
      <div role="radiogroup" aria-label="Tipo" className="space-y-1.5">
        {(tx?.kind_options ?? []).map((kind) => (
          <button
            key={kind}
            type="button"
            role="radio"
            aria-checked={selected === kind}
            onClick={() => setChoice(kind)}
            className={cn(
              "flex w-full items-start gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors",
              selected === kind ? "border-[color-mix(in_oklab,var(--accent)_60%,var(--border))] bg-accent-soft" : "border-border bg-surface-2 hover:bg-surface-3",
            )}
          >
            <span className={cn("mt-1 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border", selected === kind ? "border-accent" : "border-border-strong")}>
              {selected === kind ? <span className="h-1.5 w-1.5 rounded-full bg-accent" /> : null}
            </span>
            <span>
              <span className="block text-[13.5px] font-medium">{KIND_CHOICES[kind].label}</span>
              <span className="block text-[12px] text-muted">{KIND_CHOICES[kind].hint}</span>
            </span>
          </button>
        ))}
      </div>
      {selected === "reembolso" ? (
        <label className="mt-3 block text-[13px]">
          <span className="text-muted">Qual gasto foi reembolsado? (opcional)</span>
          <Select
            label="Categoria do gasto reembolsado"
            value={reimbursed}
            onValueChange={setReimbursed}
            className="mt-1 w-full"
            options={[{ value: "nenhuma", label: "Não sei / geral" }, ...(meta?.categories ?? []).filter((c) => c.name !== "A classificar").map((c) => ({ value: c.name, label: c.name }))]}
          />
        </label>
      ) : null}
      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Button disabled={!tx || !selected} onClick={() => tx && onApply(tx, body(), "one")}>
          Só esta
        </Button>
        <Button variant="primary" disabled={!tx || !selected || !tx.has_counterparty} onClick={() => tx && onApply(tx, body(), "counterparty")} title={tx?.counterparty ?? undefined}>
          Todas desta contraparte
        </Button>
      </div>
      <p className="mt-2 text-[12px] text-muted">“Todas” vale para as passadas e para as que vierem de {tx?.counterparty ?? "esta contraparte"}; dá para desfazer.</p>
    </Dialog>
  );
}
