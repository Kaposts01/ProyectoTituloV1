import { planIssueText } from "./billingPlan";
import type { DriftDiff, PlanIssue, PlanPreview } from "./types";

export type BillingErrorInfo = {
  status: number | null;
  code: string | null;
  /** Mensaje en español apto para mostrar (nunca texto crudo del proveedor ni PII). */
  message: string;
  drift?: { diff: DriftDiff; newPreview: PlanPreview };
  planErrors?: PlanIssue[];
  policyCode?: string;
  openRequestId?: string;
};

const POLICY_MESSAGES: Record<string, string> = {
  no_approvers: "La política debe tener al menos un rol o un usuario aprobador (AP-23). Agregue uno antes de guardar.",
  no_other_approver: "Sin autoaprobación, sus propias solicitudes no tendrían quién las apruebe: no existe otro aprobador activo distinto de usted (AP-24). Agregue otro aprobador o mantenga la autoaprobación.",
  unknown_role: "Alguno de los roles aprobadores no existe. Revise la selección.",
  unknown_user: "Alguno de los usuarios aprobadores no existe o está inactivo. Revise la selección.",
  dual_insufficient_approvers: "Con doble aprobación hacen falta más aprobadores efectivos y distintos (con autoaprobación basta uno más; sin ella, dos más). Agregue aprobadores o desactive la doble aprobación.",
  invalid_value: "Alguno de los valores indicados no es válido. Revise los campos.",
};

const CODE_MESSAGES: Record<string, string> = {
  subscription_busy: "Otra operación está modificando esta suscripción. Espere unos segundos y reintente.",
  subscription_blocked: "La suscripción tiene cobros pendientes de conciliación; no se puede modificar hasta resolverlos.",
  invalid_request_state: "La solicitud cambió de estado mientras la revisaba. Actualice la bandeja y vuelva a intentarlo.",
  open_request_exists: "Ya existe una solicitud abierta para esta suscripción. Resuélvala o retírela antes de crear otra.",
  request_expired: "La solicitud expiró y ya no se puede aprobar.",
  duplicate_approver: "Usted ya aprobó esta solicitud; se necesita otro aprobador distinto.",
  writes_disabled: "Las escrituras a VirtualPOS están deshabilitadas en este ambiente; no se puede aplicar el cambio.",
  fixed_plan_charge_blocked: "La suscripción usa un plan fijo de VirtualPOS y no admite cobros con otro monto; el cambio está bloqueado.",
  no_changes: "El estado actual ya coincide con lo solicitado: no hay cambios que aplicar.",
  plan_errors: "El plan calculado tiene errores y no se puede crear la solicitud.",
  subscription_not_active: "La suscripción no está activa; no admite cambios de cobro.",
  subscription_not_found: "No se encontró la suscripción indicada.",
  request_not_found: "No se encontró la solicitud. Puede que ya no exista.",
  not_approver: "Usted no es aprobador según la política vigente.",
  self_approval_not_allowed: "La política vigente no permite aprobar sus propias solicitudes.",
  forbidden: "No tiene permiso para realizar esta acción.",
  comment_required: "El comentario es obligatorio.",
  invalid_fields: "Alguno de los datos indicados no es válido. Revise el formulario.",
  apply_failed: "No se pudo aplicar el cambio en VirtualPOS. Los cobros creados se compensaron y el calendario original quedó intacto. La solicitud quedó «fallida»: un aprobador puede reabrirla.",
  reconciliation_required: "La aplicación quedó incompleta y requiere conciliación manual. La solicitud pasó a «requiere conciliación»; un aprobador debe revisarla antes de reabrirla.",
  provider_listing_incomplete: "No se pudo leer completo el listado de cobros del proveedor; reintente. No se calculó ni escribió nada.",
  billing_flow_conflict: "La operación choca con el flujo de solicitudes de cambio de cobro. Actualice y revise el estado de la solicitud.",
  charge_not_found: "Un cobro de la operación ya no existe en VirtualPOS. Actualice y revise el estado de la solicitud.",
  billing_apply_error: "No se pudo aplicar el cambio; revise el estado de la solicitud antes de reintentar.",
  stale_session: "Sesión desactualizada: recargue la página.",
  unparseable_charges: "VirtualPOS devolvió cobros que no se pueden interpretar; no se calculó ni escribió nada.",
  provider_error: "VirtualPOS no respondió correctamente y no se escribió nada. Reintente más tarde.",
};

