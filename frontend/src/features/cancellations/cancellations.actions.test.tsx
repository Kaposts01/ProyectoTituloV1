import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn() }));
vi.mock("../../api", () => ({ getJson: mocks.getJson, postJson: mocks.postJson, friendlyError: (_e: unknown, f: string) => f }));
vi.mock("../shared/utils", () => ({ refreshCsrfToken: vi.fn() }));

import { CancellationsInbox } from "./CancellationsInbox";
import type { ApplyResponse, CancellationDetail, CancellationRequest, CascadePreview } from "./types";

const VIEW = "subscriptions.cancellation.view";
const REQUEST = "subscriptions.cancellation.request";
const APPROVE = "subscriptions.cancellation.approve";
const canOf = (perms: string[]) => (p: string) => perms.includes(p);
const apiError = (status: number, detail: unknown) => Object.assign(new Error("texto crudo del servidor"), { status, detail });

function row(over: Partial<CancellationRequest> = {}): CancellationRequest {
  return {
    id: "r1", channel: "toku", subscription_external_id: "SUB-100", status: "pending", reason_code: "member_request",
    reason_comment: "Pedido del socio", requested_by_user_id: "u1", requested_by: "ana", approved_by_user_id: null, approved_by: null,
    self_approved: false, approvals_required: 1, approvals_count: 0, decided_at: null, decision_comment: null,
    options: { toku_stop_mode: "paused" }, requires_reconciliation: false, write_run_id: null,
    expires_at: "2026-11-30T10:00:00+00:00", executed_at: null, error_message: null, created_at: "2026-10-01T10:00:00+00:00", updated_at: null, ...over,
  };
}

const PREVIEW: CascadePreview = {
  channel: "toku", subscription_status: "ACTIVE", irreversible: false, pending_charges: 1, pending_charge_ids: ["INV-1"], processing_charges: 0,
  in_progress_invoices: 0, blockers: [], source: "local_last_sync",
  steps: [
    { step: "stop_subscription", action: "pause_subscription", reversible: true },
    { step: "cancel_pending_charges", action: "void_invoices", count: 1 },
    { step: "payment_method", action: "manual_task", reason: "decision_pending" },
  ],
};

function detail(over: Partial<CancellationDetail> = {}): CancellationDetail {
  return { ...row(), cascade_preview: PREVIEW, steps: [], rules_snapshot: {}, events: [], ...over } as CancellationDetail;
}

const PLAN = (over: object = {}): ApplyResponse => ({
  request_id: "r1", status: "dry_run", request_status: "approved", already_applied: false, dry_run: true, reason: null, steps: [], write_run_id: null,
  plan: { channel: "toku", request_status: "approved", preview: PREVIEW, steps_done: [], steps_to_run: ["stop_subscription", "cancel_pending_charges", "payment_method"], blockers: [], invoices_to_void: 1, irreversible: false, ...over },
});

let listItems: CancellationRequest[] = [];
let detailData: CancellationDetail = detail();

beforeEach(() => {
  mocks.getJson.mockReset();
  mocks.postJson.mockReset();
  listItems = [row()];
  detailData = detail();
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/cancellations?")) return { items: listItems, total: listItems.length, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/cancellations/")) return detailData;
    if (path.startsWith("/api/v1/staging/records?")) {
      return { items: [{ id: "x", source: "virtualpos1", resource_type: "subscription", external_id: "VP-77", payload: { status: "ACTIVE" }, client_name: "Cliente Sintético" }], total: 1, offset: 0, limit: 8 };
    }
    if (path.startsWith("/api/v1/staging/dashboard/general/subscriptions")) {
      return { items: [
        { id: "9001", platform: "Toku", rut: "", client: "Otro", status: "ACTIVE" },
        { id: "9002", platform: "TCH", rut: "", client: "Cliente TCH", status: "VIGENTE" },
      ], total: 2, offset: 0, limit: 50 };
    }
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de baja de la suscripción SUB-100/ }));
  await screen.findByRole("heading", { name: /SUB-100/ });
}
const dialog = () => screen.getByRole("dialog");
const postCalls = () => mocks.postJson.mock.calls.map((c) => [c[0], c[1]]);

