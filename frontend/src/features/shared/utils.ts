import { setCsrfToken, getJson } from "../../api";
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

export function normalizeTchSummary(data: Partial<import("./types").TchSummary>): import("./types").TchSummary {
  return {
    suscripciones: data.suscripciones ?? { vigentes: 0, eliminadas: 0, total: 0, monto_vigentes: 0, monto_eliminadas: 0, monto_total: 0 },
    transacciones: data.transacciones ?? { total: 0, aceptadas: 0, rechazadas: 0, tasa_rechazo_pct: 0, monto: 0 },
    kpis: data.kpis ?? { mrr: 0, arpu: 0, active_clients: 0, active_subscribers: 0, churn_rate: 0, ltv: 0 },
    years: data.years ?? [],
    transacciones_mensuales: data.transacciones_mensuales ?? [],
    activaciones_mensuales: data.activaciones_mensuales ?? [],
    bajas_mensuales: data.bajas_mensuales ?? [],
    active_subs_monthly: data.active_subs_monthly ?? [],
    churn_rate_monthly: data.churn_rate_monthly ?? [],
    ultimo_etl: data.ultimo_etl ?? { id: null, status: null, started_at: null, records_upserted: null },
    alerts: data.alerts ?? [],
  };
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
  return fieldLabels[field] ?? field.replaceAll("_", " ");
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
  if (["t", "true", "1"].includes(normalized)) return "True";
  if (["f", "false", "0"].includes(normalized)) return "False";
  return text(value);
}

export function cardTypeText(value: unknown): string {
  const normalized = String(value).toUpperCase();
  if (normalized === "TC") return "Tarjeta Credito";
  if (normalized === "TD") return "Tarjeta Debito";
  if (["TP", "TPE", "PREPAGO"].includes(normalized)) return "Tarjeta Prepago";
  return text(value);
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
  const titles: Record<string, string> = {
    client: "Cliente",
    customer: "Cliente",
    plan: "Plan",
    subscription: "Suscripción",
    charge: "Cargo",
    payment: "Pago",
    payment_method: "Método de pago",
    invoice: "Deuda",
    transaction: "Transacción",
  };
  return titles[resource] ?? resource;
}

const fieldLabels: Record<string, string> = {
  id: "ID",
  uuid: "UUID",
  status: "Estado",
  type: "Tipo",
  name: "Nombre",
  first_name: "Nombre",
  last_name: "Apellido",
  description: "Descripcion",
  email: "Correo electronico",
  mail: "Correo electronico",
  phone: "Telefono",
  phone_number: "Telefono",
  government_id: "RUT",
  social_id_type: "Tipo documento",
  social_id: "RUT documento",
  birth_date: "Fecha nacimiento",
  gender_id: "Genero",
  is_active: "Activo",
  amount: "Monto",
  activation_amount: "Monto activacion",
  currency: "Moneda",
  trial_days: "Dias de prueba",
  num_charges: "Cantidad de cargos",
  frequency_type: "Frecuencia",
  return_url: "URL retorno",
  suscription_url: "URL subscripcion",
  fixed_amount_day_charge: "Dia cobro monto fijo",
  automatic_renewal: "Renovacion automatica",
  show_in_terminal: "Visible en terminal",
  created: "Creado",
  created_at: "Fecha creacion",
  updated: "Actualizado",
  updated_at: "Fecha actualizacion",
  shipping_address: "Direccion de envio",
  plan_id: "ID plan",
  plan_name: "Nombre plan",
  suscription_date: "Fecha subscripcion",
  canceled_at: "Fecha cancelacion",
  renewal: "Renovacion",
  channel: "Canal",
  secondary_status: "Estado secundario",
  last_paid_date: "Último cobro",
  customer: "Cliente",
  customer_id: "ID cliente",
  service_id: "ID servicio",
  subscription: "Subscripcion",
  subscription_id: "ID subscripcion",
  subscription_ids: "IDs subscripciones",
  payment_method: "Metodo de pago",
  bank_name: "Banco",
  card_type: "Tipo tarjeta",
  is_paid: "Pagado",
  due_date: "Fecha limite",
  anchor: "Fecha inicio",
  end_date: "Fecha cancelacion",
  transaction_date: "Fecha transaccion",
  subscriptions: "Subscripciones",
  start: "Fecha inicio",
  end: "Fecha termino",
  rut: "RUT",
  address: "Direccion",
  city: "Ciudad",
  region: "Region",
  country: "Pais",
  postal_code: "Codigo postal",
  private_note: "Nota privada",
};
