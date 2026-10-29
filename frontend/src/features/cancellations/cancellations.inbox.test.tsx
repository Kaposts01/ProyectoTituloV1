import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn() }));
vi.mock("../../api", () => ({ getJson: mocks.getJson, postJson: mocks.postJson, friendlyError: (_e: unknown, f: string) => f }));

import { legacyRedirectPath, parseRoute, routePath } from "../../routes";
import { CancellationsInbox } from "./CancellationsInbox";
import type { CancellationDetail, CancellationRequest } from "./types";

const VIEW = "subscriptions.cancellation.view";
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

function detail(over: Partial<CancellationDetail> = {}): CancellationDetail {
  return {
    ...row(),
    cascade_preview: {
      channel: "toku", subscription_status: "ACTIVE", irreversible: false, pending_charges: 2, pending_charge_ids: ["INV-1", "INV-2"],
      processing_charges: 0, in_progress_invoices: 0, blockers: [], source: "local_last_sync",
      steps: [
        { step: "stop_subscription", action: "pause_subscription", reversible: true },
        { step: "cancel_pending_charges", action: "void_invoices", count: 2 },
        { step: "payment_method", action: "manual_task", reason: "decision_pending" },
      ],
    },
    steps: [], rules_snapshot: {},
    events: [{ id: "e1", event_type: "created", actor_user_id: "u1", actor: "ana", detail: { comment: "Pedido del socio" }, created_at: "2026-10-01T10:00:00+00:00" }],
    ...over,
  };
}

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
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

const listCalls = () => mocks.getJson.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith("/api/v1/cancellations?"));

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de baja de la suscripción SUB-100/ }));
  await screen.findByRole("heading", { name: /Toku · SUB-100/ });
}

describe("ruta y permiso", () => {
  it("la ruta /general/bajas se interpreta y se construye", () => {
    expect(parseRoute("/general/bajas")).toEqual({ kind: "cancellations" });
    expect(parseRoute("/general/bajas/")).toEqual({ kind: "cancellations" });
    expect(parseRoute("/general/bajas/x")).toBeNull();
    expect(routePath({ kind: "cancellations" })).toBe("/general/bajas");
    expect(legacyRedirectPath("/general/bajas")).toBeNull();
  });
});

