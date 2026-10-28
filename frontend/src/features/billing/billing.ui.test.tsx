import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson,
  postJson: mocks.postJson,
  putJson: mocks.putJson,
  friendlyError: (_e: unknown, f: string) => f,
}));

import { BillingInbox } from "./BillingInbox";
import { PolicyPanel } from "./PolicyPanel";

const apiError = (status: number, detail: unknown) => Object.assign(new Error("texto crudo 12.345.678-9"), { status, detail });

const ADMIN = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.request", "virtualpos.billing_changes.approve", "virtualpos.billing_policy.manage"];
const READONLY = ["virtualpos.billing_changes.view"];
const canOf = (perms: string[]) => (p: string) => perms.includes(p);

const PLAN = {
  noop: false,
  cancel: [{ month: "2026-04", charge_date: "2026-04-05", amount: 5000, charge_id: "chg-1" }],
  create: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000, internal_code: "S1-202604" }],
  covered: [], manual_review: [], unchanged: [], kept_automatic_after_horizon: [],
  warnings: [{ code: "w", message: "Aviso de prueba", month: null }], errors: [],
  summary: { creates: 1, cancels: 1, covered_months: 0, manual_review_months: 0, unchanged_months: 0, affected_charges: 2, previous_amount: 5000, new_amount: 8000, amount_delta: 3000, total_delta: 3000, variation_pct: 60, horizon_start: "2026-04", horizon_end: "2027-03" },
};

function req(over: Record<string, unknown> = {}) {
  return {
    id: "r1", request_type: "change_amount", platform: "virtualpos1", subscription_external_id: "SUB-100", status: "pendiente",
    requested_by_user_id: "u1", requested_by: "ana", new_amount: 8000, previous_amount: 5000, new_charge_day: null, previous_charge_day: null,
    new_charge_date: null, horizon_months: 12, horizon_start_month: "2026-04", approvals_required: 1, approvals_count: 0,
    requester_comment: "Pedido del socio", approved_by_user_id: null, approved_by: null, self_approved: false, decided_at: null,
    decision_comment: null, write_run_id: null, expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString(), executed_at: null,
    error_message: null, created_at: "2026-03-01T10:00:00+00:00", updated_at: null, ...over,
  };
}
function detail(over: Record<string, unknown> = {}) {
  return { ...req(over), plan_preview: PLAN, rules_snapshot: {}, events: [{ id: "e1", event_type: "creada", actor_user_id: "u1", actor: "ana", detail: {}, created_at: "2026-03-01T10:00:00+00:00" }] };
}

let listItems: ReturnType<typeof req>[] = [];
let detailData = detail();
let requesters: { id: string; username: string }[] = [];

beforeEach(() => {
  mocks.getJson.mockReset();
  mocks.postJson.mockReset();
  mocks.putJson.mockReset();
  listItems = [req()];
  requesters = [{ id: "11111111-1111-4111-8111-111111111111", username: "ana" }, { id: "22222222-2222-4222-8222-222222222222", username: "beto" }];
  detailData = detail();
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: requesters };
    if (path.startsWith("/api/v1/billing/changes?")) return { items: listItems, total: listItems.length, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes/")) return detailData;
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de la suscripción SUB-100/ }));
  await screen.findByRole("heading", { name: /Cambio de monto/ });
}

