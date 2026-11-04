import { describe, expect, it } from "vitest";
import { EMPTY_CANCELLATION_FORM, REASON_CODES, validateCancellationForm, type CancellationFormValues } from "./cancellationForm";
import { applyOutcomeNotice, canConfirmApply } from "./cancellationOutcome";
import { searchPath } from "./subscriptionSearch";
import type { ApplyResponse } from "./types";

const base: CancellationFormValues = { ...EMPTY_CANCELLATION_FORM, subscription: "SUB-1", reasonCode: "member_request", comment: "Pedido del socio" };

describe("validación del formulario de baja", () => {
  it("exige suscripción, motivo y comentario (sin espacios)", () => {
    const { errors, body } = validateCancellationForm({ ...EMPTY_CANCELLATION_FORM, comment: "   " });
    expect(body).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["comment", "reasonCode", "subscription"]);
  });

  it("arma el cuerpo de VirtualPOS sin campos de otros canales", () => {
    expect(validateCancellationForm({ ...base, subscription: " SUB-1 " }).body).toEqual({
      channel: "virtualpos1", subscription_external_id: "SUB-1", reason_code: "member_request", reason_comment: "Pedido del socio",
    });
  });

  it("Toku: pausar por defecto; con fecha de término exige la fecha", () => {
    expect(validateCancellationForm({ ...base, channel: "toku" }).body).toMatchObject({ toku_stop_mode: "paused" });
    expect(validateCancellationForm({ ...base, channel: "toku" }).body).not.toHaveProperty("toku_end_date");
    const missing = validateCancellationForm({ ...base, channel: "toku", tokuStopMode: "end_date" });
    expect(missing.body).toBeNull();
    expect(missing.errors.tokuEndDate).toMatch(/fecha de término/);
    expect(validateCancellationForm({ ...base, channel: "toku", tokuStopMode: "end_date", tokuEndDate: "2026-12-31" }).body)
      .toMatchObject({ toku_stop_mode: "end_date", toku_end_date: "2026-12-31" });
  });

  it("Payku exige la confirmación irreversible y solo ahí se envía", () => {
    const denied = validateCancellationForm({ ...base, channel: "payku" });
    expect(denied.body).toBeNull();
    expect(denied.errors.confirmIrreversible).toMatch(/irreversible/);
    expect(validateCancellationForm({ ...base, channel: "payku", confirmIrreversible: true }).body).toMatchObject({ confirm_irreversible: true });
    expect(validateCancellationForm({ ...base, channel: "toku", confirmIrreversible: true }).body).not.toHaveProperty("confirm_irreversible");
  });

  it("TCH: la suscripción es el número de ficha", () => {
    expect(validateCancellationForm({ ...base, channel: "tch", subscription: "ABC" }).errors.subscription).toMatch(/número de ficha/);
    expect(validateCancellationForm({ ...base, channel: "tch", subscription: "12345" }).body).toMatchObject({ subscription_external_id: "12345" });
  });

  it("hay siete motivos fijos", () => {
    expect(REASON_CODES).toHaveLength(7);
  });
});

describe("búsqueda de suscripciones (listas existentes)", () => {
  it("VirtualPOS, Toku y Payku usan el listado de registros de staging con el campo de cada canal", () => {
    expect(searchPath("virtualpos2", "id", " 12 ")).toBe("/api/v1/staging/records?source=virtualpos2&resource_type=subscription&filter_field=id&query=12&limit=8&offset=0");
    expect(searchPath("virtualpos1", "rut", "1")).toContain("filter_field=social_id");
    expect(searchPath("toku", "rut", "1")).toContain("filter_field=client_rut");
    expect(searchPath("payku", "rut", "1")).toContain("filter_field=rut");
  });

  it("TCH usa el listado consolidado de suscripciones", () => {
    expect(searchPath("tch", "id", "99")).toBe("/api/v1/staging/dashboard/general/subscriptions?filter_field=id&query=99&limit=50&offset=0");
  });
});

describe("resultado de aplicar", () => {
  const result = (over: Partial<ApplyResponse>): ApplyResponse => ({
    request_id: "r1", status: "completed", request_status: "completed", already_applied: false, dry_run: false, reason: null, steps: [], plan: null, write_run_id: null, ...over,
  });

  it("baja aplicada, con aviso de pasos manuales", () => {
    expect(applyOutcomeNotice(result({}))).toEqual({ tone: "ok", text: "Baja aplicada." });
    const manual = applyOutcomeNotice(result({ steps: [{ step: "payment_method", status: "manual", code: "VP_NO_PAYMENT_METHOD_API" }] }));
    expect(manual.tone).toBe("warning");
    expect(manual.text).toContain("Quedan pasos manuales por hacer: Medio de pago.");
  });

  it("TCH queda en trámite, no ejecutable y ya aplicada", () => {
    expect(applyOutcomeNotice(result({ status: "pending_external" })).text).toMatch(/en trámite/);
    expect(applyOutcomeNotice(result({ status: "not_executable", reason: "subscription_not_active" })).tone).toBe("warning");
    expect(applyOutcomeNotice(result({ already_applied: true })).text).toMatch(/ya estaba aplicada/);
  });

  it("confirmar exige simulación sin bloqueos y, si es irreversible, la casilla", () => {
    const plan = (over: object) => result({ dry_run: true, status: "dry_run", plan: { channel: "payku", request_status: "approved", preview: {}, steps_done: [], steps_to_run: ["stop_subscription"], blockers: [], invoices_to_void: null, irreversible: false, ...over } });
    expect(canConfirmApply(result({}), true)).toBe(false);
    expect(canConfirmApply(plan({}), false)).toBe(true);
    expect(canConfirmApply(plan({ blockers: ["INVOICE_IN_PROGRESS"] }), true)).toBe(false);
    expect(canConfirmApply(plan({ irreversible: true }), false)).toBe(false);
    expect(canConfirmApply(plan({ irreversible: true }), true)).toBe(true);
  });
});
