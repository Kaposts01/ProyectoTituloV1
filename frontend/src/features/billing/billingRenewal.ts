import type { Platform, RenewalPriority, RenewalStatus } from "./types";
import type { Tone } from "./billingLabels";

/** Mapeos y consulta puros de la sección «Renovaciones» (tareas del chequeo diario de calendario). */

export const RENEWAL_BASE = "/api/v1/billing/renewal-tasks";
export const OPEN_RENEWAL_STATUSES: RenewalStatus[] = ["abierta", "vencida"];
export const ALL_RENEWAL_STATUSES: RenewalStatus[] = ["abierta", "vencida", "cerrada", "no_aplica"];

export const RENEWAL_STATUS_META: Record<RenewalStatus, { label: string; tone: Tone }> = {
  abierta: { label: "Abierta", tone: "neutral" },
  vencida: { label: "Vencida", tone: "error" },
  cerrada: { label: "Cerrada", tone: "ok" },
  no_aplica: { label: "No aplica", tone: "neutral" },
};
export const RENEWAL_PRIORITY_META: Record<RenewalPriority, { label: string; tone: Tone }> = {
  alta: { label: "Alta", tone: "warning" },
  normal: { label: "Normal", tone: "neutral" },
};

export function renewalStatusLabel(status: string): string {
  return RENEWAL_STATUS_META[status as RenewalStatus]?.label ?? status;
}
export function renewalStatusTone(status: string): Tone {
  return RENEWAL_STATUS_META[status as RenewalStatus]?.tone ?? "neutral";
}
export function renewalPriorityLabel(priority: string): string {
  return RENEWAL_PRIORITY_META[priority as RenewalPriority]?.label ?? priority;
}
export function renewalPriorityTone(priority: string): Tone {
  return RENEWAL_PRIORITY_META[priority as RenewalPriority]?.tone ?? "neutral";
}

export function isOpenRenewal(status: string): boolean {
  return status === "abierta" || status === "vencida";
}

/** Texto de plazo desde los días que calcula el SERVIDOR (no el reloj del navegador). */
export function daysText(daysRemaining: number | null | undefined): string | null {
  if (daysRemaining === null || daysRemaining === undefined || !Number.isFinite(daysRemaining)) return null;
  const d = Math.trunc(daysRemaining);
  if (d === 0) return "vence hoy";
  if (d > 0) return `vence en ${d} ${d === 1 ? "día" : "días"}`;
  const n = Math.abs(d);
  return `vencida hace ${n} ${n === 1 ? "día" : "días"}`;
}

export const CLOSE_REASON_GENERIC = "Cerrada por el sistema (motivo no reconocido).";

/**
 * `close_reason` es texto en español que emite el chequeo (app/services/billing_renewal.py), no un código.
 * Se reconocen sus frases; cualquier otro valor se reemplaza por un texto genérico (nunca se muestra el crudo).
 */
export function closeReasonLabel(reason: string | null | undefined): string {
  const r = (reason ?? "").trim();
  if (!r) return "—";
  const active = /^La suscripción ya no está ACTIVA(?: \(estado: ([^)]{1,40})\))?\.?$/.exec(r);
  if (active) return active[1] && active[1] !== "desconocido" ? `La suscripción dejó de estar activa (estado: ${active[1]}).` : "La suscripción dejó de estar activa.";
  if (r.startsWith("Renovación ejecutada")) return "Renovación ejecutada: el calendario se extendió.";
  if (r.startsWith("El calendario se extendió")) return "El calendario se extendió (sin solicitud de renovación asociada).";
  if (r.startsWith("La suscripción ya no tiene un calendario modificado activo")) return "La suscripción ya no tiene un calendario modificado activo.";
  return CLOSE_REASON_GENERIC;
}

export type RenewalStatusFilter = "open" | "all" | RenewalStatus;
export type RenewalFilters = {
  status: RenewalStatusFilter;
  priority: RenewalPriority | "";
  platform: Platform | "";
  subscription: string;
};
export const EMPTY_RENEWAL_FILTERS: RenewalFilters = { status: "open", priority: "", platform: "", subscription: "" };

export function renewalStatuses(status: RenewalStatusFilter): RenewalStatus[] {
  if (status === "open") return OPEN_RENEWAL_STATUSES;
  if (status === "all") return ALL_RENEWAL_STATUSES;
  return [status];
}

export function renewalPath(filters: RenewalFilters, offset: number, limit: number): string {
  const p = new URLSearchParams();
  for (const s of renewalStatuses(filters.status)) p.append("status", s);
  if (filters.priority) p.set("priority", filters.priority);
  if (filters.platform) p.set("platform", filters.platform);
  if (filters.subscription.trim()) p.set("subscription_id", filters.subscription.trim());
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  return `${RENEWAL_BASE}?${p.toString()}`;
}

/** Contador de la pestaña: tareas abiertas/vencidas de prioridad alta (una vencida siempre es alta). */
export function renewalAlertPath(): string {
  return `${RENEWAL_BASE}?status=abierta&status=vencida&priority=alta&limit=1&offset=0`;
}
