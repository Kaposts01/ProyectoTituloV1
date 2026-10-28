import type { ChangeBody, Platform, Policy, PolicyPatch, RequestType } from "./types";

/** Valores crudos del formulario de solicitud (todo texto, como llega de los inputs). */
export type ChangeFormValues = {
  requestType: RequestType;
  platform: Platform;
  subscription: string;
  amount: string;
  chargeDay: string;
  chargeDate: string;
  taskRef: string;
  comment: string;
};

export const EMPTY_FORM: ChangeFormValues = {
  requestType: "change_amount", platform: "virtualpos1", subscription: "", amount: "", chargeDay: "", chargeDate: "", taskRef: "", comment: "",
};

export type FormErrors = Partial<Record<"subscription" | "amount" | "chargeDay" | "chargeDate" | "taskRef" | "comment", string>>;

/** Hoy en formato AAAA-MM-DD según la hora local del navegador. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function parseInteger(value: string): number | null {
  const v = value.trim();
  if (!/^\d+$/.test(v)) return null;
  const n = Number(v);
  return Number.isSafeInteger(n) ? n : null;
}

/** Valida y arma el cuerpo de la API. Devuelve errores por campo o el cuerpo listo para /changes/preview. */
export function validateChangeForm(values: ChangeFormValues, now: Date = new Date()): { errors: FormErrors; body: ChangeBody | null } {
  const errors: FormErrors = {};
  const subscription = values.subscription.trim();
  if (!subscription) errors.subscription = "Indique el ID de la suscripción.";
  else if (subscription.length > 255) errors.subscription = "El ID es demasiado largo.";

  const body: ChangeBody = { request_type: values.requestType, platform: values.platform, subscription_external_id: subscription };

  if (values.requestType === "change_amount" || values.requestType === "one_off_charge") {
    const amount = parseInteger(values.amount);
    if (amount === null || amount < 1) errors.amount = "Ingrese un monto entero mayor a 0.";
    else if (amount > 10 ** 10) errors.amount = "El monto es demasiado alto.";
    else body.new_amount = amount;
  }
  if (values.requestType === "change_date") {
    const day = parseInteger(values.chargeDay);
    if (day === null || day < 1 || day > 31) errors.chargeDay = "Ingrese un día entre 1 y 31.";
    else body.new_charge_day = day;
  }
  if (values.requestType === "one_off_charge") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(values.chargeDate)) errors.chargeDate = "Indique la fecha del cobro.";
    else if (values.chargeDate <= todayIso(now)) errors.chargeDate = "La fecha del cobro puntual debe ser posterior a hoy.";
    else body.new_charge_date = values.chargeDate;
    const ref = values.taskRef.trim();
    if (ref.length > 100) errors.taskRef = "La referencia de tarea admite hasta 100 caracteres.";
    else if (ref) body.task_ref = ref;
  }
  const comment = values.comment.trim();
  if (comment.length > 2000) errors.comment = "El comentario admite hasta 2000 caracteres.";
  else if (comment) body.requester_comment = comment;

  return { errors, body: Object.keys(errors).length ? null : body };
}

// ---------------------------------------------------------------- política

export type PolicyDraft = {
  approverRoles: string[];
  approverUserIds: string[];
  selfApproval: boolean;
  dualApproval: boolean;
  dualThresholdSubscriptions: string;
  dualThresholdVariationPct: string;
  renewalThresholdDays: string;
  requestExpiryDays: string;
  horizonMonths: string;
  windowDays: string;
  reason: string;
};

export function policyToDraft(p: Policy): PolicyDraft {
  return {
    approverRoles: [...p.approver_roles].sort(),
    approverUserIds: [...p.approver_user_ids].sort(),
    selfApproval: p.self_approval_enabled,
    dualApproval: p.dual_approval_enabled,
    dualThresholdSubscriptions: String(p.dual_threshold_subscriptions),
    dualThresholdVariationPct: String(p.dual_threshold_variation_pct),
    renewalThresholdDays: String(p.renewal_threshold_days),
    requestExpiryDays: String(p.request_expiry_days),
    horizonMonths: String(p.horizon_months),
    windowDays: String(p.window_days),
    reason: "",
  };
}

