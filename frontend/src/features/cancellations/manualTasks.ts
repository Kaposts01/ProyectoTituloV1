import { getBlob, getJson, postJson, saveBlob } from "../../api";
import { label, tryLabel, unknownLabel } from "../../i18n/label";
import type { Tone } from "../billing/billingLabels";
import { withCsrfRetry } from "../shared/csrfRetry";

/** Permisos de las tareas manuales (MGT-11/13/14) y del cambio de monto (MGT-12/14, misma bandeja de cobros). */
export const PERM_MANUAL_TASKS_VIEW = "subscriptions.manual_tasks.view";
export const PERM_MANUAL_TASKS_CONFIRM = "subscriptions.manual_tasks.confirm";
export const PERM_BILLING_REQUEST = "virtualpos.billing_changes.request";

export type ManualTaskType = "payment_method_retained" | "tch_bank_mandate" | "payku_amount_change";
export type ManualTaskStatus = "pending" | "confirmed" | "verified" | "dismissed";

export type ManualTask = {
  id: string;
  task_type: ManualTaskType;
  channel: string;
  subscription_external_id: string;
  status: ManualTaskStatus;
  cancellation_request_id: string | null;
  target_amount: number | null;
  previous_amount: number | null;
  created_by: string | null;
  assigned_to_user_id: string | null;
  assigned_to: string | null;
  confirmed_by_user_id: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  confirmation_comment: string | null;
  verified_at: string | null;
  verification_source: string | null;
  dismissed_by: string | null;
  dismissed_at: string | null;
  dismiss_comment: string | null;
  code: string | null;
  created_at: string | null;
};

export type ManualTaskList = { items: ManualTask[]; total: number; limit: number; offset: number };

/** Respuesta de la vista previa de la bandeja de cobros (solo lo que usa el diálogo de Toku). */
export type TokuAmountPreview = {
  summary: { previous_amount: number | null; new_amount: number | null; variation_pct: number | null } | null;
  plan_preview: { toku?: { invoices_to_update: number; invoices_in_progress_skipped: number } };
  would_self_approve: boolean;
};

const BASE = "/api/v1/manual-tasks";
const enc = encodeURIComponent;
export const OPEN_TASK_STATUSES: ManualTaskStatus[] = ["pending", "confirmed"];

export function manualTasksPath(statuses: ManualTaskStatus[], offset: number, limit: number): string {
  const params = new URLSearchParams();
  for (const s of statuses) params.append("status", s);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `${BASE}?${params.toString()}`;
}

export const fetchManualTasks = (statuses: ManualTaskStatus[], offset: number, limit: number) =>
  getJson<ManualTaskList>(manualTasksPath(statuses, offset, limit));
export const confirmManualTask = (id: string, comment?: string) =>
  withCsrfRetry(() => postJson<ManualTask>(`${BASE}/${enc(id)}/confirm`, comment ? { comment } : undefined));
export const dismissManualTask = (id: string, comment: string) =>
  withCsrfRetry(() => postJson<ManualTask>(`${BASE}/${enc(id)}/dismiss`, { comment }));
export const createPaykuAmountTask = (subscriptionId: string, newAmount: number, comment?: string) =>
  withCsrfRetry(() => postJson<ManualTask>(`${BASE}/payku-amount`, {
    subscription_external_id: subscriptionId, new_amount: newAmount, ...(comment ? { comment } : {}),
  }));

/** Cambio de monto de Toku: reutiliza la bandeja de «Cambios de cobro» (d106). */
const tokuBody = (subscriptionId: string, newAmount: number, comment?: string) => ({
  request_type: "change_amount", platform: "toku", subscription_external_id: subscriptionId, new_amount: newAmount,
  ...(comment ? { requester_comment: comment } : {}),
});
export const previewTokuAmount = (subscriptionId: string, newAmount: number) =>
  withCsrfRetry(() => postJson<TokuAmountPreview>("/api/v1/billing/changes/preview", tokuBody(subscriptionId, newAmount)));
export const createTokuAmount = (subscriptionId: string, newAmount: number, comment?: string) =>
  withCsrfRetry(() => postJson<{ id: string; status: string }>("/api/v1/billing/changes", tokuBody(subscriptionId, newAmount, comment)));

/** CSV de las bajas TCH en trámite (sin PAN ni datos de cuenta): lo arma el servidor. */
export async function downloadTchExport(): Promise<void> {
  const { blob, filename } = await getBlob(`${BASE}/tch-export`);
  saveBlob(blob, filename ?? "bajas_tch_en_tramite.csv");
}

const STATUS_TONE: Record<ManualTaskStatus, Tone> = { pending: "warning", confirmed: "neutral", verified: "ok", dismissed: "neutral" };

export const taskTypeText = (type: string) => label("manualTaskType", type);
export const taskStatusText = (status: string) => label("manualTaskStatus", status);
export const taskStatusTone = (status: string): Tone => STATUS_TONE[status as ManualTaskStatus] ?? "neutral";
export function taskErrorText(code: string | null | undefined, fallback: string): string {
  return (code && tryLabel("manualTaskError", code)) || fallback;
}
export function taskCodeText(code: string | null): string {
  if (!code) return "—";
  return tryLabel("cancellationManual", code) ?? unknownLabel(code);
}

/** Acciones visibles: confirmar solo `pending`; descartar `pending`/`confirmed`. El servidor decide en último término. */
export function taskActions(task: { status: string }, can: (p: string) => boolean): { confirm: boolean; dismiss: boolean } {
  const allowed = can(PERM_MANUAL_TASKS_CONFIRM);
  return { confirm: allowed && task.status === "pending", dismiss: allowed && (task.status === "pending" || task.status === "confirmed") };
}

/** Monto entero positivo en CLP; null si el texto no lo es. */
export function parseAmount(text: string): number | null {
  const clean = text.trim().replace(/[.\s$]/g, "");
  if (!/^\d{1,10}$/.test(clean)) return null;
  const value = Number(clean);
  return value > 0 ? value : null;
}

/** Código de error estructurado de la API (`detail.code`), o null. */
export function errorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "object" && detail !== null && typeof (detail as { code?: unknown }).code === "string") {
    return (detail as { code: string }).code;
  }
  return null;
}
