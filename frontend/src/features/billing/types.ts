/** Contrato de la API de cambios de cobro (app/api/v1/routes/billing_changes.py). */

export const PERM_VIEW = "virtualpos.billing_changes.view";
export const PERM_REQUEST = "virtualpos.billing_changes.request";
export const PERM_APPROVE = "virtualpos.billing_changes.approve";
export const PERM_POLICY = "virtualpos.billing_policy.manage";

export type RequestType = "change_amount" | "change_date" | "renew_calendar" | "one_off_charge";
export type RequestStatus =
  | "pendiente" | "aprobada" | "aplicando" | "ejecutada" | "rechazada" | "expirada" | "retirada" | "fallida"
  | "requiere_conciliacion" | "no_ejecutable";
export type Platform = "virtualpos1" | "virtualpos2";

export type PlanAction = { month: string; charge_date: string; amount: number; internal_code?: string | null; charge_id?: string | null; depends_on?: string[] };
export type PlanIssue = { code: string; message: string; month?: string | null };
export type PlanSummary = {
  creates: number; cancels: number; covered_months: number; manual_review_months: number; unchanged_months: number;
  affected_charges: number; previous_amount: number | null; new_amount: number | null; amount_delta: number | null;
  total_delta: number | null; variation_pct: number | null; horizon_start: string | null; horizon_end: string | null;
};
export type PlanPreview = {
  version?: number;
  request_type?: string;
  subscription_external_id?: string;
  noop?: boolean;
  create?: PlanAction[];
  cancel?: PlanAction[];
  covered?: Array<{ month: string; reason: string; charge_ids?: string[] }>;
  manual_review?: Array<{ month: string; target_date: string; days_overdue: number; reason: string }>;
  unchanged?: string[];
  kept_automatic_after_horizon?: Array<{ month: string; charge_id: string; charge_date: string; amount: number }>;
  warnings?: PlanIssue[];
  errors?: PlanIssue[];
  summary?: PlanSummary | null;
};

/** Solicitante del filtro de la bandeja: solo id y nombre de usuario. */
export type Requester = { id: string; username: string };
export type RequesterList = { items: Requester[] };

export type BillingRequest = {
  id: string;
  request_type: RequestType;
  platform: string;
  subscription_external_id: string;
  status: RequestStatus;
  requested_by_user_id: string;
  requested_by: string | null;
  new_amount: number | null;
  previous_amount: number | null;
  new_charge_day: number | null;
  previous_charge_day: number | null;
  new_charge_date: string | null;
  horizon_months: number | null;
  horizon_start_month: string | null;
  approvals_required: number;
  approvals_count: number;
  requester_comment: string | null;
  approved_by_user_id: string | null;
  approved_by: string | null;
  self_approved: boolean;
  decided_at: string | null;
  decision_comment: string | null;
  write_run_id: string | null;
  expires_at: string | null;
  executed_at: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type BillingEvent = {
  id: string;
  event_type: string;
  actor_user_id: string | null;
  actor: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
};

export type BillingRequestDetail = BillingRequest & {
  plan_preview: PlanPreview;
  rules_snapshot: Record<string, unknown>;
  events: BillingEvent[];
};

export type BillingList = { items: BillingRequest[]; total: number; limit: number; offset: number };

export type ChangeBody = {
  request_type: RequestType;
  platform: Platform;
  subscription_external_id: string;
  new_amount?: number;
  new_charge_day?: number;
  new_charge_date?: string;
  requester_comment?: string;
  task_ref?: string;
};

export type PreviewResponse = {
  plan_preview: PlanPreview;
  summary: PlanSummary | null;
  approvals_required: number;
  would_self_approve: boolean;
  expires_in_days: number;
  open_request: { id: string; status: string } | null;
};

export type ApplyResponse = {
  request_id: string;
  status: string;
  request_status: RequestStatus;
  already_applied: boolean;
  reason: string | null;
  created: number;
  cancelled: number;
  covered_late_months: number;
  manual_review_months: number;
  drift_accepted: boolean;
  plan_summary: PlanSummary | null;
};

export type DriftDiff = {
  create_added?: unknown[][];
  create_removed?: unknown[][];
  cancel_added?: unknown[][];
  cancel_removed?: unknown[][];
  manual_review_added?: string[];
  manual_review_removed?: string[];
};

export type Policy = {
  approver_roles: string[];
  approver_user_ids: string[];
  self_approval_enabled: boolean;
  dual_approval_enabled: boolean;
  dual_threshold_subscriptions: number;
  dual_threshold_variation_pct: number;
  renewal_threshold_days: number;
  request_expiry_days: number;
  horizon_months: number;
  window_days: number;
  updated_by_user_id?: string | null;
  updated_at?: string | null;
};
export type PolicyPatch = Partial<Omit<Policy, "updated_by_user_id" | "updated_at">> & { reason?: string };

export type PolicyAuditEntry = {
  id: string;
  changed_by_user_id: string | null;
  changed_by: string | null;
  changed_at: string | null;
  before_values: Record<string, unknown> | null;
  after_values: Record<string, unknown> | null;
  reason: string | null;
};
export type PolicyAuditList = { items: PolicyAuditEntry[]; total: number; limit: number; offset: number };

/** Tareas de renovación de calendario (GET /api/v1/billing/renewal-tasks). Sin nombre del socio por decisión de privacidad. */
export type RenewalStatus = "abierta" | "vencida" | "cerrada" | "no_aplica";
export type RenewalPriority = "normal" | "alta";
export type RenewalTask = {
  id: string;
  platform: Platform;
  subscription_external_id: string;
  status: RenewalStatus;
  priority: RenewalPriority;
  last_scheduled_date: string | null;
  scheduled_amount: number | null;
  due_date: string | null;
  days_remaining: number | null;
  data_stale: boolean;
  request_id: string | null;
  close_reason: string | null;
};
export type RenewalTaskList = { items: RenewalTask[]; total: number; limit: number; offset: number };
