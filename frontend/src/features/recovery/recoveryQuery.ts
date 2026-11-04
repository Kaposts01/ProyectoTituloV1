export type RecoveryTab = "cancelled" | "retry" | "history" | "card";
export type RecoveryGroup = "inactiva" | "incobrable" | "nunca_cobrado";
export type SecondaryStatus = "inactiva" | "incobrable" | "nunca_cobrado" | "cobrable";

export type RecoveryFilterValues = {
  account: string;
  rejectionCode: string;
  minAmount: string;
  maxAmount: string;
  secondaryStatus: string;
  rejectedFrom: string;
  rejectedTo: string;
  dateFrom: string;
  dateTo: string;
};

export const EMPTY_FILTERS: RecoveryFilterValues = {
  account: "", rejectionCode: "", minAmount: "", maxAmount: "", secondaryStatus: "", rejectedFrom: "", rejectedTo: "", dateFrom: "", dateTo: "",
};

export type RecoveryQueryState = { tab: RecoveryTab; group: RecoveryGroup; filters: RecoveryFilterValues };

/** Tabs that accept the extended backend filters (the retry history endpoint only takes dates). */
export function tabAcceptsFilters(tab: RecoveryTab): boolean {
  return tab !== "history";
}

function validAmount(value: string): string | null {
  const trimmed = value.trim().replace(",", ".");
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  return Number.isFinite(numeric) && numeric >= 0 ? String(numeric) : null;
}

/** Pure mapping of UI filters to backend query params; empty values are omitted. */
export function filtersToParams(tab: RecoveryTab, group: RecoveryGroup, f: RecoveryFilterValues): URLSearchParams {
  const params = new URLSearchParams();
  if (tab === "cancelled") params.set("group", group);
  if (tab === "retry") params.set("bucket", "retry");
  if (tab === "card") params.set("bucket", "card");
  if (tab !== "card") {
    if (f.dateFrom) params.set("date_from", f.dateFrom);
    if (f.dateTo) params.set("date_to", f.dateTo);
  }
  if (!tabAcceptsFilters(tab)) return params;
  if (f.account) params.set("account", f.account);
  const code = f.rejectionCode.trim();
  if (code && tab !== "cancelled") params.set("rejection_code", code);
  const min = validAmount(f.minAmount);
  const max = validAmount(f.maxAmount);
  if (min !== null) params.set("min_amount", min);
  if (max !== null) params.set("max_amount", max);
  if (f.secondaryStatus && tab !== "cancelled") params.set("secondary_status", f.secondaryStatus);
  if (f.rejectedFrom && tab !== "cancelled") params.set("rejected_from", f.rejectedFrom);
  if (f.rejectedTo && tab !== "cancelled") params.set("rejected_to", f.rejectedTo);
  return params;
}

const BASE = "/api/v1/recovery";

export function listPath(state: RecoveryQueryState, offset = 0, limit = 50): string {
  const { tab, group, filters } = state;
  const params = filtersToParams(tab, group, filters);
  // /card-expirations always means bucket=card, so it takes no bucket param.
  if (tab === "card") params.delete("bucket");
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  const base = tab === "cancelled" ? "group" : tab === "retry" ? "rejected" : tab === "history" ? "retry-history" : "card-expirations";
  return `${BASE}/${base}?${params.toString()}`;
}

export type ExportTarget = { path: string; filename: string };

/** Export endpoint for a tab, or null when the tab has none. Exports ignore pagination. */
export function exportTarget(state: RecoveryQueryState): ExportTarget | null {
  const { tab, group, filters } = state;
  if (tab === "history") return null;
  const params = filtersToParams(tab, group, filters);
  const query = params.toString();
  if (tab === "cancelled") return { path: `${BASE}/group/export?${query}`, filename: `socios-${group}.csv` };
  const bucket = tab === "retry" ? "retry" : "card";
  return { path: `${BASE}/rejected/export?${query}`, filename: `cargos-rechazados-${bucket}.csv` };
}

export function canExport(can: (permission: string) => boolean): boolean {
  return can("virtualpos.recovery.export");
}