describe("bandeja de bajas", () => {
  it("muestra tres pestañas, la primera consulta Pendientes y la tabla va en español", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    const table = await screen.findByRole("table", { name: /Solicitudes de baja de suscripción/ });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Pendientes", "En ejecución", "Historial"]);
    expect(listCalls()[0]).toBe("/api/v1/cancellations?status=pending&status=approved&limit=25&offset=0");
    const body = within(table).getAllByRole("row")[1];
    expect(within(body).getByText("Toku")).toBeTruthy();
    expect(within(body).getByText("Solicitud del socio")).toBeTruthy();
    expect(within(body).getByText("Pendiente de aprobación")).toBeTruthy();
    expect(within(body).getByText("ana")).toBeTruthy();
    expect(within(body).getByRole("button", { name: /SUB-100/ }).className).toContain("mono");
    for (const h of ["Suscripción", "Canal", "Motivo", "Solicitante", "Estado", "Creada"]) expect(within(table).getByRole("columnheader", { name: h })).toBeTruthy();
    expect(table.textContent).not.toMatch(/member_request|pending|toku\b/);
  });

  it("cambia de pestaña con clic y con flechas del teclado, y consulta los estados de cada una", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("tab", { name: "En ejecución" }));
    await waitFor(() => expect(listCalls().at(-1)).toBe("/api/v1/cancellations?status=applying&status=pending_external&status=requires_reconciliation&status=failed&limit=25&offset=0"));
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Historial" }).getAttribute("aria-selected")).toBe("true"));
    expect(listCalls().at(-1)).toBe("/api/v1/cancellations?status=completed&status=rejected&status=withdrawn&status=expired&status=not_executable&limit=25&offset=0");
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "Home" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Pendientes" }).getAttribute("aria-selected")).toBe("true"));
  });

  it("filtra por canal y por estado de la pestaña", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "payku" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "approved" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => expect(listCalls().at(-1)).toBe("/api/v1/cancellations?status=approved&channel=payku&limit=25&offset=0"));
    const options = Array.from((screen.getByLabelText("Estado") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options).toEqual(["Todos", "Pendiente de aprobación", "Aprobada"]);
    const channels = Array.from((screen.getByLabelText("Canal") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(channels).toEqual(["Todos", "VirtualPOS 1", "VirtualPOS 2", "Toku", "Payku", "TCH"]);
  });

  it("estado vacío con acción y error con reintento", async () => {
    listItems = [];
    render(<CancellationsInbox can={canOf([VIEW])} />);
    expect(await screen.findByText(/No hay solicitudes de baja pendientes/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Limpiar filtros" })).toBeTruthy();
    cleanup();
    listItems = [row()];
    mocks.getJson.mockRejectedValueOnce(apiError(500, "boom"));
    render(<CancellationsInbox can={canOf([VIEW])} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("No se pudo cargar la bandeja de bajas.");
    expect(alert.textContent).not.toContain("boom");
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("pagina de a 25", async () => {
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/cancellations?")) return { items: listItems, total: 60, limit: 25, offset: 0 };
      return detailData;
    });
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("table");
    expect(screen.getByText("1-25 de 60")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(listCalls().at(-1)).toContain("offset=25"));
  });

  it("solo lectura: sin permisos de solicitar ni aprobar no hay botones de acción", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await openDetail();
    expect(screen.queryByRole("button", { name: /Solicitar baja|Aprobar|Rechazar|Aplicar|Retirar|Reabrir/ })).toBeNull();
  });
});

describe("detalle de una baja", () => {
  it("muestra la vista previa de la cascada con pasos, conteos y el paso manual rotulado", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await openDetail();
    const steps = screen.getByRole("list", { name: "Pasos de la cascada" });
    const items = within(steps).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain("Detener la suscripción");
    expect(items[0].textContent).toContain("Pausar la suscripción (reversible)");
    expect(items[1].textContent).toContain("Anular las facturas impagas (irreversible): 2 cobros pendientes.");
    expect(items[2].textContent).toContain("Medio de pago");
    expect(items[2].textContent).toContain("Paso manual");
    expect(items[2].textContent).toContain("La decisión sobre esta tarea está pendiente.");
    expect(screen.getByLabelText("Situación actual de la suscripción").textContent).toContain("Activa");
    expect(screen.getByText(/Calculada con la última sincronización local/)).toBeTruthy();
  });

  it("un bloqueo INVOICE_IN_PROGRESS se explica en español y la baja irreversible se advierte", async () => {
    detailData = detail({ cascade_preview: { ...detail().cascade_preview, blockers: ["INVOICE_IN_PROGRESS"], irreversible: true, in_progress_invoices: 1 } });
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await openDetail();
    expect(screen.getByText(/factura en proceso de cobro/)).toBeTruthy();
    expect(screen.getByText(/no se puede revertir en el proveedor/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("INVOICE_IN_PROGRESS");
  });

  it("el resultado por paso distingue hecho, fallido y manual, sin códigos crudos", async () => {
    detailData = detail({
      status: "requires_reconciliation", requires_reconciliation: true,
      steps: [
        { step: "stop_subscription", status: "done", code: null, at: "2026-10-02T10:00:00+00:00" },
        { step: "cancel_pending_charges", status: "failed", code: "INVOICE_VOID_FAILED", voided: 1, error: "RuntimeError" },
        { step: "payment_method", status: "manual", code: "TOKU_PAYMENT_METHOD_DECISION_PENDING", task: "remove_payment_method_manually" },
      ],
    });
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await openDetail();
    const results = within(screen.getByRole("list", { name: "Resultado de cada paso" })).getAllByRole("listitem");
    expect(results[0].textContent).toContain("Hecho");
    expect(results[1].textContent).toContain("Fallido");
    expect(results[1].textContent).toContain("No se pudo anular una factura impaga en Toku");
    expect(results[1].textContent).toContain("Facturas anuladas: 1");
    expect(results[1].querySelector("[data-raw-text]")?.textContent).toContain("RuntimeError");
    expect(results[2].textContent).toContain("Paso manual");
    expect(results[2].textContent).toContain("Falta decidir si se elimina el medio de pago de Toku");
    expect(results[2].textContent).toContain("Tarea: Eliminar el medio de pago a mano");
    const alerts = screen.getAllByRole("alert").map((a) => a.textContent).join(" ");
    expect(alerts).toContain("requiere conciliación");
    expect(screen.getByText(/Pasos manuales pendientes de una persona/)).toBeTruthy();
    const visible = document.body.cloneNode(true) as HTMLElement;
    visible.querySelectorAll("[data-raw-text]").forEach((n) => n.remove());
    expect(visible.textContent).not.toMatch(/INVOICE_VOID_FAILED|TOKU_PAYMENT|remove_payment|stop_subscription|requires_reconciliation/);
  });

  it("TCH en trámite se explica: se cierra con el siguiente Excel", async () => {
    detailData = detail({ channel: "tch", status: "pending_external", steps: [
      { step: "register_internal", status: "done", code: null },
      { step: "bank_mandate", status: "manual", code: "TCH_BANK_MANDATE_OUTSIDE_CRM", task: "revoke_bank_mandate_manually" },
    ] });
    listItems = [row({ channel: "tch", status: "pending_external" })];
    render(<CancellationsInbox can={canOf([VIEW])} />);
    fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de baja/ }));
    await screen.findByRole("heading", { name: /TCH · SUB-100/ });
    expect(screen.getByText(/La baja está en trámite/)).toBeTruthy();
    expect(screen.getByText(/siguiente Excel de TCH/, { selector: "div" })).toBeTruthy();
    expect(screen.getAllByText("Mandato bancario").length).toBeGreaterThan(0);
  });

  it("la línea de tiempo traduce los eventos y no muestra textos del proveedor", async () => {
    detailData = detail({ events: [
      { id: "e1", event_type: "created", actor_user_id: "u1", actor: "ana", detail: { comment: "Pedido del socio" }, created_at: "2026-10-01T10:00:00+00:00" },
      { id: "e2", event_type: "step_failed", actor_user_id: null, actor: "sistema", detail: { step: "cancel_pending_charges", code: "PENDING_CHARGES_REMAIN", provider_message: "Mensaje del proveedor" }, created_at: "2026-10-02T10:00:00+00:00" },
      { id: "e3", event_type: "algo_nuevo", actor_user_id: null, actor: null, detail: {}, created_at: "2026-10-03T10:00:00+00:00" },
    ] });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await openDetail();
    const timeline = screen.getByRole("list", { name: /Línea de tiempo/ });
    expect(timeline.textContent).toContain("Solicitud creada");
    expect(timeline.textContent).toContain("Paso fallido");
    expect(timeline.textContent).toContain("Paso: Cancelar los cobros pendientes");
    expect(timeline.textContent).toContain("Quedaron cobros pendientes en el proveedor");
    expect(timeline.textContent).toContain("Desconocido (algo_nuevo)");
    expect(timeline.textContent).not.toContain("Mensaje del proveedor");
    warn.mockRestore();
  });

  it("error al cargar el detalle: mensaje en español y reintento", async () => {
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/cancellations?")) return { items: listItems, total: 1, limit: 25, offset: 0 };
      throw apiError(404, { code: "request_not_found", message: "Solicitud no encontrada." });
    });
    render(<CancellationsInbox can={canOf([VIEW])} />);
    fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de baja/ }));
    const alert = await screen.findByText("No se encontró la solicitud. Puede que ya no exista.");
    expect(alert).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeTruthy();
  });
});
