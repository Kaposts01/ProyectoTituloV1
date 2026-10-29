import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), refresh: vi.fn() }));
vi.mock("../../api", () => ({ getJson: mocks.getJson, postJson: mocks.postJson }));
vi.mock("../shared/utils", () => ({ refreshCsrfToken: mocks.refresh }));

import { es } from "../../i18n/es";
import { label } from "../../i18n/label";
import * as api from "./cancellationsApi";
import { describeCancellationError } from "./cancellationErrors";
import { actionText, availableActions, canWithdraw, channelText, codeText, eventText, manualText, reasonText, statusText, statusTone, stepStatusText, stepText } from "./cancellationLabels";
import { EMPTY_CANCELLATION_FILTERS, listPath, statusesFor, TAB_STATUSES } from "./cancellationsQuery";
import { PERM_CANCELLATION_APPROVE, PERM_CANCELLATION_REQUEST } from "./types";

const body = { channel: "toku", subscription_external_id: "SUB-1", reason_code: "member_request", reason_comment: "Pedido" } as const;

beforeEach(() => {
  mocks.getJson.mockReset().mockResolvedValue({});
  mocks.postJson.mockReset().mockResolvedValue({});
  mocks.refresh.mockReset().mockResolvedValue(undefined);
});

describe("catálogo de bajas", () => {
  it("cubre todos los estados, motivos, pasos y eventos del modelo en español", () => {
    expect(statusText("pending")).toBe("Pendiente de aprobación");
    expect(statusText("pending_external")).toBe("En trámite");
    expect(statusText("requires_reconciliation")).toBe("Requiere conciliación");
    expect(statusText("not_executable")).toBe("No ejecutable");
    for (const status of ["pending", "approved", "applying", "pending_external", "completed", "failed", "requires_reconciliation", "rejected", "withdrawn", "expired", "not_executable"]) {
      expect(statusText(status), status).not.toMatch(/^Desconocido/);
    }
    for (const reason of ["member_request", "payment_failure", "duplicate_subscription", "deceased", "fraud_suspected", "organization_decision", "other"]) {
      expect(reasonText(reason), reason).not.toMatch(/^Desconocido/);
    }
    for (const step of ["stop_subscription", "cancel_pending_charges", "payment_method", "register_internal", "bank_mandate"]) {
      expect(stepText(step), step).not.toMatch(/^Desconocido/);
    }
    for (const status of ["pending", "done", "failed", "skipped", "manual"]) expect(stepStatusText(status)).not.toMatch(/^Desconocido/);
    for (const event of ["created", "approved", "self_approved", "rejected", "withdrawn", "expired", "applying", "step_completed", "step_failed", "step_manual", "completed", "failed", "requires_reconciliation", "not_executable", "reopened", "pending_external", "closed_by_report"]) {
      expect(eventText(event), event).not.toMatch(/^Desconocido/);
    }
    expect(channelText("tch")).toBe("TCH");
    expect(actionText("pause_subscription")).toBe("Pausar la suscripción (reversible)");
  });

  it("un valor nuevo del API se ve como «Desconocido (valor)»", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(statusText("archived")).toBe("Desconocido (archived)");
    expect(codeText("NEW_CODE")).toBe("Desconocido (NEW_CODE)");
    expect(manualText("X_Y")).toBe("Desconocido (X_Y)");
    expect(label("cancellationReason", "otro_motivo")).toBe("Desconocido (otro_motivo)");
    warn.mockRestore();
  });

  it("los pasos manuales tienen instrucción para cada canal", () => {
    for (const code of ["VP_NO_PAYMENT_METHOD_API", "TOKU_PAYMENT_METHOD_DECISION_PENDING", "PAYKU_CARD_DELETE_Q09_UNVALIDATED", "TCH_BANK_MANDATE_OUTSIDE_CRM", "no_api", "decision_pending", "q09_unvalidated", "bank_mandate_outside_crm", "remove_payment_method_manually", "revoke_bank_mandate_manually"]) {
      expect(manualText(code), code).not.toMatch(/^Desconocido/);
    }
  });

  it("los tonos distinguen lo que necesita atención", () => {
    expect(statusTone("failed")).toBe("error");
    expect(statusTone("requires_reconciliation")).toBe("error");
    expect(statusTone("pending_external")).toBe("warning");
    expect(statusTone("completed")).toBe("ok");
    expect(statusTone("lo-que-sea")).toBe("neutral");
  });

  it("ningún texto del dominio de errores repite valores de ejemplo ni está vacío", () => {
    for (const text of Object.values(es.cancellationError)) expect(text.length).toBeGreaterThan(10);
  });
});

