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
  /** Cantidad de cobros a cancelar del mes cuando el mes tiene aviso `multiple_pending` y más de un cancel; si no, null. */
  sharedCancels: number | null;
  /** Solo en la primera fila de un mes con aviso `multiple_pending`: ahí va la insignia «Más de un cobro pendiente». */
  showMultiplePending: boolean;
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
    note: a.charge_id ? `Cobro ${a.charge_id}` : "", sharedCancels: null, showMultiplePending: false,
  }));
  (plan.create ?? []).forEach((a, i) => rows.push({
    key: `n-${a.month}-${a.internal_code ?? i}`, month: a.month, kind: "crear", date: a.charge_date, amount: a.amount,
    note: a.internal_code ?? "", sharedCancels: null, showMultiplePending: false,
  }));
  (plan.covered ?? []).forEach((c, i) => rows.push({
    key: `v-${c.month}-${i}`, month: c.month, kind: "cubierto", date: null, amount: null, note: COVERED_REASONS[c.reason] ?? COVERED_DEFAULT,
    sharedCancels: null, showMultiplePending: false,
  }));
  (plan.manual_review ?? []).forEach((m, i) => rows.push({
    key: `r-${m.month}-${i}`, month: m.month, kind: "revision", date: m.target_date, amount: null,
    note: `${m.days_overdue} días de atraso: ${manualReviewReason(m.reason)}`, sharedCancels: null, showMultiplePending: false,
  }));
  (plan.unchanged ?? []).forEach((month, i) => rows.push({
    key: `u-${month}-${i}`, month, kind: "sin_cambio", date: null, amount: null, note: "",
    sharedCancels: null, showMultiplePending: false,
  }));
  rows.sort((a, b) => a.month.localeCompare(b.month) || KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
  // Meses con aviso `multiple_pending` (código estable del servidor; nunca se interpreta el código técnico del cobro).
  const multi = multiplePendingMonths(plan);
  const cancelsByMonth = cancelCountByMonth(plan);
  const badged = new Set<string>();
  for (const r of rows) {
    if (!multi.has(r.month)) continue;
    if (!badged.has(r.month)) { r.showMultiplePending = true; badged.add(r.month); }
    const n = cancelsByMonth.get(r.month) ?? 0;
    if (r.kind === "cancelar" && n > 1) r.sharedCancels = n;
  }
  return rows;
}

const monthKey = (value: string | null | undefined): string | null => {
  const m = typeof value === "string" ? /^(\d{4}-\d{2})/.exec(value) : null;
  return m ? m[1] : null;
};

/** Meses con el aviso `multiple_pending` (más de un cobro pendiente en el mismo mes). */
export function multiplePendingMonths(plan: PlanPreview | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const w of plan?.warnings ?? []) {
    const m = w.code === "multiple_pending" ? monthKey(w.month) : null;
    if (m) out.add(m);
  }
  return out;
}

function cancelCountByMonth(plan: PlanPreview | null | undefined): Map<string, number> {
  const out = new Map<string, number>();
  for (const a of plan?.cancel ?? []) {
    const m = monthKey(a.month);
    if (m) out.set(m, (out.get(m) ?? 0) + 1);
  }
  return out;
}

export type PlanReconciliation = {
  /** Meses del horizonte (de `summary.horizon_start`..`horizon_end`), o null si no se puede derivar. */
  horizonMonths: number | null;
  /** Cancelaciones de meses con `multiple_pending` por encima de la primera de cada mes. */
  extraCancels: number;
  /** Cancelaciones restantes (una por mes del calendario). */
  calendarCancels: number;
  text: string | null;
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function horizonCount(plan: PlanPreview): number | null {
  const a = monthKey(plan.summary?.horizon_start);
  const b = monthKey(plan.summary?.horizon_end);
  if (!a || !b) return null;
  const n = (Number(b.slice(0, 4)) - Number(a.slice(0, 4))) * 12 + Number(b.slice(5)) - Number(a.slice(5)) + 1;
  return n >= 1 && n <= 120 ? n : null;
}

/**
 * Línea de conciliación del plan, calculada SOLO con los arreglos del `plan_preview`. Si el resumen contradice los arreglos
 * (creates/cancels) se omite la frase de reemplazo: solo se muestra lo que es seguro.
 */
export function reconcilePlan(plan: PlanPreview | null | undefined): PlanReconciliation {
  const empty: PlanReconciliation = { horizonMonths: null, extraCancels: 0, calendarCancels: 0, text: null };
  if (!plan || plan.noop) return empty;
  const creates = (plan.create ?? []).length;
  const cancels = (plan.cancel ?? []).length;
  const kept = (plan.kept_due_today ?? []).filter((m): m is string => typeof m === "string").length;
  const covered = (plan.covered ?? []).length;
  const manual = (plan.manual_review ?? []).length;
  const horizon = horizonCount(plan);

  const multi = multiplePendingMonths(plan);
  let extra = 0;
  for (const [month, n] of cancelCountByMonth(plan)) if (multi.has(month) && n > 1) extra += n - 1;
  const calendar = cancels - extra;

  const parts: string[] = [];
  if (horizon !== null) parts.push(`${horizon} ${horizon === 1 ? "mes" : "meses"} en el horizonte`);
  if (kept > 0) parts.push(kept === 1 ? "1 conservado (cobro de hoy)" : `${kept} conservados (cobros de hoy)`);
  if (covered > 0) parts.push(plural(covered, "cubierto", "cubiertos"));
  if (manual > 0) parts.push(`${manual} en revisión manual`);

  const s = plan.summary;
  const totalsAgree = !s || (s.creates === creates && s.cancels === cancels);
  if (totalsAgree && (creates > 0 || cancels > 0)) {
    if (creates > 0 && cancels > 0) {
      const breakdown = extra > 0 && calendar > 0 ? ` (${calendar} del calendario + ${extra} con más de un pendiente en el mes)` : "";
      parts.push(`${creates} ${creates === 1 ? "cobro nuevo reemplaza" : "cobros nuevos reemplazan"} a ${cancels} ${cancels === 1 ? "actual" : "actuales"}${breakdown}`);
    } else if (creates > 0) {
      parts.push(`${plural(creates, "cobro nuevo", "cobros nuevos")}, sin cancelar ninguno`);
    } else {
      parts.push(`${plural(cancels, "cobro se cancela", "cobros se cancelan")} sin reemplazo`);
    }
  }
  return { horizonMonths: horizon, extraCancels: extra, calendarCancels: calendar, text: parts.length ? parts.join(" · ") : null };
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
