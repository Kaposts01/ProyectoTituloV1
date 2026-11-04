/** Tipos del API de bajas de suscripción (`/api/v1/cancellations`). Las claves y los valores ya están en inglés. */

export const PERM_CANCELLATION_REQUEST = "subscriptions.cancellation.request";
export const PERM_CANCELLATION_APPROVE = "subscriptions.cancellation.approve";
export const PERM_CANCELLATION_VIEW = "subscriptions.cancellation.view";

export type CancellationChannel = "virtualpos1" | "virtualpos2" | "toku" | "payku" | "tch";

export type CancellationStatus =
  | "pending" | "approved" | "applying" | "pending_external" | "completed" | "failed"
  | "requires_reconciliation" | "rejected" | "withdrawn" | "expired" | "not_executable";

export type CancellationReason =
  | "member_request" | "payment_failure" | "duplicate_subscription" | "deceased"
  | "fraud_suspected" | "organization_decision" | "other";

export type TokuStopMode = "paused" | "end_date";

export type StepStatus = "pending" | "done" | "failed" | "skipped" | "manual";

/** Paso de la cascada (vista previa): `action` es un código fijo; `count` solo en cobros. */
export type PreviewStep = {
  step: string;
  action: string;
  reversible?: boolean;
  count?: number;
  reason?: string;
};

export type CascadePreview = {
  channel?: CancellationChannel;
  subscription_status?: string | null;
  irreversible?: boolean;
  pending_charges?: number;
  pending_charge_ids?: string[];
  processing_charges?: number;
  in_progress_invoices?: number;
  blockers?: string[];
  steps?: PreviewStep[];
  source?: string;
};

/** Resultado de un paso ya ejecutado (o manual). `code` es un código fijo, nunca texto del proveedor. */
export type StepResult = {
  step: string;
  status: StepStatus;
  code?: string | null;
  task?: string;
  at?: string;
  [key: string]: unknown;
};

export type CancellationOptions = {
  toku_stop_mode?: TokuStopMode;
  toku_end_date?: string;
  confirm_irreversible?: boolean;
};

export type CancellationRequest = {
  id: string;
  channel: CancellationChannel;
  subscription_external_id: string;
  status: CancellationStatus;
  reason_code: CancellationReason;
  reason_comment: string;
  requested_by_user_id: string;
  requested_by: string | null;
  approved_by_user_id: string | null;
  approved_by: string | null;
  self_approved: boolean;
  approvals_required: number;
  approvals_count: number;
  decided_at: string | null;
  decision_comment: string | null;
  options: CancellationOptions;
  requires_reconciliation: boolean;
  write_run_id: string | null;
  expires_at: string | null;
  executed_at: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type CancellationEvent = {
  id: string;
  event_type: string;
  actor_user_id: string | null;
  actor: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
};

export type CancellationDetail = CancellationRequest & {
  cascade_preview: CascadePreview;
  steps: StepResult[];
  rules_snapshot: Record<string, unknown>;
  events: CancellationEvent[];
};

export type CancellationList = { items: CancellationRequest[]; total: number; limit: number; offset: number };
export type CancellationEventList = { items: CancellationEvent[]; total: number };

/** Cuerpo de crear / vista previa. Los campos de Toku y la confirmación solo aplican a su canal. */
export type CancellationBody = {
  channel: CancellationChannel;
  subscription_external_id: string;
  reason_code: CancellationReason;
  reason_comment: string;
  toku_stop_mode?: TokuStopMode;
  toku_end_date?: string;
  confirm_irreversible?: boolean;
};

export type PreviewResponse = {
  cascade_preview: CascadePreview;
  options: CancellationOptions;
  approvals_required: number;
  would_self_approve: boolean;
  expires_in_days: number;
  open_request: { id: string; status: CancellationStatus } | null;
};

/** Plan de la simulación (`dry_run`): lo que se haría, sin escribir. */
export type ApplyPlan = {
  channel: CancellationChannel;
  request_status: CancellationStatus;
  preview: CascadePreview;
  steps_done: string[];
  steps_to_run: string[];
  blockers: string[];
  invoices_to_void: number | null;
  irreversible: boolean;
};

export type ApplyResponse = {
  request_id: string;
  /** `completed`, `pending_external`, `not_executable` o `dry_run`. */
  status: string;
  request_status: CancellationStatus;
  already_applied: boolean;
  dry_run: boolean;
  reason: string | null;
  steps: StepResult[];
  plan: ApplyPlan | null;
  write_run_id: string | null;
};
