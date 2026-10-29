import type { ReactNode } from "react";
import type { MonthlyEntry, MonthlyStatusEntry } from "../../MonthlyStatusChart";

export type SyncRun = { status: string; records_processed: number; started_at?: string | null; finished_at?: string | null };
export type SourceSummary = {
  source: string;
  records: number;
  resources: Record<string, number>;
  last_sync: SyncRun | null;
};
export type Summary = { sources: SourceSummary[] };
export type StagingRecord = {
  id: string;
  source: string;
  resource_type: string;
  external_id: string;
  payload: Record<string, unknown>;
  last_paid_date?: string | null;
  secondary_status?: string;
  subscription_count?: number;
  active_subscription_count?: number;
  cobrable_subscription_count?: number;
  subscription_id?: string;
  plan_name?: string;
  client_name?: string | null;
  client_social_id?: string;
  client_rut?: string | null;
  active_subscriptions?: number | null;
  collectible_subscriptions?: number | null;
};
export type StagingResponse = { items: StagingRecord[]; total: number; offset: number; limit: number };
/**
 * Columna de una tabla de registros. `key` es el identificador ESTABLE de la columna: de él dependen el filtro,
 * el orden y los enlaces guardados (`?orden=`); `label` es solo el texto que ve el usuario y puede cambiar.
 */
