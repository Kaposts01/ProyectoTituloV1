import type { CancellationChannel, CancellationStatus } from "./types";

/** Pestañas de la bandeja: pendientes de decisión, en ejecución o con seguimiento, e historial cerrado. */
export type CancellationTab = "pending" | "running" | "history";

export const TAB_STATUSES: Record<CancellationTab, CancellationStatus[]> = {
  pending: ["pending", "approved"],
  running: ["applying", "pending_external", "requires_reconciliation", "failed"],
  history: ["completed", "rejected", "withdrawn", "expired", "not_executable"],
};

export const CHANNELS: CancellationChannel[] = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];

export type CancellationFilters = { status: CancellationStatus | ""; channel: CancellationChannel | "" };
export const EMPTY_CANCELLATION_FILTERS: CancellationFilters = { status: "", channel: "" };

/** Estados a consultar: el filtro explícito (si pertenece a la pestaña) o todos los de la pestaña. */
export function statusesFor(tab: CancellationTab, status: CancellationStatus | ""): CancellationStatus[] {
  const group = TAB_STATUSES[tab];
  return status && group.includes(status) ? [status] : group;
}

export function listPath(tab: CancellationTab, filters: CancellationFilters, offset = 0, limit = 25): string {
  const params = new URLSearchParams();
  for (const status of statusesFor(tab, filters.status)) params.append("status", status);
  if (filters.channel) params.set("channel", filters.channel);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `/api/v1/cancellations?${params.toString()}`;
}
