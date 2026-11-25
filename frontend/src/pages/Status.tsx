import { AlertTriangle, CalendarCheck2, Camera, CheckCircle2, Clock, Link2, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { ErrorState, PageSkeleton } from "@/components/states";
import { Badge, Button, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { formatDate, formatDateTime, formatNumber, relativeDays } from "@/lib/format";
import { useStatus, useSyncMutation } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function StatusPage() {
  const query = useStatus();
  const sync = useSyncMutation();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton cards={4} />;
  const data = query.data;
  const run = data.last_run;
  const item = data.items[0];
  const ok = run?.status === "success";
  const running = sync.isPending || data.sync_running;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
        <Tile
          icon={ok ? <CheckCircle2 className="h-4 w-4 text-positive" /> : <XCircle className="h-4 w-4 text-negative" />}
          label="Última sincronização"
          value={run ? relativeDays(run.finished_at ?? run.started_at) : "nunca"}
          footer={run ? `${formatDateTime(run.started_at)} · ${ok ? "sucesso" : "falhou"}` : "rode a primeira sincronização"}
        />
        <Tile
          icon={<Link2 className="h-4 w-4 text-accent" />}
          label="Conexão Open Finance"
          value={item?.status ? (ITEM_STATUS[item.status] ?? item.status) : "—"}
          footer={item ? `${item.connector ?? ""} · ${EXECUTION_STATUS[item.execution_status ?? ""] ?? item.execution_status ?? "—"}` : "sem item"}
        />
        <Tile
          icon={item?.consent_warning ? <AlertTriangle className="h-4 w-4 text-warning" /> : <ShieldCheck className="h-4 w-4 text-positive" />}
          label="Consentimento"
          value={item?.consent_days !== null && item?.consent_days !== undefined ? `${item.consent_days} dias` : "—"}
          footer={item?.consent_expires_at ? `expira em ${formatDate(item.consent_expires_at.slice(0, 10), "long")}` : "sem data de expiração"}
          warn={Boolean(item?.consent_warning)}
        />
        <Tile
          icon={<Camera className="h-4 w-4 text-accent" />}
          label="Fotos diárias acumuladas"
          value={`${data.snapshots.days} ${data.snapshots.days === 1 ? "dia" : "dias"}`}
          footer={data.snapshots.first ? `desde ${formatDate(data.snapshots.first)}` : "nenhuma foto ainda"}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_380px]">
        <Card>
          <CardHeader
            title="Sincronizar agora"
            subtitle="backup do banco, busca na Pluggy, fotos do dia e reclassificação"
            action={
              <Button variant="primary" onClick={() => sync.mutate()} disabled={!data.sync_enabled || running}>
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {running ? "Sincronizando…" : "Sincronizar agora"}
              </Button>
            }
          />
          <CardBody>
            <div className="flex gap-3 rounded-xl border border-border bg-surface-2 px-4 py-3 text-[13px] leading-relaxed text-text-2">
              <Clock className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
              <span>
                A Pluggy atualiza os dados do banco <strong className="text-text">uma vez por dia</strong>. Sincronizar de novo no
                mesmo dia só traz novidades se a Pluggy já tiver atualizado
                {item?.last_updated ? <> (última atualização: {formatDateTime(item.last_updated)})</> : null}.
                {!data.sync_enabled ? " No modo demonstração a sincronização fica desligada." : ""}
              </span>
            </div>
            <AnimatePresence>
              {sync.data || sync.error ? (
                <motion.pre
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className={cn(
                    "mt-4 overflow-x-auto whitespace-pre-wrap rounded-xl border px-4 py-3 font-mono text-[12px] leading-relaxed",
                    sync.data?.ok ? "border-border bg-surface-2 text-text-2" : "border-[color-mix(in_oklab,var(--negative)_40%,var(--border))] text-negative",
                  )}
                >
                  {sync.error ? sync.error.message : sync.data?.lines.join("\n")}
                </motion.pre>
              ) : null}
            </AnimatePresence>
            {run?.error ? (
              <p className="mt-4 rounded-xl bg-[color-mix(in_oklab,var(--negative)_12%,transparent)] px-3 py-2.5 text-[13px] text-negative">
                Erro da última sincronização: {run.error}
              </p>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Banco local" subtitle="histórico permanente neste computador" action={<CalendarCheck2 className="h-4 w-4 text-muted" />} />
          <CardBody className="pt-2">
            <dl className="space-y-2 text-[13px]">
              <Row label="Período das transações">
                {formatDate(data.transactions.first)} a {formatDate(data.transactions.last)}
              </Row>
              {run ? (
                <Row label="Última execução">
                  {formatNumber(run.new)} novas · {formatNumber(run.updated)} atualizadas
                </Row>
              ) : null}
              {Object.entries(data.counts)
                .filter(([name]) => name in TABLE_LABELS)
                .map(([name, count]) => (
                  <Row key={name} label={TABLE_LABELS[name] as string}>
                    <span className="tnum">{formatNumber(count)}</span>
                  </Row>
                ))}
              {data.demo ? (
                <div className="pt-2">
                  <Badge tone="accent">modo demonstração: dados fictícios</Badge>
                </div>
              ) : null}
            </dl>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

// Chaves de queries.table_counts (as mesmas do comando `status`).
const TABLE_LABELS: Record<string, string> = {
  "transações (total)": "Transações",
  investimentos: "Investimentos",
  "transações de investimentos": "Movimentos de investimentos",
  "fotos da carteira (dias)": "Dias com foto da carteira",
  "execuções de sync": "Sincronizações registradas",
};

// Estados do item na Pluggy (https://docs.pluggy.ai) em português.
const ITEM_STATUS: Record<string, string> = {
  UPDATED: "Atualizada",
  UPDATING: "Atualizando",
  OUTDATED: "Desatualizada",
  LOGIN_ERROR: "Erro de login",
  WAITING_USER_INPUT: "Aguardando você",
  WAITING_USER_ACTION: "Aguardando você",
};

const EXECUTION_STATUS: Record<string, string> = {
  SUCCESS: "última coleta com sucesso",
  PARTIAL_SUCCESS: "última coleta parcial",
  ERROR: "última coleta com erro",
  MERGING: "processando",
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 pb-2 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium text-text-2">{children}</dd>
    </div>
  );
}

function Tile({ icon, label, value, footer, warn }: { icon: ReactNode; label: string; value: string; footer: string; warn?: boolean }) {
  return (
    <Card className={cn("p-5", warn && "border-[color-mix(in_oklab,var(--warning)_45%,var(--border))]")}>
      <p className="flex items-center gap-2 text-[13px] font-medium text-muted">
        {icon}
        {label}
      </p>
      <p className="mt-2.5 text-[22px] font-semibold tracking-[-0.02em] first-letter:uppercase">{value}</p>
      <p className="mt-1.5 text-[12.5px] text-muted">{footer}</p>
    </Card>
  );
}
