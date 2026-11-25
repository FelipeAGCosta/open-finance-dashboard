/** Tipos e chamadas da API local (FastAPI em 127.0.0.1). Valores monetários em centavos. */

export type Cents = number;
/** Lugar de um investimento no Plano: Reserva de emergência ou Patrimônio. */
export type Place = "reserva" | "patrimonio";
export interface Flows {
  contributions: Cents;
  redemptions: Cents;
  net: Cents;
  shrinking?: boolean;
}

export interface Meta {
  demo: boolean;
  today: string;
  current_month: string;
  months: string[];
  /** color: cor FIXA da categoria (1..18; 0 = neutra). */
  categories: { name: string; essential: boolean | null; color: number | null }[];
  sync_enabled: boolean;
}

export interface SalaryMonth {
  rule_id: number;
  counterparty: string | null;
  status: string;
  paycheck: Cents;
  /** Agenda em texto: "todo dia 5", "toda segunda", "a cada 2 semanas, na sexta". */
  schedule: string;
  frequency: "weekly" | "biweekly" | "monthly";
  started_on: string | null;
  paydays: number;
  due_paydays: number;
  expected: Cents;
  expected_due: Cents;
  received: Cents;
  received_cash: Cents;
  annual_average: Cents;
  in_progress: boolean;
  divergent: boolean;
  difference: Cents;
  missing_paydays: string[];
  off_schedule: string[];
  shifted: { credited: string; reference: string }[];
}

export interface MonthData {
  month: string;
  income: Cents;
  salary: Cents;
  investment_income: Cents;
  expenses: Cents;
  expenses_count: number;
  result: Cents;
  savings_rate: number | null;
  unclassified: { cents: Cents; count: number };
  fixed: Cents;
  variable: Cents;
  extraordinary: { cents: Cents; count: number };
  everyday: Cents;
  result_everyday: Cents;
  savings_rate_everyday: number | null;
  paid_with_redemptions: Cents;
  flows: Flows;
  essential: Cents;
  non_essential: Cents;
  no_flag: Cents;
  contributions: Cents;
  redemptions: Cents;
  reimbursements: Cents;
  neutral: { loans_out: Cents; loans_in: Cents; own_transfers: Cents };
  bill_payments: Cents;
  categories: { name: string; cents: Cents }[];
  refunds_without_origin: Cents;
  salaries: SalaryMonth[];
}

export interface Alert {
  level: "critical" | "warning" | "info";
  title: string;
  detail: string;
  cents?: Cents;
  target: "status" | "overview" | "expenses" | "plan";
}

export interface PlanSummary {
  total: Cents;
  base: Cents;
  extra: Cents;
  flows: Flows;
  remaining: Cents;
  capacity: Cents;
  fits: boolean;
  projected_surplus: Cents;
  places: { label: string; planned: Cents; color: string }[];
  reserve_priority: boolean;
}

export interface InvestmentsMonth {
  start: string;
  end: string;
  start_value: Cents;
  end_value: Cents;
  change: Cents;
  contributions: Cents;
  redemptions: Cents;
  net_flows: Cents;
  income: Cents;
  growth: Cents;
  gain: Cents;
  partial_since: string | null;
  in_progress: boolean;
}

/** Patrimônio total = carteira bruta (como o banco mostra em Investimentos) + compras em liquidação. */
export interface Wealth {
  date: string;
  total: Cents;
  portfolio: Cents;
  in_transit: {
    cents: Cents;
    items: InTransitItem[];
    /** Ativos da foto mais recente, para "já chegou (é o ativo X)". */
    assets: { id: string; label: string }[];
  };
}

export interface InTransitItem {
  id: string;
  date: string;
  description: string;
  cents: Cents;
  until: string;
  /** Ativo provável (compra registrada ou posição que apareceu na janela). */
  suggestion: { id: string; label: string } | null;
}

export type InTransitAction = "chegou" | "ignorar";

export interface WealthWithSeries extends Wealth {
  change: { cents: Cents; pct: number | null; since: string };
  series: { date: string; total: Cents; portfolio: Cents; in_transit: Cents }[];
}

export interface Overview {
  month: MonthData;
  wealth: WealthWithSeries | null;
  /** Saldo da conta e fatura em aberto: só informação, fora do patrimônio. */
  accounts: { date: string; bank: Cents; card_bill: Cents } | null;
  history: { month: string; income: Cents; expenses: Cents; investment_income: Cents }[];
  plan: PlanSummary | null;
  investments_month: InvestmentsMonth | null;
  data_as_of: string | null;
  alerts: Alert[];
}

export type MovementKind =
  | "receita"
  | "reembolso"
  | "devolucao_emprestimo"
  | "transferencia_propria"
  | "despesa"
  | "emprestimo_concedido";

