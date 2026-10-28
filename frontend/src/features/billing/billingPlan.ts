import type { DriftDiff, PlanPreview } from "./types";
import { formatClp } from "./billingLabels";

export type PlanRowKind = "cancelar" | "crear" | "cubierto" | "revision" | "sin_cambio";

export const PLAN_KIND_LABEL: Record<PlanRowKind, string> = {
  cancelar: "Cancelar", crear: "Crear", cubierto: "Cubierto", revision: "Revisión manual", sin_cambio: "Sin cambio",
};
export const PLAN_KIND_TONE: Record<PlanRowKind, "ok" | "warning" | "error" | "neutral"> = {
  cancelar: "error", crear: "ok", cubierto: "neutral", revision: "warning", sin_cambio: "neutral",
};

export type PlanRow = {
  key: string;
  month: string;
  kind: PlanRowKind;
  date: string | null;
  amount: number | null;
  note: string;
};

const KIND_ORDER: Record<PlanRowKind, number> = { cancelar: 0, crear: 1, cubierto: 2, revision: 3, sin_cambio: 4 };

const COVERED_REASONS: Record<string, string> = {
  pagado: "Mes ya pagado",
  procesando: "Cobro en proceso de pago",
  rechazado: "Cobro rechazado que cubre el mes",
  unknown_status: "Estado de cobro desconocido: el mes se trata como cubierto",
  late_covered: "Atrasado ya cubierto por un cobro vigente",
  already_charged: "Ya cobrado en el mes",
};
const COVERED_DEFAULT = "Mes cubierto";

const MANUAL_REVIEW_REASONS: Record<string, string> = {
  older_than_window: "fuera de la ventana de recuperación automática",
  replacement_outside_month: "el cobro de reemplazo caería en otro mes",
};
/** Motivo de revisión manual por código estable; texto fijo si el código es desconocido (nunca el valor del servidor). */
export function manualReviewReason(code: string | null | undefined): string {
  return (code && MANUAL_REVIEW_REASONS[code]) || "Motivo no reconocido";
}

const WARNING_TEXTS: Record<string, string> = {
  unknown_status: "Estado de cobro desconocido para el CRM: el mes se trató como cubierto.",
  due_today_kept: "Hay un cobro pendiente fechado hoy: no se toca para evitar un doble cobro.",
  multiple_pending: "El mes tiene más de un cobro pendiente; revise cuál corresponde.",
  foreign_manual_kept: "Hay un cobro manual ajeno al CRM: no se toca.",
  pending_same_month: "El mes ya tiene un cobro pendiente; el cobro puntual convive con él.",
};
const ERROR_TEXTS: Record<string, string> = {
  invalid_amount: "El monto debe ser un entero positivo.",
  invalid_charge_day: "El día de cobro debe estar entre 1 y 31.",
  invalid_horizon: "El horizonte debe ser de al menos 1 mes.",
  invalid_window: "La ventana de recuperación no es válida.",
  invalid_effective_month: "El mes de vigencia no es válido.",
  missing_charge_day: "No se pudo determinar el día de cobro: indique el nuevo día.",
  invalid_request_type: "El tipo de cambio no es válido.",
  no_crm_calendar: "La suscripción no tiene un calendario de cobros del CRM que renovar.",
  missing_one_off_date: "El cobro puntual requiere una fecha.",
  past_charge_date: "La fecha del cobro debe ser posterior a hoy.",
};
/** Texto local de un aviso/error del plan por código estable. Nunca se muestra el `message` del servidor. */
export function planIssueText(code: string | null | undefined, kind: "error" | "warning"): string {
  const table = kind === "error" ? ERROR_TEXTS : WARNING_TEXTS;
  return (code && table[code]) || (kind === "error" ? "Error del plan no reconocido." : "Aviso del plan no reconocido.");
}

/** Plan de 12 meses -> filas por mes (cancelaciones antes que creaciones dentro del mismo mes). */
export function buildPlanRows(plan: PlanPreview | null | undefined): PlanRow[] {
  if (!plan) return [];
  const rows: PlanRow[] = [];
  (plan.cancel ?? []).forEach((a, i) => rows.push({
    key: `c-${a.month}-${a.charge_id ?? i}`, month: a.month, kind: "cancelar", date: a.charge_date, amount: a.amount,
    note: a.charge_id ? `Cobro ${a.charge_id}` : "",
  }));
  (plan.create ?? []).forEach((a, i) => rows.push({
    key: `n-${a.month}-${a.internal_code ?? i}`, month: a.month, kind: "crear", date: a.charge_date, amount: a.amount,
    note: a.internal_code ?? "",
  }));
  (plan.covered ?? []).forEach((c, i) => rows.push({
    key: `v-${c.month}-${i}`, month: c.month, kind: "cubierto", date: null, amount: null, note: COVERED_REASONS[c.reason] ?? COVERED_DEFAULT,
  }));
  (plan.manual_review ?? []).forEach((m, i) => rows.push({
    key: `r-${m.month}-${i}`, month: m.month, kind: "revision", date: m.target_date, amount: null,
    note: `${m.days_overdue} días de atraso: ${manualReviewReason(m.reason)}`,
  }));
  (plan.unchanged ?? []).forEach((month, i) => rows.push({
    key: `u-${month}-${i}`, month, kind: "sin_cambio", date: null, amount: null, note: "",
  }));
  return rows.sort((a, b) => a.month.localeCompare(b.month) || KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
}

export type KeptRow = { key: string; month: string; chargeId: string; date: string; amount: number };
export function buildKeptRows(plan: PlanPreview | null | undefined): KeptRow[] {
  return (plan?.kept_automatic_after_horizon ?? [])
    .map((k, i) => ({ key: `k-${k.charge_id}-${i}`, month: k.month, chargeId: k.charge_id, date: k.charge_date, amount: k.amount }))
    .sort((a, b) => a.month.localeCompare(b.month));
}

export function planHasErrors(plan: PlanPreview | null | undefined): boolean {
  return (plan?.errors?.length ?? 0) > 0;
}

function cell(value: unknown): string {
  return value === null || value === undefined ? "—" : String(value);
}

/** Diferencias de un 409 plan_drift como líneas legibles. */
export function describeDrift(diff: DriftDiff | null | undefined): string[] {
  if (!diff) return [];
  const lines: string[] = [];
  // create: [month, charge_date, amount, internal_code]; cancel: [month, charge_id, amount]
  for (const k of diff.create_added ?? []) lines.push(`Se creará un cobro nuevo: ${cell(k[0])}, día ${cell(k[1])}, ${formatClp(Number(k[2]))}`);
  for (const k of diff.create_removed ?? []) lines.push(`Ya no se creará el cobro aprobado: ${cell(k[0])}, día ${cell(k[1])}, ${formatClp(Number(k[2]))}`);
  for (const k of diff.cancel_added ?? []) lines.push(`Se cancelará un cobro adicional: ${cell(k[0])}, cobro ${cell(k[1])}, ${formatClp(Number(k[2]))}`);
  for (const k of diff.cancel_removed ?? []) lines.push(`Ya no se cancelará el cobro aprobado: ${cell(k[0])}, cobro ${cell(k[1])}, ${formatClp(Number(k[2]))}`);
  for (const m of diff.manual_review_added ?? []) lines.push(`El mes ${m} pasa a revisión manual`);
  for (const m of diff.manual_review_removed ?? []) lines.push(`El mes ${m} deja de estar en revisión manual`);
  return lines;
}