export type TableColumn = { key: string; label: string; value: (record: StagingRecord) => string };
export type VirtualPosDetailColumn = {
  label: string;
  kind?: "text" | "amount" | "date";
  filterable?: boolean;
  value: (record: StagingRecord) => string;
  render?: (record: StagingRecord) => ReactNode;
};
export type Activity = { year: number; month: number; count: number; amount: number };
export type RecoveryRow = Record<string, unknown> & { source?: string; external_id?: string; subscription_id?: string; id?: string };
export type RecoveryResponse = { items: RecoveryRow[]; total: number; offset: number; limit: number };
export type VpKpis = {
  mrr: number;
  active_subscribers: number;
  active_clients: number;
  arpu: number;
  churn_rate: number;
  ltv: number;
};
export type ChannelDashboard = {
  source: string;
  records: number;
  resources: Record<string, number>;
  resource_amounts: Record<string, number>;
  statuses: { resource: string; status: string; count: number }[];
  activity_resource: string;
  activity: Activity[];
  /** Toku: serie mensual de facturas (deuda emitida); `activity` son transacciones. */
  invoice_activity?: Activity[];
  /** Payku: meses sin transacciones entre el primer y el último mes con datos. */
  coverage_gaps?: { year: number; month: number }[];
  years: number[];
  last_sync: SyncRun | null;
  kpis?: VpKpis;
  churn_window_label?: string | null;
  charges_monthly?: MonthlyStatusEntry[];
  rejected_charges_monthly?: MonthlyStatusEntry[];
  payments_monthly?: MonthlyStatusEntry[];
  invoices_monthly?: MonthlyStatusEntry[];
  transactions_monthly?: MonthlyEntry[] | MonthlyStatusEntry[];
  activation_monthly?: MonthlyStatusEntry[];
  churn_monthly?: MonthlyEntry[] | MonthlyStatusEntry[];
  churn_rate_monthly?: { year: number; month: number; rate: number }[];
  churn_rate_monthly_vp1?: { year: number; month: number; rate: number }[];
  churn_rate_monthly_vp2?: { year: number; month: number; rate: number }[];
  active_subs_monthly?: { year: number; month: number; count: number }[];
  cobrable_subs_monthly?: { year: number; month: number; count: number }[];
  alerts?: DashboardAlert[];
};
export type VirtualPosClientDetail = {
  client: StagingRecord;
  subscriptions: StagingRecord[];
  subscription_total: number;
  charges: StagingRecord[];
  charge_total: number;
  payments: StagingRecord[];
  payment_total: number;
};
export type VirtualPosPlanDetail = {
  plan: StagingRecord;
  subscriptions: StagingRecord[];
  subscription_total: number;
};
export type VirtualPosSubscriptionDetail = {
  subscription: StagingRecord;
  payment_method: unknown;
  charges: StagingRecord[];
  charge_total: number;
  payments: StagingRecord[];
  payment_total: number;
};
export type VirtualPosChargeDetail = { charge: StagingRecord; subscription: StagingRecord | null; client: StagingRecord | null; payment: StagingRecord | null };
export type VirtualPosPaymentDetail = { payment: StagingRecord; charge: StagingRecord | null; subscription: StagingRecord | null; client: StagingRecord | null };
export type RelatedRecords = {
  label: string;
  resource_type: string;
  items: StagingRecord[];
};
export type ProviderRecordDetail = {
  record: StagingRecord;
  related: RelatedRecords[];
};
export type FilterOption = { value: string; label: string };
export type SortDirection = "asc" | "desc";
export type EtlRun = {
  id: string;
  status: string;
  phase: string | null;
  started_at: string | null;
  finished_at: string | null;
  records_upserted: number;
  channels_processed: string[] | null;
  error_message: string | null;
};
export type SchedulerJob = { id: string; name: string; cron: string; next_run: string | null; last_run: EtlRun | null; status: string; active_run_id?: string | null };
export type SseEvent = { type: string; phase?: string; pct?: number | null; resource?: string; records?: number; msg?: string; total_records?: number; duration_s?: number };
export type ClientEditField = { name: string; label: string; type?: string; options?: { value: string; label: string }[] };
export type AuthUser = { id: string; username: string; is_active: boolean; roles: { id: string; name: string }[]; permissions: string[]; created_at?: string | null };
export type AuthSession = { user: AuthUser; csrf_token: string };
export type AdminRole = { id: string; name: string; description: string | null; permission_codes: string[] };
export type PermGroup = { group: string; permissions: Array<{ code: string; description: string }> };
export type DashboardAlert = { id?: string; sev: "alta" | "media" | "baja"; tipo: string; canal: string; detalle: string; periodo?: string };
export type AlertDetailItem = {
  external_id: string | null;
  rut: string | null;
  status: string | null;
  amount: number;
  suscription_date: string | null;
  ultimo_cobro?: string | null;
  ultimo_estado?: string | null;
  intentos?: number;
};
export type GeneralDashboard = {
  clients: number;
  subscriptions: { active: number; amount: number };
  transactions: { total: number; accepted: number; rejected: number; amount: number; rejection_rate_pct: number | null; basis_label?: string | null };
  channels: { source: string; clients: number; active_subscriptions: number; accepted: number; amount: number }[];
  years: number[];
  transactions_monthly: MonthlyStatusEntry[];
  activations_monthly: MonthlyStatusEntry[];
  cancellations_monthly: MonthlyStatusEntry[];
  debts_monthly: (MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" })[];
  transactions_effective_monthly: (MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" })[];
  alerts?: DashboardAlert[];
  pending_payments?: number;
  sync_success_rate_pct?: number | null;
  churn_rate_pct?: number;
};
export type GeneralClient = { rut: string; name: string; origins: string[]; active_origins: string[] };
export type GeneralClients = { items: GeneralClient[]; total: number; offset: number; limit: number };
export type GeneralSubscription = { id: string; platform: string; rut: string; client: string; status: string; started_at: string | null; ended_at: string | null; amount: string | null; currency: string | null; last_paid_date: string | null; secondary_status: string };
export type GeneralSubscriptions = { items: GeneralSubscription[]; total: number; offset: number; limit: number };
export type GeneralClientDetail = {
  rut: string;
  clients: { portal: string; id_cliente: string; external_id: string }[];
  subscriptions: { portal: string; id_subscription: string; external_id: string; status: string }[];
  charges: { portal: string; id_cargo: string; external_id: string; status: string; amount: string | null }[];
  transactions: { portal: string; id_transaccion: string; external_id: string; status: string; amount: string | null }[];
};
export type PlanCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
export type SubscriptionCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
