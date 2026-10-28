import { formatKpi } from "../../components/formatKpi";
import type { BillingRequest, RequestStatus, RequestType } from "./types";
import { PERM_APPROVE, PERM_POLICY, PERM_REQUEST } from "./types";

export type Tone = "ok" | "warning" | "error" | "neutral";

export const STATUS_META: Record<RequestStatus, { label: string; tone: Tone; group: "pending" | "history" }> = {
  pendiente: { label: "Pendiente", tone: "warning", group: "pending" },
  aprobada: { label: "Aprobada", tone: "ok", group: "pending" },
  aplicando: { label: "Aplicando", tone: "neutral", group: "pending" },
  fallida: { label: "Fallida", tone: "error", group: "pending" },
  requiere_conciliacion: { label: "Requiere conciliación", tone: "error", group: "pending" },
  ejecutada: { label: "Ejecutada", tone: "ok", group: "history" },
  rechazada: { label: "Rechazada", tone: "error", group: "history" },
  expirada: { label: "Expirada", tone: "neutral", group: "history" },
  retirada: { label: "Retirada", tone: "neutral", group: "history" },
  no_ejecutable: { label: "No ejecutable", tone: "neutral", group: "history" },
};

export const ALL_STATUSES = Object.keys(STATUS_META) as RequestStatus[];
export const PENDING_STATUSES = ALL_STATUSES.filter((s) => STATUS_META[s].group === "pending");
export const HISTORY_STATUSES = ALL_STATUSES.filter((s) => STATUS_META[s].group === "history");
export const REOPENABLE: RequestStatus[] = ["fallida", "requiere_conciliacion"];

export const TYPE_LABELS: Record<RequestType, string> = {
  change_amount: "Cambio de monto",
  change_date: "Cambio de día de cobro",
  renew_calendar: "Renovación de calendario",
  one_off_charge: "Cobro puntual",
};
export const REQUEST_TYPES = Object.keys(TYPE_LABELS) as RequestType[];

export const PLATFORM_LABELS: Record<string, string> = { virtualpos1: "VirtualPOS 1", virtualpos2: "VirtualPOS 2" };

export function statusLabel(status: string): string {
  return STATUS_META[status as RequestStatus]?.label ?? status;
}
export function statusTone(status: string): Tone {
  return STATUS_META[status as RequestStatus]?.tone ?? "neutral";
}
export function typeLabel(type: string): string {
  return TYPE_LABELS[type as RequestType] ?? type;
}

export function formatClp(value: number | null | undefined): string {
  return formatKpi(value, "clp");
}

/** Variación porcentual; null -> "—". */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("es-CL", { maximumFractionDigits: 2 })}%`;
}

export function formatSignedClp(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${formatKpi(value, "clp")}`;
}

/** "2026-03-05T14:30:00+00:00" -> "2026-03-05 14:30"; "2026-03-05" se deja igual. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const m = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(value);
  if (!m) return value;
  return m[2] ? `${m[1]} ${m[2]}` : m[1];
}

const DAY_MS = 86_400_000;

/** Texto de expiración solo para solicitudes pendientes de aprobación. */
export function expiryText(request: Pick<BillingRequest, "status" | "expires_at">, now: Date = new Date()): string | null {
  if (request.status !== "pendiente" || !request.expires_at) return null;
  const expires = new Date(request.expires_at).getTime();
  if (Number.isNaN(expires)) return null;
  const diff = expires - now.getTime();
  if (diff <= 0) return "vencida";
  const days = Math.ceil(diff / DAY_MS);
  if (days <= 1) return "vence hoy";
  return `vence en ${days} días`;
}

export const EVENT_LABELS: Record<string, string> = {
  creada: "Solicitud creada",
  aprobada: "Aprobada",
  autoaprobada: "Autoaprobada",
  rechazada: "Rechazada",
  retirada: "Retirada",
  expirada: "Expirada",
  aplicando: "Aplicación iniciada",
  ejecutada: "Ejecutada",
  fallida: "Aplicación fallida",
  reintentada: "Reabierta",
  requiere_conciliacion: "Requiere conciliación",
  no_ejecutable: "No ejecutable",
};
export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replace(/_/g, " ");
}

/** Comentario de un evento (solo texto plano; nunca el payload completo). */
export function eventComment(detail: Record<string, unknown> | undefined): string | null {
  const c = detail?.comment;
  return typeof c === "string" && c.trim() ? c : null;
}

export type RequestActions = { approve: boolean; reject: boolean; withdraw: boolean; reopen: boolean; apply: boolean };

/** Acciones visibles según estado y permisos. El backend decide en última instancia (403/409). */
export function availableActions(request: Pick<BillingRequest, "status">, can: (permission: string) => boolean): RequestActions {
  const pending = request.status === "pendiente";
  const approver = can(PERM_APPROVE);
  return {
    approve: pending && approver,
    reject: pending && approver,
    withdraw: pending && can(PERM_REQUEST),
    reopen: REOPENABLE.includes(request.status) && (approver || can(PERM_POLICY)),
    apply: request.status === "aprobada" && approver,
  };
}

/** Descripción corta de lo pedido, para listas. */
export function requestSummary(r: BillingRequest): string {
  switch (r.request_type) {
    case "change_amount": return `${formatClp(r.previous_amount)} → ${formatClp(r.new_amount)}`;
    case "change_date": return `día ${r.previous_charge_day ?? "—"} → día ${r.new_charge_day ?? "—"}`;
    case "one_off_charge": return `${formatClp(r.new_amount)} el ${r.new_charge_date ?? "—"}`;
    default: return r.horizon_months ? `${r.horizon_months} meses` : "—";
  }
}
