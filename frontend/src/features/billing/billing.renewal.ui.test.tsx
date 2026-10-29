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

const apiError = (status: number, detail: unknown) => Object.assign(new Error("texto crudo 12.345.678-9"), { status, detail });
const ADMIN = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.request", "virtualpos.billing_changes.approve"];
const READONLY = ["virtualpos.billing_changes.view"];
const canOf = (perms: string[]) => (p: string) => perms.includes(p);

const PLAN = {
  noop: false, cancel: [], create: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000, internal_code: "S1-202604" }],
  covered: [], manual_review: [], unchanged: [], kept_automatic_after_horizon: [], warnings: [], errors: [],
  summary: { creates: 1, cancels: 0, covered_months: 0, manual_review_months: 0, unchanged_months: 0, affected_charges: 1, previous_amount: 5000, new_amount: 8000, amount_delta: 3000, total_delta: 3000, variation_pct: 60, horizon_start: "2026-04", horizon_end: "2027-03" },
};

function task(over: Record<string, unknown> = {}) {
  return {
    id: "t1", platform: "virtualpos1", subscription_external_id: "SUB-777", status: "abierta", priority: "normal",
    last_scheduled_date: "2026-12-01", scheduled_amount: 12000, due_date: "2026-12-01", days_remaining: 20, data_stale: false,
    request_id: null, close_reason: null, ...over,
  };
}
function reqDetail(id: string) {
  return {
    id, request_type: "renew_calendar", platform: "virtualpos1", subscription_external_id: "SUB-777", status: "pendiente",
    requested_by_user_id: "u1", requested_by: "ana", new_amount: null, previous_amount: null, new_charge_day: null, previous_charge_day: null,
    new_charge_date: null, horizon_months: 12, horizon_start_month: "2026-04", approvals_required: 1, approvals_count: 0,
    requester_comment: null, approved_by_user_id: null, approved_by: null, self_approved: false, decided_at: null, decision_comment: null,
    write_run_id: null, expires_at: null, executed_at: null, error_message: null, created_at: "2026-03-01T10:00:00+00:00", updated_at: null,
    plan_preview: PLAN, rules_snapshot: {}, events: [],
  };
}
const preview = () => ({ plan_preview: PLAN, summary: PLAN.summary, approvals_required: 1, would_self_approve: false, expires_in_days: 7, open_request: null });

let tasks: Record<string, unknown>[] = [];
let alertTotal = 0;
const isAlert = (p: string) => p.includes("limit=1&");
const renewalCalls = () => mocks.getJson.mock.calls.map((c) => c[0] as string).filter((p) => p.startsWith("/api/v1/billing/renewal-tasks") && !isAlert(p));