export const POLICY_FIELD_LABELS: Record<string, string> = {
  approver_roles: "Roles aprobadores",
  approver_user_ids: "Usuarios aprobadores",
  self_approval_enabled: "Autoaprobación",
  dual_approval_enabled: "Doble aprobación",
  dual_threshold_subscriptions: "Umbral de suscripciones (doble aprobación)",
  dual_threshold_variation_pct: "Umbral de variación % (doble aprobación)",
  renewal_threshold_days: "Días mínimos para renovar (N)",
  request_expiry_days: "Días de expiración de solicitudes",
  horizon_months: "Horizonte (meses)",
  window_days: "Ventana (días)",
};

type IntRule = { key: keyof PolicyDraft; label: string; min: number; max: number; field: keyof Policy };
const INT_RULES: IntRule[] = [
  { key: "dualThresholdSubscriptions", label: "El umbral de suscripciones", min: 1, max: 100_000, field: "dual_threshold_subscriptions" },
  { key: "renewalThresholdDays", label: "Los días de renovación", min: 1, max: 3650, field: "renewal_threshold_days" },
  { key: "requestExpiryDays", label: "Los días de expiración", min: 1, max: 365, field: "request_expiry_days" },
  { key: "horizonMonths", label: "El horizonte", min: 1, max: 60, field: "horizon_months" },
  { key: "windowDays", label: "La ventana", min: 1, max: 365, field: "window_days" },
];

export type PolicyErrors = Partial<Record<keyof PolicyDraft, string>>;

/** Valida el borrador y devuelve el parche con SOLO los campos modificados (la API acepta parches parciales). */
export function buildPolicyPatch(original: Policy, draft: PolicyDraft): { errors: PolicyErrors; patch: PolicyPatch } {
  const errors: PolicyErrors = {};
  const patch: PolicyPatch = {};
  const sameList = (a: string[], b: string[]) => a.length === b.length && [...a].sort().every((x, i) => x === [...b].sort()[i]);

  if (!sameList(draft.approverRoles, original.approver_roles)) patch.approver_roles = [...draft.approverRoles];
  if (!sameList(draft.approverUserIds, original.approver_user_ids)) patch.approver_user_ids = [...draft.approverUserIds];
  if (draft.selfApproval !== original.self_approval_enabled) patch.self_approval_enabled = draft.selfApproval;
  if (draft.dualApproval !== original.dual_approval_enabled) patch.dual_approval_enabled = draft.dualApproval;

  for (const rule of INT_RULES) {
    const raw = String(draft[rule.key]).trim();
    const n = /^\d+$/.test(raw) ? Number(raw) : NaN;
    if (!Number.isInteger(n) || n < rule.min || n > rule.max) {
      errors[rule.key] = `${rule.label} debe ser un entero entre ${rule.min} y ${rule.max}.`;
    } else if (n !== original[rule.field]) {
      (patch as Record<string, unknown>)[rule.field] = n;
    }
  }
  const pctRaw = draft.dualThresholdVariationPct.trim().replace(",", ".");
  const pct = /^\d+(\.\d{1,2})?$/.test(pctRaw) ? Number(pctRaw) : NaN;
  if (!Number.isFinite(pct) || pct < 0 || pct > 9999.99) errors.dualThresholdVariationPct = "La variación debe estar entre 0 y 9999,99 (máximo 2 decimales).";
  else if (pct !== original.dual_threshold_variation_pct) patch.dual_threshold_variation_pct = pct;

  if (draft.reason.trim().length > 1000) errors.reason = "El motivo admite hasta 1000 caracteres.";
  else if (draft.reason.trim() && Object.keys(patch).length) patch.reason = draft.reason.trim();
  return { errors, patch };
}

export function patchIsEmpty(patch: PolicyPatch): boolean {
  return Object.keys(patch).filter((k) => k !== "reason").length === 0;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "ninguno";
  if (typeof value === "boolean") return value ? "sí" : "no";
  if (value === null || value === undefined) return "—";
  return String(value);
}

/** Cambios entre dos snapshots de política, para el historial. */
export function diffPolicyValues(before: Record<string, unknown> | null, after: Record<string, unknown> | null): Array<{ field: string; label: string; before: string; after: string }> {
  const keys = Object.keys(POLICY_FIELD_LABELS).filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]));
  return keys.map((k) => ({ field: k, label: POLICY_FIELD_LABELS[k], before: formatValue(before?.[k]), after: formatValue(after?.[k]) }));
}