export interface Transaction {
  id: string;
  date: string;
  description: string | null;
  counterparty: string | null;
  amount: Cents;
  account: "conta" | "cartao";
  status: string;
  movement_type: string;
  movement_rule: string;
  category: string | null;
  essential: boolean | null;
  is_fixed: boolean;
  extraordinary: boolean;
  fixed_source: "transacao" | "regra" | null;
  rule_level: string | null;
  rule_pattern: string | null;
  source: "manual" | "regra_pessoal" | "automatico";
  from_interface_rule: boolean;
  installment: string | null;
  category_editable: boolean;
  kind_options: MovementKind[];
  counterparty_kind: "PF" | "PJ" | null;
  has_counterparty: boolean;
  override: { category: string | null; fixed: boolean | null; movement_type: string | null; extraordinary: boolean | null } | null;
}

export interface Loan {
  key: string;
  counterparty: string | null;
  lent: Cents;
  returned: Cents;
  open: Cents;
  last_date: string | null;
}

export interface Expenses {
  month: string;
  total: Cents;
  count: number;
  by_category: { name: string; cents: Cents; count: number }[];
  fixed: { fixed: Cents; variable: Cents; pending: Cents };
  everyday: Cents;
  extraordinary: { cents: Cents; count: number };
  paid_with_redemptions: Cents;
  income: Cents;
  result: Cents;
  result_everyday: Cents;
  savings_rate: number | null;
  savings_rate_everyday: number | null;
  flows: Flows;
  essential: { essential: Cents; non_essential: Cents; no_flag: Cents };
  reimbursements: Cents;
  reimbursements_uncategorized: Cents;
  refunds_without_origin: Cents;
  neutral: { loans_out: Cents; loans_in: Cents; own_transfers: Cents };
  loans: Loan[];
  transactions: Transaction[];
}

export interface RecurringRule {
  id: number;
  kind: "fixo" | "salario";
  counterparty: string | null;
  category: string | null;
  status: "automatico" | "manual_sim" | "manual_nao";
  manual: boolean;
  active: boolean;
  state: "ativo" | "inativo" | "desmarcado";
  stale: boolean;
  inactive_after_days: number;
  avg_monthly: Cents | null;
  months_count: number | null;
  detected: boolean;
  interval_days: number | null;
  paycheck: Cents | null;
  schedule: string | null;
  annual_average: Cents | null;
  last_payment: { date: string; cents: Cents } | null;
  first_payment: string | null;
  this_month?: { paid: Cents; pending: Cents };
}

export interface Fixed {
  fixed: RecurringRule[];
  salary: RecurringRule[];
  fixed_monthly: Cents;
  month: {
    month: string;
    paid: Cents;
    pending: Cents;
    singles: { key: string; counterparty: string | null; category: string | null; paid: Cents; count: number; last_payment: string | null }[];
  };
  commitments: { months: { month: string; cents: Cents }[]; total: Cents };
}

export interface Asset {
  id: string;
  label: string;
  code: string | null;
  class: string;
  class_source: string;
  quantity: number | null;
  price: number | null;
  balance: Cents;
  net: Cents;
  pct: number | null;
  variation: { cents: Cents; pct: number | null; since: string; bought: Cents; sold: Cents } | null;
  dividends_12m: Cents | null;
}

export interface MonthlyReturn {
  month: string;
  start: string;
  end: string;
  start_value: Cents;
  end_value: Cents;
  contributions: Cents;
  redemptions: Cents;
  income: Cents;
  gain: Cents;
  twr: number | null;
  cdi: number | null;
  ipca: number | null;
  target: number;
  ipca_note: string;
  partial_since: string | null;
  in_progress: boolean;
}

export interface Investments {
  snapshot_date: string | null;
  data_as_of: string | null;
  total: Cents;
  total_net: Cents;
  wealth: Wealth | null;
  /** Os grupos da tela de investimentos do app do banco, para conferir os totais lado a lado. */
  bank_view: {
    institution: string | null;
    groups: { label: string; cents: Cents }[];
    in_transit: Cents;
    total: Cents;
  } | null;
  aspirational: number;
  allocation: { class: string; cents: Cents; pct: number | null }[];
  allocation_by_place: { place: Place; label: string; color: string; cents: Cents; pct: number | null }[];
  assets: Asset[];
  evolution: { date: string; value: Cents }[];
  performance: {
    days: number;
    min_days: number;
    enough: boolean;
    first_date: string | null;
    series: { date: string; twr: number; cdi: number | null; ipca: number | null; target: number }[];
    accumulated: {
      twr: number | null;
      xirr_annual: number | null;
      xirr_period: number | null;
      cdi: number | null;
      ipca: number | null;
      net_flows: Cents;
      income: Cents;
      notes: string[];
      target: number;
      above_target: boolean | null;
    } | null;
  };
  monthly: { months: MonthlyReturn[]; total_contributions: Cents; total_redemptions: Cents; total_gain: Cents };
  fixed_income: {
    label: string;
    class: string;
    rate: string;
    purchase_date: string | null;
    due_date: string | null;
    applied: Cents | null;
    gross: Cents | null;
    net: Cents | null;
    profit: Cents | null;
    return_pct: number | null;
    annualized: number | null;
  }[];
  dividends: {
    total: Cents;
    by_month: { month: string; cents: Cents }[];
    by_class: { month: string; total: Cents; by_class: Record<string, Cents>; by_asset: Record<string, Cents> }[];
  };
}