describe("Solicitar baja", () => {
  it("el botón solo aparece con el permiso de solicitar", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Solicitar baja" })).toBeNull();
    cleanup();
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    expect(await screen.findByRole("button", { name: "Solicitar baja" })).toBeTruthy();
  });

  it("es un diálogo accesible; los errores se anuncian y nada se envía sin datos", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Solicitar baja" }));
    expect(dialog().getAttribute("aria-modal")).toBe("true");
    expect(dialog().getAttribute("aria-labelledby")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Solicitar baja de suscripción" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enviar solicitud" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    const alerts = (await screen.findAllByRole("alert")).map((a) => a.textContent);
    expect(alerts).toEqual(expect.arrayContaining(["Elija el motivo de la baja.", "El comentario del motivo es obligatorio.", "Indique la suscripción que se dará de baja."]));
    expect(screen.getByLabelText(/Motivo de la baja/).getAttribute("aria-invalid")).toBe("true");
    expect(mocks.postJson).not.toHaveBeenCalled();
  });

  it("Escape cierra el diálogo y devuelve el foco al botón", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    const opener = await screen.findByRole("button", { name: "Solicitar baja" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.keyDown(dialog(), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("busca suscripciones en las listas existentes y rellena el identificador", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Solicitar baja" }));
    fireEvent.change(screen.getByLabelText("Texto a buscar"), { target: { value: "VP-7" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar suscripciones" }));
    const results = await screen.findByRole("list", { name: "Resultados de la búsqueda" });
    expect(mocks.getJson.mock.calls.map((c) => String(c[0]))).toContain("/api/v1/staging/records?source=virtualpos1&resource_type=subscription&filter_field=id&query=VP-7&limit=8&offset=0");
    expect(results.textContent).toContain("VP-77");
    expect(results.textContent).toContain("Activa");
    fireEvent.click(within(results).getByRole("button"));
    expect((screen.getByLabelText("ID de la suscripción") as HTMLInputElement).value).toBe("VP-77");
  });

  it("TCH busca en el listado consolidado y solo ofrece fichas de TCH", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Solicitar baja" }));
    fireEvent.change(within(dialog()).getByLabelText("Canal"), { target: { value: "tch" } });
    expect(screen.getByLabelText("Número de ficha", { selector: "input" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Texto a buscar"), { target: { value: "900" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar suscripciones" }));
    const results = await screen.findByRole("list", { name: "Resultados de la búsqueda" });
    expect(within(results).getAllByRole("button")).toHaveLength(1);
    expect(results.textContent).toContain("9002");
  });

  it("Payku exige la confirmación irreversible; Toku ofrece pausar o fecha de término", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Solicitar baja" }));
    fireEvent.change(within(dialog()).getByLabelText("Canal"), { target: { value: "toku" } });
    expect(screen.getByLabelText("Forma de baja en Toku")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Forma de baja en Toku"), { target: { value: "end_date" } });
    expect(screen.getByLabelText("Fecha de término")).toBeTruthy();
    fireEvent.change(within(dialog()).getByLabelText("Canal"), { target: { value: "payku" } });
    expect(screen.queryByLabelText("Forma de baja en Toku")).toBeNull();
    const confirm = screen.getByRole("checkbox", { name: /baja en Payku es irreversible/ });
    expect((confirm as HTMLInputElement).checked).toBe(false);
    fireEvent.change(screen.getByLabelText(/Motivo de la baja/), { target: { value: "deceased" } });
    fireEvent.change(screen.getByLabelText(/Comentario del motivo/), { target: { value: "Aviso de la familia" } });
    fireEvent.change(screen.getByLabelText("ID de la suscripción"), { target: { value: "PK-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    expect((await screen.findAllByRole("alert")).map((a) => a.textContent)).toContain("Debe confirmar de forma explícita que la baja en Payku es irreversible.");
    expect(mocks.postJson).not.toHaveBeenCalled();
  });

  async function fillValid() {
    fireEvent.click(await screen.findByRole("button", { name: "Solicitar baja" }));
    fireEvent.change(within(dialog()).getByLabelText("Canal"), { target: { value: "toku" } });
    fireEvent.change(screen.getByLabelText(/Motivo de la baja/), { target: { value: "member_request" } });
    fireEvent.change(screen.getByLabelText("ID de la suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(screen.getByLabelText(/Comentario del motivo/), { target: { value: "Pedido del socio" } });
  }
  const previewReply = { cascade_preview: PREVIEW, options: { toku_stop_mode: "paused" }, approvals_required: 1, would_self_approve: false, expires_in_days: 14, open_request: null };

  it("calcula la vista previa antes de enviar y la invalida si se edita un campo", async () => {
    mocks.postJson.mockResolvedValueOnce(previewReply);
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    await fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    expect(await screen.findByRole("list", { name: "Pasos de la cascada" })).toBeTruthy();
    expect(postCalls()[0]).toEqual(["/api/v1/cancellations/preview", { channel: "toku", subscription_external_id: "SUB-100", reason_code: "member_request", reason_comment: "Pedido del socio", toku_stop_mode: "paused" }]);
    expect(screen.getByText(/Quedará pendiente de aprobación \(1 aprobación requerida\) y vence en 14 días/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enviar solicitud" }).hasAttribute("disabled")).toBe(false);
    fireEvent.change(screen.getByLabelText(/Comentario del motivo/), { target: { value: "Otro texto" } });
    expect(screen.queryByRole("list", { name: "Pasos de la cascada" })).toBeNull();
    expect(screen.getByRole("button", { name: "Enviar solicitud" }).hasAttribute("disabled")).toBe(true);
  });

  it("envía la solicitud, cierra el diálogo, avisa y abre el detalle de la creada", async () => {
    mocks.postJson.mockResolvedValueOnce({ ...previewReply, would_self_approve: true }).mockResolvedValueOnce(detail({ id: "r9", status: "approved" }));
    detailData = detail({ id: "r9", status: "approved" });
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    await fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    await screen.findByText(/quedará autoaprobada/);
    fireEvent.click(screen.getByRole("button", { name: "Enviar solicitud" }));
    expect(await screen.findByText("Solicitud de baja creada y autoaprobada. Ya puede aplicarse.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(postCalls()[1][0]).toBe("/api/v1/cancellations");
    await waitFor(() => expect(mocks.getJson.mock.calls.map((c) => String(c[0]))).toContain("/api/v1/cancellations/r9"));
  });

  it("una solicitud abierta en la vista previa bloquea el envío y ofrece abrirla", async () => {
    mocks.postJson.mockResolvedValueOnce({ ...previewReply, open_request: { id: "r5", status: "approved" } });
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    await fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    expect(await screen.findByText(/Ya existe una solicitud de baja abierta.*Aprobada/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enviar solicitud" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Ver la solicitud abierta" }));
    await waitFor(() => expect(mocks.getJson.mock.calls.map((c) => String(c[0]))).toContain("/api/v1/cancellations/r5"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("errores del API en español, sin eco del servidor", async () => {
    mocks.postJson.mockRejectedValueOnce(apiError(409, { code: "open_request_exists", message: "Texto en inglés", open_request_id: "11111111-1111-4111-8111-111111111111" }));
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} />);
    await fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Ver vista previa" }));
    const alert = await screen.findByText(/Ya existe una solicitud de baja abierta para esta suscripción\. Resuélvala/);
    expect(alert.textContent).not.toContain("Texto en inglés");
    expect(screen.getByRole("button", { name: "Ver la solicitud abierta" })).toBeTruthy();
  });
});

describe("acciones de aprobación", () => {
  it("el aprobador aprueba un pendiente con comentario opcional", async () => {
    mocks.postJson.mockResolvedValueOnce(detail({ status: "approved" }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    expect(screen.queryByRole("button", { name: "Retirar" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Aprobar" }));
    expect(await screen.findByText("Baja aprobada. Ya puede aplicarse.")).toBeTruthy();
    expect(postCalls()[0]).toEqual(["/api/v1/cancellations/r1/approve", undefined]);
  });

  it("rechazar exige comentario y lo envía", async () => {
    mocks.postJson.mockResolvedValueOnce(detail({ status: "rejected" }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Rechazar" }));
    expect((await screen.findAllByRole("alert")).map((a) => a.textContent)).toContain("El comentario es obligatorio.");
    expect(mocks.postJson).not.toHaveBeenCalled();
    fireEvent.change(within(dialog()).getByRole("textbox"), { target: { value: "No corresponde" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Rechazar" }));
    expect(await screen.findByText("Solicitud de baja rechazada.")).toBeTruthy();
    expect(postCalls()[0]).toEqual(["/api/v1/cancellations/r1/reject", { comment: "No corresponde" }]);
  });

  it("retirar: el solicitante puede, otro usuario no, un admin sí", async () => {
    mocks.postJson.mockResolvedValue(detail({ status: "withdrawn" }));
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} currentUserId="u1" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Retirar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Retirar" }));
    expect(await screen.findByText("Solicitud de baja retirada.")).toBeTruthy();
    cleanup();
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} currentUserId="u2" />);
    await openDetail();
    expect(screen.queryByRole("button", { name: "Retirar" })).toBeNull();
    cleanup();
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} currentUserId="u2" isAdmin />);
    await openDetail();
    expect(screen.getByRole("button", { name: "Retirar" })).toBeTruthy();
  });

  it("reabrir solo en fallida o con conciliación y exige comentario", async () => {
    detailData = detail({ status: "requires_reconciliation", requires_reconciliation: true });
    listItems = [row({ status: "requires_reconciliation" })];
    mocks.postJson.mockResolvedValueOnce(detail({ status: "approved" }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    fireEvent.click(screen.getByRole("tab", { name: "En ejecución" }));
    await openDetail();
    expect(screen.queryByRole("button", { name: "Aprobar" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reabrir" }));
    fireEvent.change(within(dialog()).getByRole("textbox"), { target: { value: "Revisé el proveedor" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Reabrir" }));
    expect(await screen.findByText(/Solicitud reabierta como aprobada/)).toBeTruthy();
    expect(postCalls()[0]).toEqual(["/api/v1/cancellations/r1/reopen", { comment: "Revisé el proveedor" }]);
  });

  it("un error del API al aprobar se muestra en español dentro del diálogo", async () => {
    mocks.postJson.mockRejectedValueOnce(apiError(403, { code: "self_approval_not_allowed", message: "Self approval" }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u1" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Aprobar" }));
    expect(await within(dialog()).findByText("La política vigente no permite aprobar sus propias solicitudes.")).toBeTruthy();
    expect(dialog().textContent).not.toContain("Self approval");
  });
});

describe("aplicar con simulación", () => {
  beforeEach(() => {
    detailData = detail({ status: "approved" });
    listItems = [row({ status: "approved" })];
  });

  it("no usa window.confirm; confirma dentro de la página y primero hay que simular", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    mocks.postJson.mockResolvedValueOnce(PLAN()).mockResolvedValueOnce({ ...PLAN(), status: "completed", dry_run: false, plan: null, steps: [{ step: "payment_method", status: "manual", code: "TOKU_PAYMENT_METHOD_DECISION_PENDING" }] });
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    const confirm = within(dialog()).getByRole("button", { name: "Confirmar y aplicar" });
    expect(confirm.hasAttribute("disabled")).toBe(true);
    expect(within(dialog()).getByText("Debe simular antes de confirmar.")).toBeTruthy();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Simular baja" }));
    expect(await within(dialog()).findByText(/Simulación: no se escribió nada/)).toBeTruthy();
    expect(postCalls()[0]).toEqual(["/api/v1/cancellations/r1/apply", { dry_run: true }]);
    expect(within(dialog()).getByText(/Se anularán 1 factura impaga/)).toBeTruthy();
    expect(within(dialog()).getByText("Sin bloqueos: la baja puede aplicarse.")).toBeTruthy();
    expect(confirm.hasAttribute("disabled")).toBe(false);
    fireEvent.click(confirm);
    expect(await screen.findByText(/Baja aplicada\. Quedan pasos manuales por hacer: Medio de pago\./)).toBeTruthy();
    expect(postCalls()[1]).toEqual(["/api/v1/cancellations/r1/apply", { dry_run: false }]);
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("un bloqueo de la simulación (INVOICE_IN_PROGRESS) impide confirmar y se explica en español", async () => {
    mocks.postJson.mockResolvedValueOnce(PLAN({ blockers: ["INVOICE_IN_PROGRESS"] }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Simular baja" }));
    expect(await within(dialog()).findByText(/factura en proceso de cobro/)).toBeTruthy();
    expect(within(dialog()).getByRole("button", { name: "Confirmar y aplicar" }).hasAttribute("disabled")).toBe(true);
    expect(dialog().textContent).not.toContain("INVOICE_IN_PROGRESS");
  });

  it("una baja irreversible exige marcar la casilla de confirmación", async () => {
    mocks.postJson.mockResolvedValueOnce(PLAN({ irreversible: true }));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Simular baja" }));
    const ack = await within(dialog()).findByRole("checkbox", { name: /no se puede revertir/ });
    const confirm = within(dialog()).getByRole("button", { name: "Confirmar y aplicar" });
    expect(confirm.hasAttribute("disabled")).toBe(true);
    fireEvent.click(ack);
    expect(confirm.hasAttribute("disabled")).toBe(false);
  });

  it("errores al aplicar: INVOICE_IN_PROGRESS, apply_failed y reconciliation_required en español", async () => {
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    const cases: Array<[number, Record<string, unknown>, RegExp]> = [
      [409, { code: "INVOICE_IN_PROGRESS", message: "Raw" }, /factura en proceso de cobro/],
      [502, { code: "apply_failed", message: "Raw", step: "stop_subscription", step_code: "PROVIDER_ERROR" }, /La baja falló en un paso sin efectos previos[\s\S]*Detener la suscripción[\s\S]*El proveedor no respondió correctamente/],
      [503, { code: "reconciliation_required", message: "Raw", step: "cancel_pending_charges", step_code: "PENDING_CHARGES_REMAIN" }, /requiere conciliación[\s\S]*Cancelar los cobros pendientes/],
    ];
    for (const [status, detailBody, expected] of cases) {
      mocks.postJson.mockReset().mockResolvedValueOnce(PLAN()).mockRejectedValueOnce(apiError(status, detailBody));
      fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
      fireEvent.click(within(dialog()).getByRole("button", { name: "Simular baja" }));
      await within(dialog()).findByText(/Simulación/);
      fireEvent.click(within(dialog()).getByRole("button", { name: "Confirmar y aplicar" }));
      const alert = await within(dialog()).findByRole("alert");
      expect(alert.textContent).toMatch(expected);
      expect(alert.textContent).not.toContain("Raw");
      expect(alert.textContent).not.toMatch(/[A-Z]{3,}_[A-Z_]{3,}/);
      fireEvent.click(within(dialog()).getByRole("button", { name: "Cancelar" }));
    }
  });

  it("sin respuesta definitiva no invita a reintentar a ciegas", async () => {
    mocks.postJson.mockResolvedValueOnce(PLAN()).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<CancellationsInbox can={canOf([VIEW, APPROVE])} currentUserId="u2" />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Simular baja" }));
    await within(dialog()).findByText(/Simulación/);
    fireEvent.click(within(dialog()).getByRole("button", { name: "Confirmar y aplicar" }));
    expect((await within(dialog()).findByRole("alert")).textContent).toContain("No se pudo confirmar el resultado de la operación");
  });

  it("quien solo solicita no ve Aplicar ni Aprobar", async () => {
    render(<CancellationsInbox can={canOf([VIEW, REQUEST])} currentUserId="u2" />);
    await openDetail();
    expect(screen.queryByRole("button", { name: /Aplicar|Aprobar|Rechazar|Reabrir/ })).toBeNull();
  });
});
