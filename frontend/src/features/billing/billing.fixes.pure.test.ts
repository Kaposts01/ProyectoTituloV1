import { afterEach, describe, expect, it, vi } from "vitest";
import { describeBillingError } from "./billingErrors";
import { eventNotes, eventTechnical, expiryText, formatDateTime, technicalCode } from "./billingLabels";
import { buildPlanRows, manualReviewReason, planIssueText } from "./billingPlan";
import { applyOutcome } from "./billingResult";
import { noteServerDate, resetServerClock } from "../../serverClock";

const err = (status: number | null, detail: unknown) => Object.assign(new Error("texto crudo 12.345.678-9"), { status, detail });

afterEach(() => { vi.useRealTimers(); resetServerClock(); });

describe("zona horaria (America/Santiago)", () => {
  it("convierte UTC a hora de Chile (verano UTC-3, invierno UTC-4) sin depender de la zona de la maquina", () => {
    expect(formatDateTime("2026-01-15T12:00:00+00:00")).toBe("2026-01-15 09:00");
    expect(formatDateTime("2026-07-15T12:00:00+00:00")).toBe("2026-07-15 08:00");
    expect(formatDateTime("2026-01-15T01:30:00Z")).toBe("2026-01-14 22:30");
  });
  it("fechas sin hora quedan iguales y lo invalido no revienta", () => {
    expect(formatDateTime("2026-03-05")).toBe("2026-03-05");
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("no-es-fecha")).toBe("no-es-fecha");
  });
});

describe("expiracion con la hora del servidor", () => {
  it("usa la cabecera Date del servidor, no el reloj del navegador", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-01T00:00:00Z")); // reloj del navegador atrasado 8 dias
    noteServerDate("Mon, 09 Mar 2026 00:00:00 GMT");
    expect(expiryText({ status: "pendiente", expires_at: "2026-03-12T00:00:00+00:00" })).toBe("vence en 3 días");
    expect(expiryText({ status: "pendiente", expires_at: "2026-03-08T00:00:00+00:00" })).toBe("vencida");
  });
  it("sin cabecera cae al reloj del navegador", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-01T00:00:00Z"));
    noteServerDate(null);
    expect(expiryText({ status: "pendiente", expires_at: "2026-03-04T00:00:00+00:00" })).toBe("vence en 3 días");
  });
});

describe("resultado de aplicar", () => {
  const base = { request_id: "r1", status: "ejecutada", request_status: "ejecutada", already_applied: false, reason: null, drift_accepted: false, plan_summary: null };
  it("usa la forma real del backend (listas)", () => {
    const out = applyOutcome({ ...base, created: [{ month: "2026-04" }, { month: "2026-05" }], cancelled: ["c1"], covered_late_months: [], manual_review_months: ["2026-04", "2026-06"] } as never);
    expect(out.tone).toBe("ok");
    expect(out.message).toBe("Cambio aplicado: 2 cobros creados y 1 cancelados; 2 meses quedan en revisión manual.");
    expect(out.message).not.toContain("object");
  });
  it("sin revision manual no la menciona", () => {
    const out = applyOutcome({ ...base, created: [], cancelled: [], covered_late_months: [], manual_review_months: [] } as never);
    expect(out.message).toBe("Cambio aplicado: 0 cobros creados y 0 cancelados.");
  });
  it("already_applied es informativo", () => {
    expect(applyOutcome({ ...base, already_applied: true, created: [], cancelled: [], covered_late_months: [], manual_review_months: [] } as never).message).toBe("La solicitud ya estaba aplicada.");
  });
  it("no_ejecutable es una advertencia con texto local por codigo", () => {
    const mk = (reason: string | null) => applyOutcome({ ...base, status: "no_ejecutable", request_status: "no_ejecutable", reason, created: [], cancelled: [], covered_late_months: [], manual_review_months: [] } as never);
    expect(mk("subscription_not_active")).toMatchObject({ tone: "warning" });
    expect(mk("subscription_not_active").message).toMatch(/^La solicitud no se pudo ejecutar: la suscripción ya no es ejecutable/);
    expect(mk("plan_changed").message).toMatch(/plan de la suscripción cambió/);
    expect(mk("invalid_plan").message).toMatch(/errores/);
    expect(mk("algo <b>raro</b> 12.345.678-9").message).toBe("La solicitud no se pudo ejecutar: la suscripción ya no es ejecutable.");
    expect(mk(null).tone).toBe("warning");
  });
});