export interface SyncRun {
  id: number;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  full: boolean;
  new: number;
  updated: number;
  snapshots: number;
  error: string | null;
}

export interface Status {
  demo: boolean;
  last_run: SyncRun | null;
  last_success: SyncRun | null;
  items: {
    connector: string | null;
    status: string | null;
    execution_status: string | null;
    last_updated: string | null;
    next_auto_sync: string | null;
    consent_expires_at: string | null;
    consent_days: number | null;
    consent_warning: string | null;
    checked_at: string | null;
    /** Horas desde a última atualização do dado na Pluggy, só quando passa de 36 h. */
    stale_hours: number | null;
  }[];
  snapshots: { days: number; first: string | null; last: string | null };
  transactions: { first: string | null; last: string | null };
  counts: Record<string, number>;
  sync_enabled: boolean;
  sync_running: boolean;
}

// ------------------------------------------------------------------ Plano

/** Classes do alvo da carteira (somam 100%). */
export type Bucket = "renda_fixa" | "etf_global" | "etf_brasil" | "acoes_nucleo" | "fiis" | "satelite";
/** Na tela entra também "Ações mantidas": só acompanha, sem alvo e sem aporte. */
export type DisplayBucket = Bucket | "acoes_mantidas";
export type StockRole = "nucleo" | "manter" | "satelite";
export type CoreWeights = "iguais" | "atual" | "personalizado";
export type BucketState = "abaixo" | "no_alvo" | "acima" | "dentro_teto" | "acima_teto" | "sem_alvo";

export interface PlanSettingValue {
  aporte_mensal: { cents: Cents; extra_paycheck: boolean };
  colchao: { cents: Cents };
  reserva: { cents: Cents | null; order: string[] };
  alvo_patrimonio: { classes: Record<Bucket, number | null>; etf_global: string | null; etf_brasil: string | null };
  nucleo: { tickers: string[]; satellite: string[]; weights: CoreWeights; custom: Record<string, number> };
  rentabilidade: { assumed: number; aspirational: number };
}
export type PlanKey = keyof PlanSettingValue;

export interface PlanSetting<K extends PlanKey> {
  value: PlanSettingValue[K];
  effective_month: string | null;
  id: number | null;
  /** Só mudanças reais: a última gravação de cada mês, sem repetir o valor anterior. */
  history: { id: number; effective_month: string; value: PlanSettingValue[K]; created_at: string }[];
}

export interface Capacity {
  month: string;
  closed: boolean;
  income: Cents;
  salary_remaining: Cents;
  salary_remaining_paydays: string[];
  expenses: Cents;
  fixed_pending: Cents;
  variable_daily: Cents | null;
  days_remaining: number;
  variable_estimate: Cents;
  variable_months: { month: string; cents: Cents; days: number }[];
  contributions: Cents;
  redemptions: Cents;
  contributions_net: Cents;
  projected_surplus: Cents;
  capacity: Cents;
  bank: Cents | null;
  card_bill: Cents | null;
  balance_date: string | null;
  cushion: Cents;
  cash_available: Cents | null;
  depends_on_future_salary: boolean;
}

export interface PatrimonyBucket {
  bucket: DisplayBucket;
  label: string;
  current: Cents;
  current_pct: number | null;
  target_pct: number | null;
  target_cents: Cents | null;
  deviation_pct: number | null;
  deviation_cents: Cents | null;
  suggested: boolean;
  cap: boolean;
  over_cap: boolean;
  state: BucketState;
  needs_core: boolean;
  members: { label: string; cents: Cents }[];
}

/** Uma linha de "O que fazer este mês": R$ X → onde comprar. */
export interface ChecklistLine {
  where: string;
  amount: Cents;
  detected: Cents;
  shares: number | null;
  price: Cents | null;
  ticker: string | null;
  done: boolean;
}

/** Meta de um mês e a lista de compras (o mês atual ou a prévia do próximo). */
export interface MonthPlan {
  month: string;
  base: Cents;
  total: Cents;
  /** Pagamento extra do salário no mês (ex.: 5ª segunda num salário semanal), quando a meta pede para somá-lo. */
  extra: { active: boolean; cents: Cents; paycheck: Cents; count: number; enabled: boolean };
  reserve_priority: { active: boolean; cents: Cents; gap: Cents };
  checklist: ChecklistLine[];
  patrimony: {
    amount: Cents;
    target_defined: boolean;
    leftover: Cents;
    buckets: { bucket: Bucket; label: string; amount: Cents }[];
    items: { bucket: Bucket; label: string; ticker: string | null; amount: Cents; price: Cents | null; shares: number | null; spend: Cents; carried_in: Cents }[];
  };
}

