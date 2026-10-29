import { setCsrfToken, getJson } from "../../api";
import { label, tryLabel } from "../../i18n/label";
import type { AuthSession, RecoveryRow, StagingRecord } from "./types";
import type { MonthlyEntry, MonthlyStatusEntry } from "../../MonthlyStatusChart";

export const RECORDS_PAGE_SIZE = 100;

export function groupPermissions(all: Array<{ code: string; description: string }>): { group: string; permissions: Array<{ code: string; description: string }> }[] {
  const groupOf = (code: string): string => {
    if (code.startsWith("users.") || code.startsWith("roles.")) return "Administración";
    if (code.startsWith("virtualpos.")) return "VirtualPOS";
    if (code.startsWith("toku.")) return "Toku";
    if (code.startsWith("payku.")) return "Payku";
    if (code.startsWith("tch.")) return "TCH";
    if (code.startsWith("etl.") || code.startsWith("sync")) return "Sincronización";
    return "General";
  };
  const map = new Map<string, Array<{ code: string; description: string }>>();
  for (const p of all) {
    const g = groupOf(p.code);
    if (!map.has(g)) map.set(g, []);
    map.get(g)!.push(p);
  }
  const ORDER = ["Administración", "General", "VirtualPOS", "Toku", "Payku", "TCH", "Sincronización"];
  return ORDER.filter(g => map.has(g)).map(group => ({ group, permissions: map.get(group)! }));
}

export function aggregateChurn(churn: (MonthlyEntry | MonthlyStatusEntry)[]): MonthlyEntry[] {
  const byMonth = new Map<string, MonthlyEntry>();
  for (const entry of churn) {
    const key = `${entry.year}-${entry.month}`;
    const cur = byMonth.get(key) ?? { year: entry.year, month: entry.month, count: 0, amount: 0 };
    cur.count += entry.count;
    cur.amount += entry.amount;
    byMonth.set(key, cur);
  }
  return [...byMonth.values()].sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month);
}

export function defaultYear(years: number[]): number | null {
  if (!years.length) return null;
  const current = new Date().getFullYear();
  if (years.includes(current)) return current;
  const past = years.filter((entry) => entry < current);
  return past.length ? Math.max(...past) : Math.min(...years);
}

export async function refreshCsrfToken(): Promise<void> {
  const session = await getJson<AuthSession>("/api/v1/auth/me");
  setCsrfToken(session.csrf_token);
}

export function text(value: unknown, fallback = "Sin dato"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function dateOnly(value: unknown, fallback = "Sin dato"): string {
  const raw = text(value, "");
  if (!raw) return fallback;
  return /^\d{4}-\d{2}-\d{2}/.test(raw) ? raw.slice(0, 10) : raw;
}

export function clp(value: unknown, fallback = "Sin dato"): string {
  const raw = text(value, "");
  if (!raw) return fallback;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return raw;
  return `$${Math.round(numeric).toLocaleString("es-CL")}`;
}

export function recoveryValue(item: RecoveryRow, ...keys: string[]): unknown {
  for (const key of keys) {
    if (item[key] !== undefined && item[key] !== null && item[key] !== "") return item[key];
  }
  return undefined;
}

export function recoveryNestedValue(item: RecoveryRow, relation: string, ...keys: string[]): unknown {
  const value = item[relation];
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return recoveryValue(value as RecoveryRow, ...keys);
}

export function recoveryAmount(item: RecoveryRow): string {
  const amount = recoveryValue(item, "amount", "charge_amount", "subscription_amount");
  if (amount === undefined) return "—";
  const numeric = Number(amount);
  const value = Number.isFinite(numeric) ? numeric.toLocaleString("es-CL") : String(amount);
  const currency = recoveryValue(item, "currency") ?? recoveryNestedValue(item, "charge", "currency");
  return currency ? `${currency} ${value}` : value;
}

export function recoveryRowKey(item: RecoveryRow): string {
  return `${recoveryValue(item, "source") ?? ""}:${recoveryValue(item, "external_id", "id", "subscription_id") ?? ""}`;
}

export function recoveryDisplay(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return text(value, "—");
  const item = value as RecoveryRow;
  return text(recoveryValue(item, "name", "full_name", "email", "external_id", "id"), "—");
}

export function documentType(value: unknown): string {
  const normalized = String(value ?? "").toUpperCase();
  return normalized === "RUT" ? "1" : normalized === "DNI" ? "2" : normalized;
}

export function normalizeRut(value: string): string | null {
  const compact = value.toUpperCase().replace(/[.\-\s]/g, "");
  if (!/^[0-9]+[0-9K]$/.test(compact)) return null;
  const body = compact.slice(0, -1).replace(/^0+/, "") || "0";
  const checkDigit = compact.at(-1)!;
  const total = [...body].reverse().reduce((sum, digit, index) => sum + Number(digit) * (2 + index % 6), 0);
  const remainder = total % 11;
  const expected = remainder === 0 ? "0" : remainder === 1 ? "K" : String(11 - remainder);
  return checkDigit === expected ? `${body}-${checkDigit}` : null;
}

export function fieldLabel(field: string): string {
  return tryLabel("field", field) ?? `Campo (${field})`;
}

export function providerRecordHeading(record: StagingRecord): string {
  if (record.source === "toku" && record.resource_type === "subscription") {
    return text(record.payload.product_id, record.external_id);
  }
  return text(record.payload.name, text(record.payload.id, record.external_id));
}

export function externalUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function renewalText(value: unknown): string {
  const normalized = String(value).toLowerCase();
  if (["t", "true", "1"].includes(normalized)) return label("boolean", true);
  if (["f", "false", "0"].includes(normalized)) return label("boolean", false);
  return text(value);
}

export function cardTypeText(value: unknown): string {
  return label("cardType", value);
}

export function isActiveSubscription(record: StagingRecord): boolean {
  return String(record.payload.status).toLowerCase() === "activa";
}

export function isPendingCharge(record: StagingRecord): boolean {
  return String(record.payload.status ?? "").toLowerCase() === "pendiente";
}

export function isRejectedCharge(record: StagingRecord): boolean {
  return String(record.payload.status ?? "").toLowerCase() === "rechazado";
}

export function nested(
  payload: Record<string, unknown>,
  key: string,
  child: string,
): unknown {
  const value = payload[key];
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)[child]
    : undefined;
}

export function objectEntries(value: unknown): [string, unknown][] {
  return value && typeof value === "object" && !Array.isArray(value)
    ? Object.entries(value as Record<string, unknown>)
    : [];
}

export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function identifierList(value: unknown): string {
  if (!Array.isArray(value)) return text(value);
  return (
    value
      .map((item) => text(typeof item === "object" ? record(item).id : item, ""))
      .filter(Boolean)
      .join(", ") || "Sin dato"
  );
}

export function title(source: string): string {
  if (source === "virtualpos") return "VirtualPOS";
  if (source === "toku") return "Toku";
  if (source === "payku") return "Payku";
  if (source === "tch") return "TCH";
  return source.charAt(0).toUpperCase() + source.slice(1);
}

export function resourceTitle(resource: string): string {
  return label("resource", resource);
}