describe("errores del API en español, sin eco del proveedor", () => {
  it.each([
    ["INVOICE_IN_PROGRESS", 409, /factura en proceso de cobro/],
    ["INVOICE_LIST_FAILED", 502, /No se pudieron leer las facturas/],
    ["INVOICE_VOID_FAILED", 502, /No se pudo anular una factura/],
    ["apply_failed", 502, /fallida/],
    ["reconciliation_required", 503, /requiere conciliación/],
    ["open_request_exists", 409, /Ya existe una solicitud de baja abierta/],
    ["invalid_request_state", 409, /cambió de estado/],
    ["subscription_busy", 409, /Otra operación/],
    ["writes_disabled", 403, /deshabilitadas/],
    ["not_approver", 403, /no tiene permiso para aprobar/i],
    ["self_approval_not_allowed", 403, /no permite aprobar sus propias/],
    ["irreversibility_confirmation_required", 422, /irreversible/],
    ["comment_required", 422, /comentario es obligatorio/],
    ["subscription_not_active", 422, /ya está dada de baja/],
    ["subscription_not_found", 404, /No se encontró la suscripción/],
    ["request_not_found", 404, /No se encontró la solicitud/],
  ])("%s se muestra en español", (code, status, expected) => {
    const info = describeCancellationError({ status, detail: { code, message: "Texto del servidor" } }, "respaldo");
    expect(info.code).toBe(code);
    expect(info.message).toMatch(expected);
    expect(info.message).not.toContain("Texto del servidor");
    expect(info.message).not.toMatch(/[A-Z]{3,}_[A-Z_]+/);
  });

  it("no repite valores del proveedor que viajen en el detalle", () => {
    const info = describeCancellationError({
      status: 502,
      detail: { code: "apply_failed", message: "Toku dijo: tarjeta 4111111111111111 rechazada", provider_error: "secreto-xyz", step: "stop_subscription", step_code: "PROVIDER_ERROR" },
    }, "respaldo");
    expect(info.message).not.toMatch(/4111|secreto|Toku dijo/);
    expect(info.step).toBe("stop_subscription");
    expect(info.stepCode).toBe("PROVIDER_ERROR");
  });

  it("descarta paso y código de paso que no estén en el catálogo, y ids que no sean UUID", () => {
    const info = describeCancellationError({ status: 502, detail: { code: "apply_failed", step: "<script>", step_code: "texto libre del proveedor" } }, "respaldo");
    expect(info.step).toBeUndefined();
    expect(info.stepCode).toBeUndefined();
    expect(describeCancellationError({ status: 409, detail: { code: "open_request_exists", open_request_id: "no-es-uuid" } }, "x").openRequestId).toBeUndefined();
    expect(describeCancellationError({ status: 409, detail: { code: "open_request_exists", open_request_id: "11111111-1111-4111-8111-111111111111" } }, "x").openRequestId)
      .toBe("11111111-1111-4111-8111-111111111111");
  });

  it("sin código usa el texto del estado HTTP; sin estado, el de red o el de respaldo", () => {
    expect(describeCancellationError({ status: 502, detail: "Bad gateway del proveedor" }, "respaldo").message).toMatch(/proveedor no respondió/);
    expect(describeCancellationError({ status: 500, detail: "boom" }, "respaldo").message).toBe("respaldo");
    expect(describeCancellationError(new TypeError("Failed to fetch"), "respaldo").message).toMatch(/No se pudo conectar/);
    expect(describeCancellationError(new Error("otra cosa"), "respaldo").message).toBe("respaldo");
  });

  it("un código desconocido cae al texto del estado HTTP, nunca al texto del servidor", () => {
    const info = describeCancellationError({ status: 409, detail: { code: "algo_nuevo", message: "Texto en inglés" } }, "x");
    expect(info.message).toMatch(/conflicto/);
  });
});