export interface Plan {
  month: string;
  today: string;
  data_as_of: string | null;
  /** Horas desde a última atualização da Pluggy, só quando passa de 36 h. */
  data_stale_hours: number | null;
  wealth: Wealth | null;
  settings: { [K in PlanKey]: PlanSetting<K> };
  capacity: Capacity;
  contribution: MonthPlan & {
    flows: Flows;
    invested: Cents;
    remaining: Cents;
    capacity: Cents;
    projected_surplus: Cents;
    fits: boolean;
    places: { place: Place; label: string; color: string; planned: Cents }[];
    next: MonthPlan | null;
  };
  reserve: {
    target: Cents | null;
    current: Cents;
    gap: Cents;
    complete: boolean;
    order: string[];
    essential_average: Cents | null;
    essential_months: { month: string; cents: Cents }[];
    covered_months: number | null;
    target_months: number | null;
    holdings: { label: string; class: string; cents: Cents; manual: boolean }[];
  };
  patrimony: {
    current: Cents;
    target_defined: boolean;
    off_target: number;
    buckets: PatrimonyBucket[];
    core: { ticker: string; current: Cents; current_pct: number | null; weight: number; target_pct: number | null; deviation_pct: number | null }[];
    core_weights: CoreWeights;
    etf_global: string | null;
    etf_brasil: string | null;
  };
  places: { place: Place; label: string; color: string; cents: Cents }[];
  holdings: {
    investment_id: string;
    label: string;
    class: string;
    value: Cents;
    place: Place;
    place_label: string;
    manual: boolean;
    reason: string;
    parts: { place: Place; label: string; cents: Cents }[];
    ticker: string | null;
    role: StockRole | null;
  }[];
  returns: { assumed: number; aspirational: number };
  history: {
    month: string;
    contributed: Cents;
    contributions: Cents;
    redemptions: Cents;
    target: Cents | null;
    surplus: Cents | null;
    in_progress: boolean;
  }[];
}

export interface UndoPackage {
  kind: "transaction" | "plan_setting" | "investment_place" | "in_transit";
  payload: Record<string, unknown>;
}

export interface ClassifyBody {
  scope: "one" | "counterparty";
  category?: string | null;
  fixed?: boolean | null;
  kind?: MovementKind;
  extraordinary?: boolean | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

const withMonth = (path: string, month?: string) => (month ? `${path}?month=${month}` : path);
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  overview: (month?: string) => request<Overview>(withMonth("/api/overview", month)),
  expenses: (month?: string) => request<Expenses>(withMonth("/api/expenses", month)),
  fixed: () => request<Fixed>("/api/fixed"),
  investments: () => request<Investments>("/api/investments"),
  plan: () => request<Plan>("/api/plan"),
  status: () => request<Status>("/api/status"),
  patchTransaction: (id: string, body: { category?: string | null; fixed?: boolean | null }) =>
    request<{ transaction: Transaction }>(`/api/transactions/${encodeURIComponent(id)}`, json("PATCH", body)),
  classify: (id: string, body: ClassifyBody) =>
    request<{ transaction: Transaction; affected: number; undo: UndoPackage }>(
      `/api/transactions/${encodeURIComponent(id)}/classify`,
      json("POST", body),
    ),
  undo: (undo: UndoPackage) => request<{ ok: boolean }>("/api/undo", json("POST", undo)),
  patchRule: (id: number, mode: "auto" | "sim" | "nao") =>
    request<{ rule: RecurringRule }>(`/api/recurring/${id}`, json("PATCH", { mode })),
  savePlanSetting: <K extends PlanKey>(key: K, effective_month: string, value: PlanSettingValue[K]) =>
    request<{ id: number | null; unchanged: boolean; undo: UndoPackage | null }>("/api/plan/settings", json("POST", { key, effective_month, value })),
  setPlace: (investmentId: string, place: Place | null) =>
    request<{ undo: UndoPackage }>(`/api/investments/${encodeURIComponent(investmentId)}/place`, json("PUT", { place })),
  setInTransit: (transactionId: string, action: InTransitAction | null, investmentId?: string) =>
    request<{ undo: UndoPackage }>(
      `/api/in-transit/${encodeURIComponent(transactionId)}`,
      json("PUT", { action, investment_id: investmentId ?? null }),
    ),
  sync: () => request<{ ok: boolean; code: number; lines: string[] }>("/api/sync", { method: "POST" }),
};