describe("codigos de error nuevos de /billing", () => {
  const cases: Array<[number, Record<string, unknown>, RegExp]> = [
    [502, { code: "provider_listing_incomplete", message: "texto del proveedor 12.345.678-9" }, /No se pudo leer completo el listado de cobros del proveedor; reintente/],
    [409, { code: "billing_flow_conflict", message: "x" }, /flujo de solicitudes/],
    [409, { code: "charge_not_found", message: "x" }, /ya no existe/],
    [409, { code: "billing_apply_error", message: "x" }, /revise el estado de la solicitud/i],
    [409, { code: "subscription_blocked", message: "x" }, /conciliación/],
    [403, { code: "not_approver", message: "x" }, /no es aprobador/],
  ];
  it.each(cases)("%i %o", (status, detail, re) => {
    const info = describeBillingError(err(status, detail), "fb");
    expect(info.message).toMatch(re);
    expect(info.message).not.toContain("12.345.678-9");
    expect(info.code).toBe(detail.code);
  });
  it("unparseable_charges usa count y estados normalizados como numeros/identificadores", () => {
    const info = describeBillingError(err(422, { code: "unparseable_charges", message: "x", count: 3, by_status: { pagado: 2, "<script>alert(1)</script>": 1, ok_1: "12.345.678-9" } }), "fb");
    expect(info.message).toMatch(/3 cobros/);
    expect(info.message).toContain("pagado");
    expect(info.message).not.toContain("script");
    expect(info.message).not.toContain("12.345.678-9");
  });
  it("unparseable_charges con datos raros no revienta ni hace eco", () => {
    const info = describeBillingError(err(422, { code: "unparseable_charges", count: "mil", by_status: "x" }), "fb");
    expect(info.message).toMatch(/no se pueden interpretar/);
    expect(info.message).not.toContain("mil");
  });
  it("dual_insufficient_approvers como policy_code de policy_invalid", () => {
    const info = describeBillingError(err(422, { code: "policy_invalid", policy_code: "dual_insufficient_approvers", message: "x" }), "fb");
    expect(info.policyCode).toBe("dual_insufficient_approvers");
    expect(info.message).toMatch(/doble aprobación/i);
  });
  it("plan_errors se mapea por codigo y nunca muestra el message del servidor", () => {
    const info = describeBillingError(err(422, { code: "plan_errors", errors: [{ code: "past_charge_date", message: "texto servidor 12.345.678-9", month: "2026-04" }, { code: "zzz_nuevo", message: "otro 99" }] }), "fb");
    const all = (info.planErrors ?? []).map((e) => e.message).join("|");
    expect(all).not.toContain("12.345.678-9");
    expect(all).not.toContain("otro 99");
    expect(info.planErrors?.[0].message).toMatch(/fecha/i);
    expect(info.planErrors?.[1].message).toBe("Error del plan no reconocido.");
  });
});

describe("textos del plan por codigo", () => {
  it("avisos conocidos", () => {
    for (const c of ["unknown_status", "multiple_pending", "foreign_manual_kept", "due_today_kept", "pending_same_month"]) {
      const t = planIssueText(c, "warning");
      expect(t).not.toBe("Aviso del plan no reconocido.");
      expect(t).not.toContain(c);
    }
  });
  it("errores conocidos y desconocidos con texto fijo", () => {
    for (const c of ["invalid_amount", "invalid_charge_day", "invalid_horizon", "invalid_window", "invalid_effective_month", "missing_charge_day", "invalid_request_type", "no_crm_calendar", "missing_one_off_date", "past_charge_date"]) {
      expect(planIssueText(c, "error")).not.toBe("Error del plan no reconocido.");
    }
    expect(planIssueText("lo_que_sea", "error")).toBe("Error del plan no reconocido.");
    expect(planIssueText("lo_que_sea", "warning")).toBe("Aviso del plan no reconocido.");
  });
  it("manual_review.reason por codigo y fijo si desconocido", () => {
    expect(manualReviewReason("replacement_outside_month")).toMatch(/otro mes/);
    expect(manualReviewReason("older_than_window")).toMatch(/ventana/);
    expect(manualReviewReason("x 12.345.678-9")).toBe("Motivo no reconocido");
    const rows = buildPlanRows({ manual_review: [{ month: "2026-04", target_date: "2026-04-05", days_overdue: 9, reason: "replacement_outside_month" }, { month: "2026-05", target_date: "2026-05-05", days_overdue: 3, reason: "raro 99" }] });
    expect(rows[0].note).not.toContain("replacement_outside_month");
    expect(rows[1].note).not.toContain("raro");
  });
});

describe("etiqueta tecnica y eventos", () => {
  it("technicalCode acepta etiquetas cortas y descarta texto libre", () => {
    expect(technicalCode("VirtualPOSAPIError E-113")).toBe("VirtualPOSAPIError E-113");
    expect(technicalCode("StuckApplying")).toBe("StuckApplying");
    expect(technicalCode("error_registrado")).toBe("error_registrado");
    expect(technicalCode("juan@correo.cl pagó 12.345.678-9 con tarjeta y falló porque sí y sí")).toBeNull();
    expect(technicalCode(null)).toBeNull();
    expect(technicalCode(42)).toBeNull();
  });
  it("evento reintentada con las claves nuevas y sin ellas", () => {
    const full = eventNotes("reintentada", { to_status: "pendiente", previous_approvals_count: 1, previous_approvals_required: 2, new_approvals_required: 2, comment: "x" });
    expect(full.join(" ")).toMatch(/aprobaciones reiniciadas/i);
    expect(full.join(" ")).toMatch(/Pendiente/);
    expect(eventNotes("reintentada", {}).join(" ")).toMatch(/aprobaciones reiniciadas/i);
    expect(() => eventNotes("reintentada", { previous_approvals_count: "mil", to_status: { a: 1 } })).not.toThrow();
  });
  it("evento de falla muestra la etiqueta tecnica (error / previous_error)", () => {
    expect(eventTechnical({ error: "RuntimeError" })).toEqual([{ label: "Código técnico", code: "RuntimeError" }]);
    expect(eventTechnical({ previous_error: "StuckApplying" })).toEqual([{ label: "Código técnico previo", code: "StuckApplying" }]);
    expect(eventTechnical({ error: "texto libre con RUT 12.345.678-9 y correo a@b.cl y mas texto largo largo largo largo largo" })).toEqual([]);
  });
});