describe("rutas y consultas", () => {
  it("las pestañas agrupan los estados del modelo sin repetirlos", () => {
    const all = Object.values(TAB_STATUSES).flat();
    expect(new Set(all).size).toBe(all.length);
    expect(all).toHaveLength(11);
    expect(TAB_STATUSES.pending).toEqual(["pending", "approved"]);
  });

  it("arma la consulta con estados repetidos, canal, límite y desplazamiento", () => {
    expect(listPath("pending", EMPTY_CANCELLATION_FILTERS, 0, 25)).toBe("/api/v1/cancellations?status=pending&status=approved&limit=25&offset=0");
    expect(listPath("running", { status: "failed", channel: "toku" }, 25, 25)).toBe("/api/v1/cancellations?status=failed&channel=toku&limit=25&offset=25");
    expect(statusesFor("history", "pending")).toEqual(TAB_STATUSES.history);
  });
});

describe("cliente HTTP", () => {
  it("lee la bandeja, el detalle y los eventos con GET", async () => {
    await api.fetchCancellations("pending", EMPTY_CANCELLATION_FILTERS, 0, 25);
    await api.fetchCancellation("a/b");
    await api.fetchCancellationEvents("abc");
    expect(mocks.getJson.mock.calls.map((c) => c[0])).toEqual([
      "/api/v1/cancellations?status=pending&status=approved&limit=25&offset=0",
      "/api/v1/cancellations/a%2Fb",
      "/api/v1/cancellations/abc/events",
    ]);
  });

  it("vista previa y creación envían el cuerpo tal cual", async () => {
    await api.previewCancellation(body);
    await api.createCancellation(body);
    expect(mocks.postJson.mock.calls).toEqual([["/api/v1/cancellations/preview", body], ["/api/v1/cancellations", body]]);
  });

  it("aprobar, rechazar, retirar y reabrir envían el comentario según corresponda", async () => {
    await api.approveCancellation("r1");
    await api.approveCancellation("r1", "ok");
    await api.rejectCancellation("r1", "no");
    await api.withdrawCancellation("r1");
    await api.withdrawCancellation("r1", "ya no");
    await api.reopenCancellation("r1", "revisado");
    expect(mocks.postJson.mock.calls).toEqual([
      ["/api/v1/cancellations/r1/approve", undefined],
      ["/api/v1/cancellations/r1/approve", { comment: "ok" }],
      ["/api/v1/cancellations/r1/reject", { comment: "no" }],
      ["/api/v1/cancellations/r1/withdraw", undefined],
      ["/api/v1/cancellations/r1/withdraw", { comment: "ya no" }],
      ["/api/v1/cancellations/r1/reopen", { comment: "revisado" }],
    ]);
  });

  it("aplicar envía dry_run explícito", async () => {
    await api.applyCancellation("r1", true);
    await api.applyCancellation("r1", false);
    expect(mocks.postJson.mock.calls).toEqual([
      ["/api/v1/cancellations/r1/apply", { dry_run: true }],
      ["/api/v1/cancellations/r1/apply", { dry_run: false }],
    ]);
  });

  it("ante un 403 de CSRF (sin código) refresca el token y reintenta UNA vez", async () => {
    mocks.postJson.mockRejectedValueOnce({ status: 403, detail: "Invalid CSRF token" }).mockResolvedValueOnce({ id: "r1" });
    await expect(api.approveCancellation("r1")).resolves.toEqual({ id: "r1" });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(mocks.postJson).toHaveBeenCalledTimes(2);
  });

  it("si el CSRF sigue fallando devuelve «stale_session»", async () => {
    mocks.postJson.mockRejectedValue({ status: 403, detail: "Invalid CSRF token" });
    await expect(api.approveCancellation("r1")).rejects.toMatchObject({ status: 403, detail: { code: "stale_session" } });
  });

  it("el CSRF obsoleto que ahora llega como {code: invalid_csrf_token} también refresca y reintenta UNA vez", async () => {
    const stale = { status: 403, detail: { code: "invalid_csrf_token", message: "Sesión desactualizada. Recarga la página e inténtalo de nuevo." } };
    mocks.postJson.mockRejectedValueOnce(stale).mockResolvedValueOnce({ id: "r1" });
    await expect(api.approveCancellation("r1")).resolves.toEqual({ id: "r1" });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(mocks.postJson).toHaveBeenCalledTimes(2);
  });

  it("si el CSRF {code: invalid_csrf_token} sigue fallando devuelve «stale_session»", async () => {
    mocks.postJson.mockRejectedValue({ status: 403, detail: { code: "invalid_csrf_token", message: "x" } });
    await expect(api.approveCancellation("r1")).rejects.toMatchObject({ status: 403, detail: { code: "stale_session" } });
    expect(mocks.postJson).toHaveBeenCalledTimes(2);
  });

  it("un 403 con código estructurado (not_approver) no se reintenta", async () => {
    mocks.postJson.mockRejectedValue({ status: 403, detail: { code: "not_approver" } });
    await expect(api.approveCancellation("r1")).rejects.toMatchObject({ status: 403 });
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.postJson).toHaveBeenCalledTimes(1);
  });
});

