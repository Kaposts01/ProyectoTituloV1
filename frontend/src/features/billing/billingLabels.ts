import { formatKpi } from "../../components/formatKpi";
import { serverNow } from "../../serverClock";
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

export const CHILE_TZ = "America/Santiago";
/** Nota para pantallas que muestran fechas con hora. */
export const CHILE_TZ_NOTE = "Fechas y horas en hora de Chile (America/Santiago).";

let chileFormatter: Intl.DateTimeFormat | null = null;
function chileParts(date: Date): Record<string, string> {
  chileFormatter ??= new Intl.DateTimeFormat("en-CA", {
    timeZone: CHILE_TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const out: Record<string, string> = {};
  for (const part of chileFormatter.formatToParts(date)) out[part.type] = part.value;
  return out;
}

/**
 * Instante ISO -> "2026-03-05 11:30" en hora de Chile (America/Santiago), sin depender de la zona del navegador.
 * Una fecha sin hora ("2026-03-05") se deja igual; una hora sin zona se interpreta como UTC (así las emite el backend).
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const m = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(value);
  if (!m) return value;
  if (!m[2]) return m[1];
  const hasZone = /(Z|[+-]\d{2}(?::?\d{2})?)$/i.test(value);
  const date = new Date(hasZone ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return `${m[1]} ${m[2]}`;
  const p = chileParts(date);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

const DAY_MS = 86_400_000;

/**
 * Texto de expiración solo para solicitudes pendientes de aprobación. El «ahora» sale de la hora del servidor
 * (cabecera Date de la última respuesta), no del reloj del navegador.
 */
export function expiryText(request: Pick<BillingRequest, "status" | "expires_at">, now: Date = new Date(serverNow())): string | null {
  if (request.status !== "pendiente" || !request.expires_at) return null;
  const expires = new Date(request.expires_at).getTime();
  if (Number.isNaN(expires)) return null;
  const diff = expires - now.getTime();
  if (diff <= 0) return "vencida";
  const days = Math.ceil(diff / DAY_MS);
  if (days <= 1) return "vence hoy";
  return `vence en ${days} días`;
}

const TECH_CODE = /^[A-Za-z0-9_.:-]{1,60}(?: [A-Za-z0-9_.:-]{1,30}){0,3}$/;

/**
 * `error_message` / `detail.error` son una ETIQUETA técnica corta («RuntimeError», «VirtualPOSAPIError E-113»,
 * «StuckApplying»), no un mensaje legible. Se muestra tal cual, sin interpretarla; lo que no parezca etiqueta se descarta.
 */
export function technicalCode(value: unknown): string | null {
  return typeof value === "string" && value.length <= 100 && TECH_CODE.test(value.trim()) ? value.trim() : null;
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
  aplicada: "Cambio aplicado",
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

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Notas de un evento a partir de claves conocidas (nunca el payload completo). Tolera claves ausentes o con tipos raros. */
export function eventNotes(eventType: string, detail: Record<string, unknown> | undefined): string[] {
  const d = detail ?? {};
  const notes: string[] = [];
  if (eventType === "reintentada") {
    const before = num(d.previous_approvals_count);
    const beforeOf = num(d.previous_approvals_required);
    const now = num(d.new_approvals_required);
    const parts: string[] = [];
    if (before !== null && beforeOf !== null) parts.push(`antes ${before} de ${beforeOf}`);
    if (now !== null) parts.push(`ahora se requieren ${now}`);
    notes.push(`Aprobaciones reiniciadas${parts.length ? ` (${parts.join("; ")})` : ""}.`);
    if (typeof d.to_status === "string" && d.to_status in STATUS_META) notes.push(`Nuevo estado: ${statusLabel(d.to_status)}.`);
  }
  return notes;
}

/** Etiquetas técnicas de un evento (`error`, `previous_error`), para mostrarlas en mono como «Código técnico». */
export function eventTechnical(detail: Record<string, unknown> | undefined): Array<{ label: string; code: string }> {
  const out: Array<{ label: string; code: string }> = [];
  const err = technicalCode(detail?.error);
  if (err) out.push({ label: "Código técnico", code: err });
  const prev = technicalCode(detail?.previous_error);
  if (prev) out.push({ label: "Código técnico previo", code: prev });
  return out;
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

export const APPROVE_BLOCK_ALREADY = "Usted ya aprobó esta solicitud; se necesita otro aprobador distinto.";
export const APPROVE_BLOCK_REQUESTER_DUAL = "El solicitante no puede aprobar una solicitud con doble aprobación.";
export const APPROVE_BLOCK_NO_SELF = "La política vigente al crear la solicitud no permite aprobar sus propias solicitudes.";

type ApproveCheckInput = Pick<BillingRequest, "requested_by_user_id" | "approvals_required"> & {
  events: Array<{ event_type: string; actor_user_id: string | null; created_at: string | null }>;
  rules_snapshot?: Record<string, unknown>;
};

/**
 * Motivo por el que el usuario NO debería poder aprobar (para deshabilitar el botón con texto visible), o null.
 * Solo cuenta la ronda vigente (tras una reapertura las aprobaciones anteriores no valen). El backend sigue siendo
 * la autoridad: aquí solo se evita un clic que sabemos que termina en 403/409.
 */
export function approveBlockReason(request: ApproveCheckInput, userId: string | undefined): string | null {
  if (!userId) return null;
  const events = request.events
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (a.e.created_at ?? "").localeCompare(b.e.created_at ?? "") || a.i - b.i)
    .map((x) => x.e);
  let lastReopen = -1;
  events.forEach((e, i) => { if (e.event_type === "reintentada") lastReopen = i; });
  if (events.slice(lastReopen + 1).some((e) => (e.event_type === "aprobada" || e.event_type === "autoaprobada") && e.actor_user_id === userId)) {
    return APPROVE_BLOCK_ALREADY;
  }
  if (userId === request.requested_by_user_id) {
    const selfOk = request.rules_snapshot?.self_approval_enabled;
    if (request.approvals_required >= 2 && selfOk !== true) return APPROVE_BLOCK_REQUESTER_DUAL;
    if (selfOk === false) return APPROVE_BLOCK_NO_SELF;
  }
  return null;
}

/** Retirar: solo el solicitante o un admin (AP-33). Sin usuario conocido no se oculta nada. */
export function canWithdrawRequest(request: Pick<BillingRequest, "requested_by_user_id">, userId: string | undefined, isAdmin: boolean): boolean {
  return !userId || isAdmin || userId === request.requested_by_user_id;
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