describe("bandeja", () => {
  it("renderiza estado con texto, datos en mono y vencimiento", async () => {
    render(<BillingInbox can={canOf(READONLY)} />);
    const table = await screen.findByRole("table", { name: /Solicitudes de cambio de cobro/ });
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getByText("Pendiente")).toBeTruthy();
    expect(within(row).getByRole("button", { name: /SUB-100/ }).className).toContain("mono");
    expect(within(row).getByText("$5.000 → $8.000").className).toContain("mono");
    expect(within(row).getByText("vence en 5 días").className).toContain("mono");
    for (const h of ["Suscripción", "Tipo", "Estado", "Solicitante", "Creada", "Vencimiento"]) expect(within(table).getByRole("columnheader", { name: h })).toBeTruthy();
  });

  it("muestra estado vacio con accion", async () => {
    listItems = [];
    render(<BillingInbox can={canOf(ADMIN)} />);
    expect(await screen.findByText(/No hay solicitudes pendientes/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Crear una solicitud" })).toBeTruthy();
  });

  it("muestra error y permite reintentar", async () => {
    mocks.getJson.mockRejectedValueOnce(apiError(500, "boom"));
    render(<BillingInbox can={canOf(READONLY)} />);
    expect((await screen.findByRole("alert")).textContent).toContain("No se pudo cargar la bandeja");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("las pestanas y los filtros arman la consulta", async () => {
    render(<BillingInbox can={canOf(READONLY)} />);
    await screen.findByRole("table");
    const first = new URL(mocks.getJson.mock.calls[0][0], "http://x").searchParams;
    expect(first.getAll("status")).toContain("pendiente");
    expect(first.getAll("status")).not.toContain("ejecutada");

    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "change_date" } });
    fireEvent.change(screen.getByLabelText("Suscripción"), { target: { value: "SUB-9" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => {
      const last = new URL(mocks.getJson.mock.calls.at(-1)![0], "http://x").searchParams;
      expect(last.get("request_type")).toBe("change_date");
      expect(last.get("subscription_id")).toBe("SUB-9");
      expect(last.get("date_from")).toBe("2026-01-01");
    });

    fireEvent.click(screen.getByRole("tab", { name: "Historial" }));
    await waitFor(() => {
      const last = new URL(mocks.getJson.mock.calls.at(-1)![0], "http://x").searchParams;
      expect(last.getAll("status")).toContain("ejecutada");
      expect(last.getAll("status")).not.toContain("pendiente");
    });
  });

  it("el selector de solicitante lista usuarios, filtra por requested_by y conserva Todos", async () => {
    render(<BillingInbox can={canOf(READONLY)} />);
    await screen.findByRole("table");
    const select = await screen.findByLabelText("Solicitante") as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(["Todos", "ana", "beto"]);
    fireEvent.change(select, { target: { value: "22222222-2222-4222-8222-222222222222" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => {
      const last = new URL(mocks.getJson.mock.calls.at(-1)![0], "http://x").searchParams;
      expect(last.get("requested_by")).toBe("22222222-2222-4222-8222-222222222222");
    });
    fireEvent.change(select, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => {
      const last = new URL(mocks.getJson.mock.calls.at(-1)![0], "http://x").searchParams;
      expect(last.has("requested_by")).toBe(false);
    });
  });

  it("«Mis solicitudes» sigue funcionando aunque el usuario no figure en la lista", async () => {
    render(<BillingInbox can={canOf(READONLY)} currentUserId="33333333-3333-4333-8333-333333333333" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Mis solicitudes" }));
    expect((screen.getByLabelText("Solicitante") as HTMLSelectElement).value).toBe("33333333-3333-4333-8333-333333333333");
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => {
      const last = new URL(mocks.getJson.mock.calls.at(-1)![0], "http://x").searchParams;
      expect(last.get("requested_by")).toBe("33333333-3333-4333-8333-333333333333");
    });
  });

  it("si falla la lista de solicitantes avisa, permite reintentar y no bloquea la bandeja", async () => {
    const base = mocks.getJson.getMockImplementation()!;
    let failOnce = true;
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path === "/api/v1/billing/requesters" && failOnce) { failOnce = false; throw apiError(500, "boom"); }
      return base(path);
    });
    render(<BillingInbox can={canOf(READONLY)} />);
    expect(await screen.findByRole("table")).toBeTruthy();
    expect((await screen.findByText(/No se pudo cargar la lista de solicitantes/)).textContent).toBeTruthy();
    expect((screen.getByLabelText("Solicitante") as HTMLSelectElement).disabled).toBe(false);
    const buscar = screen.getByRole("button", { name: "Buscar" }) as HTMLButtonElement;
    expect(buscar.disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(screen.queryByText(/No se pudo cargar la lista de solicitantes/)).toBeNull());
    await waitFor(() => expect(Array.from((screen.getByLabelText("Solicitante") as HTMLSelectElement).options).length).toBe(3));
  });
});

describe("permisos", () => {
  it("solo lectura ve el detalle pero ninguna accion", async () => {
    render(<BillingInbox can={canOf(READONLY)} />);
    await openDetail();
    expect(screen.queryByRole("button", { name: "Aprobar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rechazar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Retirar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Nueva solicitud" })).toBeNull();
    expect(screen.getByRole("table", { name: "Plan por mes" })).toBeTruthy();
    expect(screen.getByText("Aviso de prueba")).toBeTruthy();
    expect(screen.getByRole("list", { name: /Línea de tiempo/ })).toBeTruthy();
  });

  it("admin ve las acciones segun el estado", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    for (const n of ["Aprobar", "Rechazar", "Retirar"]) expect(screen.getByRole("button", { name: n })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Aplicar" })).toBeNull();
    expect(screen.getByRole("button", { name: "Nueva solicitud" })).toBeTruthy();
  });

  it("reabrir solo en fallida y requiere_conciliacion", async () => {
    listItems = [req({ status: "fallida" })];
    detailData = detail({ status: "fallida" });
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    expect(screen.getByRole("button", { name: "Reabrir" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Aprobar" })).toBeNull();
  });
});

describe("acciones", () => {
  it("rechazar sin comentario queda bloqueado", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));
    const dialog = await screen.findByRole("dialog", { name: "Rechazar solicitud" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rechazar" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/obligatorio/);
    expect(mocks.postJson).not.toHaveBeenCalled();
  });

  it("reabrir sin comentario queda bloqueado y con comentario envia", async () => {
    listItems = [req({ status: "fallida" })];
    detailData = detail({ status: "fallida" });
    mocks.postJson.mockResolvedValue(detail({ status: "aprobada" }));
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Reabrir" }));
    const dialog = await screen.findByRole("dialog", { name: "Reabrir solicitud" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reabrir" }));
    await within(dialog).findByRole("alert");
    expect(mocks.postJson).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "  Conciliado a mano  " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reabrir" }));
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledWith("/api/v1/billing/changes/r1/reopen", { comment: "Conciliado a mano" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("el foco entra al dialogo y vuelve al cerrar con Escape", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    const trigger = screen.getByRole("button", { name: "Rechazar" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("aprobar bloquea el doble envio", async () => {
    let release: (v: unknown) => void = () => {};
    mocks.postJson.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    const dialog = await screen.findByRole("dialog", { name: "Aprobar solicitud" });
    const confirm = within(dialog).getByRole("button", { name: "Aprobar" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "Aprobando…" }) as HTMLButtonElement).disabled).toBe(true));
    expect(mocks.postJson).toHaveBeenCalledTimes(1);
    detailData = detail({ status: "aprobada" });
    release(detail({ status: "aprobada" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((await screen.findByText(/Solicitud aprobada/)).textContent).toMatch(/Ya puede aplicarse/);
  });

  it("aplicar con plan_drift muestra el diff y reintenta con accept_drift solo tras confirmar", async () => {
    listItems = [req({ status: "aprobada" })];
    detailData = detail({ status: "aprobada" });
    mocks.postJson
      .mockRejectedValueOnce(apiError(409, {
        code: "plan_drift", message: "x", retry_with: { accept_drift: true },
        diff: { create_added: [["2026-05", "2026-05-10", 9000, "S1-202605"]], cancel_removed: [["2026-04", "chg-1", 5000]] },
        new_preview: { ...PLAN, create: [{ month: "2026-05", charge_date: "2026-05-10", amount: 9000, internal_code: "S1-202605" }] },
      }))
      .mockResolvedValueOnce({ request_id: "r1", status: "ok", request_status: "ejecutada", already_applied: false, created: 1, cancelled: 1, covered_late_months: 0, manual_review_months: 0, drift_accepted: true, plan_summary: null });
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    const dialog = await screen.findByRole("dialog", { name: "Aplicar cambio en VirtualPOS" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aplicar ahora" }));

    const drift = await screen.findByRole("dialog", { name: "El plan cambió desde la aprobación" });
    expect(mocks.postJson).toHaveBeenCalledTimes(1);
    expect(mocks.postJson.mock.calls[0]).toEqual(["/api/v1/billing/changes/r1/apply", {}]);
    expect(within(drift).getByText(/Se creará un cobro nuevo/)).toBeTruthy();
    expect(within(drift).getByText(/Ya no se cancelará el cobro aprobado/)).toBeTruthy();
    expect(within(drift).getByText("Nuevo plan recalculado")).toBeTruthy();

    const accept = within(drift).getByRole("button", { name: "Aceptar cambios y aplicar" }) as HTMLButtonElement;
    expect(accept.disabled).toBe(true);
    fireEvent.click(accept);
    expect(mocks.postJson).toHaveBeenCalledTimes(1);

    fireEvent.click(within(drift).getByRole("checkbox"));
    fireEvent.click(accept);
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledTimes(2));
    expect(mocks.postJson.mock.calls[1]).toEqual(["/api/v1/billing/changes/r1/apply", { accept_drift: true }]);
    expect((await screen.findByText(/Cambio aplicado: 1 cobros creados y 1 cancelados/))).toBeTruthy();
  });

  const failures: Array<[number, Record<string, unknown>, RegExp, string]> = [
    [403, { code: "writes_disabled", message: "x" }, /deshabilitadas/, "Aplicar"],
    [409, { code: "subscription_busy", message: "x" }, /Otra operación/, "Aplicar"],
    [409, { code: "subscription_blocked", message: "x" }, /pendientes de conciliación/, "Aplicar"],
    [409, { code: "invalid_request_state", message: "x", current_status: "ejecutada" }, /cambió de estado/, "Aplicar"],
    [422, { code: "fixed_plan_charge_blocked", message: "x" }, /plan fijo/, "Aplicar"],
    [502, { code: "apply_failed", message: "payload del proveedor RUT 12.345.678-9", request_status: "fallida" }, /compensaron/, "Aplicar"],
    [503, { code: "reconciliation_required", message: "x" }, /conciliación manual/, "Aplicar"],
  ];
  it.each(failures)("aplicar con %i %o muestra el mensaje claro", async (status, detailBody, re) => {
    listItems = [req({ status: "aprobada" })];
    detailData = detail({ status: "aprobada" });
    mocks.postJson.mockRejectedValue(apiError(status, detailBody));
    render(<BillingInbox can={canOf(ADMIN)} />);
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Aplicar ahora" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toMatch(re);
    expect(document.body.textContent).not.toContain("12.345.678-9");
    expect((within(dialog).getByRole("button", { name: "Aplicar ahora" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("nueva solicitud", () => {
  const preview = (over: Record<string, unknown> = {}) => ({ plan_preview: PLAN, summary: PLAN.summary, approvals_required: 1, would_self_approve: true, expires_in_days: 7, open_request: null, ...over });

  async function openForm() {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    return screen.findByRole("dialog", { name: /Nueva solicitud/ });
  }

  it("exige vista previa antes de enviar y valida campos", async () => {
    mocks.postJson.mockResolvedValueOnce(preview());
    const dialog = await openForm();
    const send = within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect((await within(dialog).findAllByRole("alert")).length).toBeGreaterThanOrEqual(2);
    expect(mocks.postJson).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    await within(dialog).findByText(/se autoaprobará/);
    expect(mocks.postJson).toHaveBeenCalledWith("/api/v1/billing/changes/preview", expect.objectContaining({ request_type: "change_amount", new_amount: 8000, subscription_external_id: "SUB-100" }));
    expect(within(dialog).getByRole("table", { name: "Plan por mes" })).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "9000" } });
    expect((within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("indica doble aprobacion y que quedara pendiente", async () => {
    mocks.postJson.mockResolvedValueOnce(preview({ would_self_approve: false, approvals_required: 2 }));
    const dialog = await openForm();
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect(await within(dialog).findByText(/quedará pendiente de aprobación/)).toBeTruthy();
    expect(within(dialog).getByText(/Requiere doble aprobación/)).toBeTruthy();
  });

  it("valida dia y fecha futura segun el tipo", async () => {
    const dialog = await openForm();
    fireEvent.change(within(dialog).getByLabelText("Tipo de cambio"), { target: { value: "one_off_charge" } });
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-1" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "1000" } });
    fireEvent.change(within(dialog).getByLabelText("Fecha del cobro"), { target: { value: "2020-01-01" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/posterior a hoy/);
    fireEvent.change(within(dialog).getByLabelText("Tipo de cambio"), { target: { value: "change_date" } });
    fireEvent.change(within(dialog).getByLabelText("Nuevo día de cobro (1-31)"), { target: { value: "40" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/entre 1 y 31/);
    expect(mocks.postJson).not.toHaveBeenCalled();
  });

  it("maneja open_request_exists y no_changes", async () => {
    mocks.postJson.mockRejectedValueOnce(apiError(409, { code: "open_request_exists", message: "x", open_request_id: "r9" }));
    const dialog = await openForm();
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/solicitud abierta/);
    mocks.postJson.mockRejectedValueOnce(apiError(422, { code: "no_changes", message: "x" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    await waitFor(() => expect(within(dialog).getByRole("alert").textContent).toMatch(/no hay cambios/));
  });

  it("enviar crea la solicitud, cierra y la selecciona", async () => {
    mocks.postJson.mockResolvedValueOnce(preview()).mockResolvedValueOnce(detail({ status: "aprobada", self_approved: true }));
    const dialog = await openForm();
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    await within(dialog).findByText(/se autoaprobará/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar solicitud" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.postJson.mock.calls[1][0]).toBe("/api/v1/billing/changes");
    expect(await screen.findByText(/creada y autoaprobada/)).toBeTruthy();
  });
});

describe("politica", () => {
  const policy = {
    approver_roles: ["admin"], approver_user_ids: [], self_approval_enabled: true, dual_approval_enabled: false,
    dual_threshold_subscriptions: 10, dual_threshold_variation_pct: 25, renewal_threshold_days: 30, request_expiry_days: 7,
    horizon_months: 12, window_days: 30,
  };
  const roles = [{ id: "1", name: "admin" }, { id: "2", name: "ejecutivo" }];

  beforeEach(() => {
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path === "/api/v1/billing/policy") return policy;
      if (path.startsWith("/api/v1/billing/policy/audit")) {
        return { items: [{ id: "a1", changed_by_user_id: "u1", changed_by: "root", changed_at: "2026-03-01T10:00:00+00:00", before_values: { self_approval_enabled: false }, after_values: { self_approval_enabled: true }, reason: "Piloto" }], total: 1, limit: 20, offset: 0 };
      }
      if (path === "/api/v1/admin/users") return [{ id: "u1", username: "root", is_active: true }];
      throw new Error(`ruta no mockeada ${path}`);
    });
  });

  it("muestra la politica y el historial", async () => {
    render(<PolicyPanel roles={roles} canListUsers />);
    expect(await screen.findByRole("checkbox", { name: "admin" })).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "admin" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: "ejecutivo" }) as HTMLInputElement).checked).toBe(false);
    const table = await screen.findByRole("table", { name: /Historial de cambios/ });
    expect(within(table).getByText("Piloto")).toBeTruthy();
    expect(within(table).getByText(/Autoaprobación/)).toBeTruthy();
  });

  it("guarda solo los campos modificados con el motivo", async () => {
    mocks.putJson.mockResolvedValue({ ...policy, request_expiry_days: 14 });
    render(<PolicyPanel roles={roles} canListUsers />);
    const field = await screen.findByLabelText(/Expiración de solicitudes/);
    fireEvent.change(field, { target: { value: "14" } });
    fireEvent.change(screen.getByLabelText(/Motivo del cambio/), { target: { value: "Más plazo" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar política" }));
    await waitFor(() => expect(mocks.putJson).toHaveBeenCalledWith("/api/v1/billing/policy", { request_expiry_days: 14, reason: "Más plazo" }));
    expect(await screen.findByText(/Política actualizada/)).toBeTruthy();
  });

  it("no envia si no hay cambios", async () => {
    render(<PolicyPanel roles={roles} canListUsers />);
    await screen.findByLabelText(/Expiración de solicitudes/);
    fireEvent.click(screen.getByRole("button", { name: "Guardar política" }));
    expect(await screen.findByText(/No hay cambios para guardar/)).toBeTruthy();
    expect(mocks.putJson).not.toHaveBeenCalled();
  });

  it("muestra el error AP-23 del servidor", async () => {
    mocks.putJson.mockRejectedValue(apiError(422, { code: "policy_invalid", message: "x", policy_code: "no_approvers" }));
    render(<PolicyPanel roles={roles} canListUsers />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "admin" }));
    expect(screen.getByText(/ningún rol ni usuario aprobador/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Guardar política" }));
    expect((await screen.findByRole("alert")).textContent).toContain("AP-23");
  });

  it("muestra el error AP-24 del servidor", async () => {
    mocks.putJson.mockRejectedValue(apiError(422, { code: "policy_invalid", message: "x", policy_code: "no_other_approver" }));
    render(<PolicyPanel roles={roles} canListUsers />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /Permitir autoaprobación/ }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar política" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("AP-24");
    expect(alert.textContent).not.toContain("12.345.678-9");
  });

  it("valida rangos localmente sin llamar a la API", async () => {
    render(<PolicyPanel roles={roles} canListUsers />);
    fireEvent.change(await screen.findByLabelText(/Horizonte \(meses\)/), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar política" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/entre 1 y 60/);
    expect(mocks.putJson).not.toHaveBeenCalled();
  });

  it("403 al cargar muestra mensaje claro", async () => {
    mocks.getJson.mockRejectedValue(apiError(403, "Forbidden"));
    render(<PolicyPanel roles={roles} canListUsers={false} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/permiso/);
  });
});
