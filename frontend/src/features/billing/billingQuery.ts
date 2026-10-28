import { HISTORY_STATUSES, PENDING_STATUSES } from "./billingLabels";
import type { Platform, RequestStatus, RequestType } from "./types";

export type InboxTab = "pending" | "history";

export type InboxFilters = {
  status: RequestStatus | "";
  requestType: RequestType | "";
  platform: Platform | "";
  subscription: string;
  requestedBy: string;
  dateFrom: string;
  dateTo: string;
};

export const EMPTY_FILTERS: InboxFilters = { status: "", requestType: "", platform: "", subscription: "", requestedBy: "", dateFrom: "", dateTo: "" };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value.trim());
}

/** Mensaje de validación local de filtros (null si son válidos). */
export function validateFilters(filters: InboxFilters): string | null {
  if (filters.requestedBy.trim() && !isUuid(filters.requestedBy)) return "El ID del solicitante debe ser un UUID válido.";
  if (filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo) return "La fecha inicial no puede ser posterior a la final.";
  return null;
}

/** Estados a consultar: el filtro explícito (si pertenece a la pestaña) o todos los de la pestaña. */
export function statusesFor(tab: InboxTab, status: RequestStatus | ""): RequestStatus[] {
  const group = tab === "pending" ? PENDING_STATUSES : HISTORY_STATUSES;
  return status && group.includes(status) ? [status] : group;
}

export function listParams(tab: InboxTab, filters: InboxFilters, offset: number, limit: number): URLSearchParams {
  const p = new URLSearchParams();
  for (const s of statusesFor(tab, filters.status)) p.append("status", s);
  if (filters.requestType) p.set("request_type", filters.requestType);
  if (filters.platform) p.set("platform", filters.platform);
  if (filters.subscription.trim()) p.set("subscription_id", filters.subscription.trim());
  if (isUuid(filters.requestedBy)) p.set("requested_by", filters.requestedBy.trim());
  if (DATE_RE.test(filters.dateFrom)) p.set("date_from", filters.dateFrom);
  if (DATE_RE.test(filters.dateTo)) p.set("date_to", filters.dateTo);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  return p;
}

export function listPath(tab: InboxTab, filters: InboxFilters, offset = 0, limit = 25): string {
  return `/api/v1/billing/changes?${listParams(tab, filters, offset, limit).toString()}`;
}