beforeEach(() => {
  mocks.getJson.mockReset();
  mocks.postJson.mockReset();
  tasks = [task()];
  alertTotal = 0;
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: [] };
    if (path.startsWith("/api/v1/billing/renewal-tasks")) {
      if (isAlert(path)) return { items: [], total: alertTotal, limit: 1, offset: 0 };
      return { items: tasks, total: tasks.length, limit: 25, offset: 0 };
    }
    if (path.startsWith("/api/v1/billing/changes?")) return { items: [], total: 0, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes/")) return reqDetail(path.split("/").pop() as string);
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

async function openRenewals(perms = READONLY) {
  render(<BillingInbox can={canOf(perms)} />);
  fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
  return screen.findByRole("table", { name: /Tareas de renovación/ });
}

describe("renovaciones: lista", () => {
  it("renderiza prioridad, estado, plazo, monto y datos desactualizados con texto", async () => {
    tasks = [task({ priority: "alta", status: "vencida", days_remaining: -3, data_stale: true })];
    const table = await openRenewals();
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getByText("SUB-777").className).toContain("mono");
    expect(within(row).getByText("VirtualPOS 1")).toBeTruthy();
    expect(within(row).getByText("Alta")).toBeTruthy();
    expect(within(row).getByText("Vencida")).toBeTruthy();
    expect(within(row).getByText("vencida hace 3 días").className).toContain("mono");
    expect(within(row).getByText("2026-12-01").className).toContain("mono");
    expect(within(row).getByText("$12.000").className).toContain("mono");
    expect(within(row).getByText("Datos desactualizados")).toBeTruthy();
    expect(within(row).getByText(/sincronización de la plataforma es antigua o falló/)).toBeTruthy();
    for (const h of ["Suscripción", "Plataforma", "Prioridad", "Estado", "Fecha límite", "Último monto programado", "Acción"]) {
      expect(within(table).getByRole("columnheader", { name: h })).toBeTruthy();
    }
  });

  it("textos de plazo: vence en N días, vence hoy y vencida hace N días", async () => {
    tasks = [task({ id: "a", days_remaining: 4 }), task({ id: "b", days_remaining: 0 }), task({ id: "c", status: "vencida", days_remaining: -1 })];
    await openRenewals();
    expect(screen.getByText("vence en 4 días")).toBeTruthy();
    expect(screen.getByText("vence hoy")).toBeTruthy();
    expect(screen.getByText("vencida hace 1 día")).toBeTruthy();
  });

  it("carga abierta+vencida por defecto y usa status repetible", async () => {
    await openRenewals();
    const sp = new URL(renewalCalls()[0], "http://x").searchParams;
    expect(sp.getAll("status")).toEqual(["abierta", "vencida"]);
  });

  it("los filtros arman la consulta", async () => {
    await openRenewals();
    fireEvent.change(screen.getByLabelText("Prioridad"), { target: { value: "alta" } });
    fireEvent.change(screen.getByLabelText("Plataforma"), { target: { value: "virtualpos2" } });
    fireEvent.change(screen.getByLabelText("Suscripción"), { target: { value: "SUB-9" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => {
      const sp = new URL(renewalCalls().at(-1)!, "http://x").searchParams;
      expect(sp.getAll("status")).toEqual(["abierta", "vencida", "cerrada", "no_aplica"]);
      expect(sp.get("priority")).toBe("alta");
      expect(sp.get("platform")).toBe("virtualpos2");
      expect(sp.get("subscription_id")).toBe("SUB-9");
    });
  });

  it("estado vacío", async () => {
    tasks = [];
    render(<BillingInbox can={canOf(READONLY)} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
    expect(await screen.findByText("No hay renovaciones pendientes.")).toBeTruthy();
  });

  it("error con reintento", async () => {
    const base = mocks.getJson.getMockImplementation()!;
    let fail = true;
    mocks.getJson.mockImplementation(async (path: string) => {
      if (fail && path.startsWith("/api/v1/billing/renewal-tasks") && !isAlert(path)) { fail = false; throw apiError(500, "boom"); }
      return base(path);
    });
    render(<BillingInbox can={canOf(READONLY)} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("No se pudieron cargar las tareas de renovación");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("table", { name: /Tareas de renovación/ })).toBeTruthy();
  });

  it("la pestaña muestra el contador de altas/vencidas con texto accesible", async () => {
    alertTotal = 3;
    render(<BillingInbox can={canOf(READONLY)} />);
    expect(await screen.findByRole("tab", { name: /Renovaciones.*3 tareas abiertas o vencidas con prioridad alta/ })).toBeTruthy();
  });

  it("si falla el contador no rompe la bandeja", async () => {
    const base = mocks.getJson.getMockImplementation()!;
    mocks.getJson.mockImplementation(async (path: string) => {
      if (isAlert(path)) throw apiError(500, "boom");
      return base(path);
    });
    render(<BillingInbox can={canOf(READONLY)} />);
    expect(await screen.findByRole("tab", { name: "Renovaciones" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("tareas cerradas muestran el motivo en español, sin acciones; motivo desconocido no rompe", async () => {
    tasks = [
      task({ id: "a", status: "cerrada", close_reason: "Renovación ejecutada: el calendario se extendió.", request_id: "r-9" }),
      task({ id: "b", status: "no_aplica", subscription_external_id: "SUB-2", close_reason: "La suscripción ya no está ACTIVA (estado: CANCELADA)." }),
      task({ id: "c", status: "no_aplica", subscription_external_id: "SUB-3", close_reason: "algo inesperado 12.345.678-9" }),
    ];
    await openRenewals(ADMIN);
    expect(screen.getByText("Renovación ejecutada: el calendario se extendió.")).toBeTruthy();
    expect(screen.getByText("La suscripción dejó de estar activa (estado: CANCELADA).")).toBeTruthy();
    expect(screen.getByText("Cerrada por el sistema (motivo no reconocido).")).toBeTruthy();
    expect(screen.queryByText(/12\.345\.678-9/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Solicitar renovación/ })).toBeNull();
  });

  it("no muestra nombre ni datos personales aunque el servidor los envíe", async () => {
    tasks = [task({ member_name: "Juan Pérez Soto", member_rut: "12.345.678-9", email: "juan@example.com" })];
    await openRenewals();
    expect(document.body.textContent).not.toMatch(/Juan|Pérez|12\.345\.678-9|juan@example/);
  });
});

describe("renovaciones: acciones", () => {
  it("«Solicitar renovación» solo con permiso request y sin request_id", async () => {
    tasks = [task({ id: "a" }), task({ id: "b", subscription_external_id: "SUB-OPEN", request_id: "r-1" })];
    await openRenewals(ADMIN);
    expect(screen.getByRole("button", { name: "Solicitar renovación de la suscripción SUB-777" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Solicitar renovación de la suscripción SUB-OPEN" })).toBeNull();
    expect(screen.getByRole("button", { name: "Ver solicitud de la suscripción SUB-OPEN" })).toBeTruthy();
    cleanup();
    await openRenewals(READONLY);
    expect(screen.queryByRole("button", { name: /Solicitar renovación/ })).toBeNull();
  });

  it("«Ver solicitud» abre el detalle de esa solicitud", async () => {
    tasks = [task({ request_id: "req-55" })];
    await openRenewals(READONLY);
    fireEvent.click(screen.getByRole("button", { name: "Ver solicitud de la suscripción SUB-777" }));
    expect(await screen.findByRole("heading", { name: /Renovación de calendario/ })).toBeTruthy();
    expect(mocks.getJson).toHaveBeenCalledWith("/api/v1/billing/changes/req-55");
  });

  it("el diálogo abre prellenado y no editable, exige vista previa y al crear refresca las tareas", async () => {
    await openRenewals(ADMIN);
    fireEvent.click(screen.getByRole("button", { name: "Solicitar renovación de la suscripción SUB-777" }));
    const dialog = await screen.findByRole("dialog");
    const type = within(dialog).getByLabelText("Tipo de cambio") as HTMLInputElement;
    const platform = within(dialog).getByLabelText("Plataforma") as HTMLInputElement;
    const sub = within(dialog).getByLabelText("ID de suscripción") as HTMLInputElement;
    expect(type.value).toBe("Renovación de calendario");
    expect(platform.value).toBe("VirtualPOS 1");
    expect(sub.value).toBe("SUB-777");
    for (const el of [type, platform, sub]) expect(el.readOnly).toBe(true);
    expect(within(dialog).getByText("$12.000").className).toContain("mono");

    const send = within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    mocks.postJson.mockResolvedValueOnce(preview()).mockResolvedValueOnce(reqDetail("new-1"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    await waitFor(() => expect(send.disabled).toBe(false));
    expect(mocks.postJson).toHaveBeenCalledWith("/api/v1/billing/changes/preview", expect.objectContaining({
      request_type: "renew_calendar", platform: "virtualpos1", subscription_external_id: "SUB-777",
    }));

    const before = renewalCalls().length;
    fireEvent.click(send);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.postJson).toHaveBeenLastCalledWith("/api/v1/billing/changes", expect.objectContaining({ request_type: "renew_calendar", subscription_external_id: "SUB-777" }));
    await waitFor(() => expect(renewalCalls().length).toBeGreaterThan(before));
    expect(await screen.findByText(/Solicitud creada y pendiente de aprobación/)).toBeTruthy();
  });

  it("un 409 open_request_exists se muestra en el diálogo", async () => {
    await openRenewals(ADMIN);
    fireEvent.click(screen.getByRole("button", { name: "Solicitar renovación de la suscripción SUB-777" }));
    const dialog = await screen.findByRole("dialog");
    mocks.postJson.mockResolvedValueOnce(preview()).mockRejectedValueOnce(apiError(409, { code: "open_request_exists", open_request_id: "x1" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    const send = within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement;
    await waitFor(() => expect(send.disabled).toBe(false));
    fireEvent.click(send);
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Ya existe una solicitud abierta");
  });
});