describe("acciones según estado y permisos", () => {
  const perms = { request: PERM_CANCELLATION_REQUEST, approve: PERM_CANCELLATION_APPROVE };
  const canOf = (list: string[]) => (p: string) => list.includes(p);

  it("el aprobador decide los pendientes y aplica los aprobados", () => {
    const can = canOf([PERM_CANCELLATION_APPROVE]);
    expect(availableActions({ status: "pending" }, can, perms)).toEqual({ approve: true, reject: true, withdraw: false, reopen: false, apply: false });
    expect(availableActions({ status: "approved" }, can, perms)).toMatchObject({ apply: true, approve: false });
    expect(availableActions({ status: "failed" }, can, perms).reopen).toBe(true);
    expect(availableActions({ status: "requires_reconciliation" }, can, perms).reopen).toBe(true);
    expect(availableActions({ status: "completed" }, can, perms)).toEqual({ approve: false, reject: false, withdraw: false, reopen: false, apply: false });
  });

  it("quien solo solicita puede retirar lo pendiente y nada más", () => {
    const can = canOf([PERM_CANCELLATION_REQUEST]);
    expect(availableActions({ status: "pending" }, can, perms)).toEqual({ approve: false, reject: false, withdraw: true, reopen: false, apply: false });
  });

  it("quien solo ve no tiene acciones", () => {
    const can = canOf(["subscriptions.cancellation.view"]);
    for (const status of ["pending", "approved", "failed", "requires_reconciliation"]) {
      expect(Object.values(availableActions({ status }, can, perms)).some(Boolean)).toBe(false);
    }
  });

  it("retirar: el solicitante o un admin", () => {
    expect(canWithdraw({ requested_by_user_id: "u1" }, "u1", false)).toBe(true);
    expect(canWithdraw({ requested_by_user_id: "u1" }, "u2", false)).toBe(false);
    expect(canWithdraw({ requested_by_user_id: "u1" }, "u2", true)).toBe(true);
    expect(canWithdraw({ requested_by_user_id: "u1" }, undefined, false)).toBe(true);
  });
});
