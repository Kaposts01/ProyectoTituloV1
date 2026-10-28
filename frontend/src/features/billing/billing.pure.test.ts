import { describe, expect, it } from "vitest";
import { describeBillingError } from "./billingErrors";
import { buildPolicyPatch, diffPolicyValues, EMPTY_FORM, patchIsEmpty, policyToDraft, validateChangeForm } from "./billingForm";
import { availableActions, expiryText, formatDateTime, statusLabel, statusTone } from "./billingLabels";
import { buildKeptRows, buildPlanRows, describeDrift } from "./billingPlan";
import { EMPTY_FILTERS, listPath, statusesFor, validateFilters } from "./billingQuery";
import type { Policy } from "./types";

const err = (status: number, detail: unknown) => Object.assign(new Error("raw server text with 12.345.678-9"), { status, detail });

describe("etiquetas de estado", () => {
  it("mapea estado a etiqueta y tono", () => {
    expect(statusLabel("requiere_conciliacion")).toBe("Requiere conciliación");
    expect(statusTone("ejecutada")).toBe("ok");
    expect(statusTone("fallida")).toBe("error");
    expect(statusLabel("desconocido")).toBe("desconocido");
  });
  it("expiracion solo para pendientes", () => {
    const now = new Date("2026-03-01T12:00:00Z");
    expect(expiryText({ status: "pendiente", expires_at: "2026-03-06T12:00:00Z" }, now)).toBe("vence en 5 días");
    expect(expiryText({ status: "pendiente", expires_at: "2026-03-01T20:00:00Z" }, now)).toBe("vence hoy");
    expect(expiryText({ status: "pendiente", expires_at: "2026-02-28T12:00:00Z" }, now)).toBe("vencida");
    expect(expiryText({ status: "aprobada", expires_at: "2026-03-06T12:00:00Z" }, now)).toBeNull();
  });
  it("formatea fechas", () => {
    expect(formatDateTime("2026-03-05T14:30:00+00:00")).toBe("2026-03-05 11:30");
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("acciones segun permisos", () => {
  const view = () => false;
  const approver = (p: string) => p === "virtualpos.billing_changes.approve";
  it("solo lectura no ve acciones", () => {
    for (const s of ["pendiente", "aprobada", "fallida"] as const) {
      expect(Object.values(availableActions({ status: s }, view)).some(Boolean)).toBe(false);
    }
  });
  it("aprobador segun estado", () => {
    expect(availableActions({ status: "pendiente" }, approver)).toMatchObject({ approve: true, reject: true, apply: false, reopen: false });
    expect(availableActions({ status: "aprobada" }, approver)).toMatchObject({ apply: true, approve: false });
    expect(availableActions({ status: "fallida" }, approver).reopen).toBe(true);
    expect(availableActions({ status: "requiere_conciliacion" }, approver).reopen).toBe(true);
    expect(availableActions({ status: "ejecutada" }, approver).reopen).toBe(false);
  });
  it("retirar depende del permiso request", () => {
    expect(availableActions({ status: "pendiente" }, (p) => p === "virtualpos.billing_changes.request").withdraw).toBe(true);
  });
});

describe("plan -> filas", () => {
  const plan = {
    cancel: [{ month: "2026-04", charge_date: "2026-04-05", amount: 5000, charge_id: "c1" }],
    create: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000, internal_code: "S-1" }],
    covered: [{ month: "2026-03", reason: "late_covered" }],
    manual_review: [{ month: "2026-02", target_date: "2026-02-05", days_overdue: 20, reason: "late" }],
    unchanged: ["2026-05"],
    kept_automatic_after_horizon: [{ month: "2027-06", charge_id: "k1", charge_date: "2027-06-05", amount: 5000 }],
  };
  it("ordena por mes y cancela antes de crear", () => {
    const rows = buildPlanRows(plan);
    expect(rows.map((r) => `${r.month}:${r.kind}`)).toEqual(["2026-02:revision", "2026-03:cubierto", "2026-04:cancelar", "2026-04:crear", "2026-05:sin_cambio"]);
  });
  it("plan vacio y conservados", () => {
    expect(buildPlanRows(null)).toEqual([]);
    expect(buildKeptRows(plan)[0]).toMatchObject({ chargeId: "k1", amount: 5000 });
  });
  it("describe el drift", () => {
    const lines = describeDrift({ create_added: [["2026-04", "2026-04-10", 8000, "S-1"]], cancel_removed: [["2026-04", "c1", 5000]], manual_review_added: ["2026-06"] });
    expect(lines).toHaveLength(3);
    expect(lines[0]).toContain("$8.000");
    expect(describeDrift(null)).toEqual([]);
  });
});

describe("consulta de la bandeja", () => {
  it("pestanas usan sus estados", () => {
    expect(statusesFor("pending", "")).toContain("fallida");
    expect(statusesFor("pending", "")).not.toContain("ejecutada");
    expect(statusesFor("history", "ejecutada")).toEqual(["ejecutada"]);
    expect(statusesFor("history", "pendiente")).toContain("rechazada");
  });
  it("arma la URL con filtros", () => {
    const uuid = "123e4567-e89b-12d3-a456-426614174000";
    const url = listPath("history", { ...EMPTY_FILTERS, status: "ejecutada", requestType: "change_amount", platform: "virtualpos2", subscription: " S-9 ", requestedBy: uuid, dateFrom: "2026-01-01", dateTo: "2026-02-01" }, 25, 25);
    const p = new URL(url, "http://x").searchParams;
    expect(p.getAll("status")).toEqual(["ejecutada"]);
    expect(Object.fromEntries(p)).toMatchObject({ request_type: "change_amount", platform: "virtualpos2", subscription_id: "S-9", requested_by: uuid, date_from: "2026-01-01", date_to: "2026-02-01", limit: "25", offset: "25" });
  });
  it("descarta solicitante invalido y valida", () => {
    expect(new URL(listPath("pending", { ...EMPTY_FILTERS, requestedBy: "abc" }), "http://x").searchParams.has("requested_by")).toBe(false);
    expect(validateFilters({ ...EMPTY_FILTERS, requestedBy: "abc" })).toMatch(/UUID/);
    expect(validateFilters({ ...EMPTY_FILTERS, dateFrom: "2026-02-02", dateTo: "2026-01-01" })).toBeTruthy();
    expect(validateFilters(EMPTY_FILTERS)).toBeNull();
  });
});

describe("validacion del formulario", () => {
  const now = new Date(2026, 2, 10, 12);
  it("exige suscripcion y monto > 0", () => {
    const r = validateChangeForm({ ...EMPTY_FORM, amount: "0" }, now);
    expect(r.body).toBeNull();
    expect(r.errors.subscription).toBeTruthy();
    expect(r.errors.amount).toBeTruthy();
    expect(validateChangeForm({ ...EMPTY_FORM, subscription: "S1", amount: "-5" }, now).errors.amount).toBeTruthy();
    expect(validateChangeForm({ ...EMPTY_FORM, subscription: "S1", amount: "12.5" }, now).errors.amount).toBeTruthy();
  });
  it("cuerpo de cambio de monto", () => {
    expect(validateChangeForm({ ...EMPTY_FORM, subscription: " S1 ", amount: "9900", comment: " hola " }, now).body).toEqual({
      request_type: "change_amount", platform: "virtualpos1", subscription_external_id: "S1", new_amount: 9900, requester_comment: "hola",
    });
  });
  it("dia entre 1 y 31", () => {
    const base = { ...EMPTY_FORM, requestType: "change_date" as const, subscription: "S1" };
    expect(validateChangeForm({ ...base, chargeDay: "0" }, now).errors.chargeDay).toBeTruthy();
    expect(validateChangeForm({ ...base, chargeDay: "32" }, now).errors.chargeDay).toBeTruthy();
    expect(validateChangeForm({ ...base, chargeDay: "31" }, now).body?.new_charge_day).toBe(31);
  });
  it("cobro puntual exige fecha futura", () => {
    const base = { ...EMPTY_FORM, requestType: "one_off_charge" as const, subscription: "S1", amount: "1000" };
    expect(validateChangeForm({ ...base, chargeDate: "2026-03-10" }, now).errors.chargeDate).toBeTruthy();
    expect(validateChangeForm({ ...base, chargeDate: "" }, now).errors.chargeDate).toBeTruthy();
    expect(validateChangeForm({ ...base, chargeDate: "2026-03-11", taskRef: "T-1" }, now).body).toMatchObject({ new_charge_date: "2026-03-11", task_ref: "T-1" });
  });
  it("renovacion no pide campos extra", () => {
    expect(validateChangeForm({ ...EMPTY_FORM, requestType: "renew_calendar", subscription: "S1" }, now).body).toMatchObject({ request_type: "renew_calendar" });
  });
});

describe("errores de la API", () => {
  it("mapea codigos a mensajes propios, sin texto crudo del servidor", () => {
    const cases: Array<[number, string, RegExp]> = [
      [409, "subscription_busy", /Otra operación/],
      [409, "subscription_blocked", /conciliación/],
      [409, "invalid_request_state", /cambió de estado/],
      [409, "open_request_exists", /solicitud abierta/],
      [403, "writes_disabled", /deshabilitadas/],
      [422, "fixed_plan_charge_blocked", /plan fijo/],
      [502, "apply_failed", /compensaron/],
      [503, "reconciliation_required", /conciliación manual/],
      [502, "provider_error", /no se escribió nada/],
    ];
    for (const [status, code, re] of cases) {
      const info = describeBillingError(err(status, { code, message: "mensaje crudo del proveedor 12.345.678-9" }), "fallback");
      expect(info.message).toMatch(re);
      expect(info.message).not.toContain("12.345.678-9");
    }
  });
  it("plan_drift trae diff y nuevo plan", () => {
    const info = describeBillingError(err(409, { code: "plan_drift", message: "x", diff: { create_added: [["2026-04", "2026-04-10", 1, "c"]] }, new_preview: { create: [] }, retry_with: { accept_drift: true } }), "f");
    expect(info.drift?.diff.create_added).toHaveLength(1);
  });
  it("politica AP-23 y AP-24", () => {
    expect(describeBillingError(err(422, { code: "policy_invalid", policy_code: "no_approvers" }), "f").message).toContain("AP-23");
    expect(describeBillingError(err(422, { code: "policy_invalid", policy_code: "no_other_approver" }), "f").message).toContain("AP-24");
  });
  it("cae al fallback sin detalle ni red", () => {
    expect(describeBillingError(err(500, "texto"), "fallback").message).toBe("fallback");
    expect(describeBillingError(err(403, "Forbidden"), "fb").message).toMatch(/permiso/);
    expect(describeBillingError(new Error("boom"), "fallback").message).toBe("fallback");
  });
  it("plan_errors lista los errores del plan", () => {
    const info = describeBillingError(err(422, { code: "plan_errors", errors: [{ code: "invalid_effective_month", message: "Mes inválido del servidor", month: "2026-05" }] }), "f");
    expect(info.planErrors?.[0].message).toMatch(/mes de vigencia/);
    expect(info.planErrors?.[0].message).not.toContain("servidor");
  });
});

describe("politica", () => {
  const policy: Policy = {
    approver_roles: ["admin"], approver_user_ids: [], self_approval_enabled: true, dual_approval_enabled: false,
    dual_threshold_subscriptions: 10, dual_threshold_variation_pct: 25, renewal_threshold_days: 30, request_expiry_days: 7,
    horizon_months: 12, window_days: 30,
  };
  it("sin cambios el parche queda vacio", () => {
    const { errors, patch } = buildPolicyPatch(policy, policyToDraft(policy));
    expect(errors).toEqual({});
    expect(patchIsEmpty(patch)).toBe(true);
  });
  it("solo envia campos modificados y el motivo", () => {
    const draft = { ...policyToDraft(policy), selfApproval: false, requestExpiryDays: "14", dualThresholdVariationPct: "12,5", reason: " ajuste " };
    expect(buildPolicyPatch(policy, draft).patch).toEqual({ self_approval_enabled: false, request_expiry_days: 14, dual_threshold_variation_pct: 12.5, reason: "ajuste" });
  });
  it("valida rangos", () => {
    const { errors } = buildPolicyPatch(policy, { ...policyToDraft(policy), horizonMonths: "99", windowDays: "0", dualThresholdVariationPct: "-1" });
    expect(Object.keys(errors).sort()).toEqual(["dualThresholdVariationPct", "horizonMonths", "windowDays"]);
  });
  it("diff de auditoria", () => {
    const d = diffPolicyValues({ self_approval_enabled: true, approver_roles: ["admin"] }, { self_approval_enabled: false, approver_roles: ["admin"] });
    expect(d).toEqual([{ field: "self_approval_enabled", label: "Autoaprobación", before: "sí", after: "no" }]);
  });
});