const STATUS_MESSAGES: Record<number, string> = {
  401: "Su sesión expiró. Vuelva a iniciar sesión.",
  403: "No tiene permiso para realizar esta acción.",
  404: "No se encontró el recurso solicitado.",
  409: "La operación entra en conflicto con el estado actual. Actualice y reintente.",
  422: "Los datos enviados no son válidos. Revise los campos.",
  502: "VirtualPOS no respondió correctamente. Reintente más tarde.",
  503: "El servicio no está disponible temporalmente. Reintente más tarde.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** `count` y `by_status` solo como número y estados normalizados ([a-z0-9_]); nunca texto del proveedor. */
function unparseableMessage(detail: Record<string, unknown>): string {
  const base = CODE_MESSAGES.unparseable_charges;
  const count = typeof detail.count === "number" && Number.isInteger(detail.count) && detail.count >= 0 && detail.count < 1_000_000 ? detail.count : null;
  const states = isRecord(detail.by_status)
    ? Object.entries(detail.by_status)
      .filter(([k, v]) => /^[a-z0-9_]{1,30}$/.test(k) && typeof v === "number" && Number.isInteger(v) && v >= 0)
      .map(([k, v]) => `${k}: ${v}`)
    : [];
  if (count === null && states.length === 0) return base;
  const head = count === null ? "VirtualPOS devolvió cobros que no se pueden interpretar" : `VirtualPOS devolvió ${count} cobros que no se pueden interpretar`;
  return `${head}${states.length ? ` (por estado: ${states.join(", ")})` : ""}; no se calculó ni escribió nada.`;
}

/**
 * Interpreta un error de la API de cambios de cobro. No depende de la clase ApiError (duck typing sobre
 * `status` y `detail`) para poder usarse con mocks. El texto mostrado sale de tablas locales, nunca del servidor.
 */
export function describeBillingError(error: unknown, fallback: string): BillingErrorInfo {
  const status = isRecord(error) && typeof error.status === "number" ? error.status : null;
  const detail = isRecord(error) ? error.detail : undefined;
  if (status === null) {
    const msg = error instanceof Error && error.message.toLowerCase().includes("fetch")
      ? "No se pudo conectar con el servidor. Verifique su conexión."
      : fallback;
    return { status: null, code: null, message: msg };
  }
  const code = isRecord(detail) && typeof detail.code === "string" ? detail.code : null;
  if (code === "policy_invalid") {
    const policyCode = typeof (detail as Record<string, unknown>).policy_code === "string" ? String((detail as Record<string, unknown>).policy_code) : undefined;
    return { status, code, policyCode, message: (policyCode && POLICY_MESSAGES[policyCode]) || "La política no es válida. Revise los campos." };
  }
  if (code === "plan_drift" && isRecord(detail)) {
    const diff = isRecord(detail.diff) ? (detail.diff as DriftDiff) : {};
    const newPreview = isRecord(detail.new_preview) ? (detail.new_preview as PlanPreview) : {};
    return {
      status, code, drift: { diff, newPreview },
      message: "El estado en VirtualPOS cambió desde la aprobación y el plan recalculado difiere del aprobado. Revise las diferencias.",
    };
  }
  const info: BillingErrorInfo = { status, code, message: (code && CODE_MESSAGES[code]) || STATUS_MESSAGES[status] || fallback };
  if (code === "unparseable_charges" && isRecord(detail)) info.message = unparseableMessage(detail);
  if (code === "plan_errors" && isRecord(detail) && Array.isArray(detail.errors)) {
    // El `message` del servidor NO se usa: el texto sale del código estable.
    info.planErrors = detail.errors.filter(isRecord).map((e) => {
      const issueCode = typeof e.code === "string" ? e.code : "";
      return { code: issueCode, message: planIssueText(issueCode, "error"), month: typeof e.month === "string" && /^\d{4}-\d{2}$/.test(e.month) ? e.month : null };
    });
  }
  if (code === "open_request_exists" && isRecord(detail) && typeof detail.open_request_id === "string") info.openRequestId = detail.open_request_id;
  return info;
}
