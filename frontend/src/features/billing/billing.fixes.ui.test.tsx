import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn(), setCsrfToken: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson,
  postJson: mocks.postJson,
  putJson: mocks.putJson,
  setCsrfToken: mocks.setCsrfToken,
  friendlyError: (_e: unknown, f: string) => f,
}));

import { BillingInbox } from "./BillingInbox";

const apiError = (status: number | null, detail: unknown) => Object.assign(new Error("texto crudo 12.345.678-9"), { status, detail });
const ADMIN = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.request", "virtualpos.billing_changes.approve", "virtualpos.billing_policy.manage"];
const canOf = (perms: string[]) => (p: string) => perms.includes(p);

const PLAN = {
  noop: false, cancel: [], create: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000, internal_code: "S1-202604" }],
  covered: [], manual_review: [], unchanged: [], kept_automatic_after_horizon: [], warnings: [], errors: [],
  summary: { creates: 1, cancels: 0, covered_months: 0, manual_review_months: 0, unchanged_months: 0, affected_charges: 1, previous_amount: 5000, new_amount: 8000, amount_delta: 3000, total_delta: 3000, variation_pct: 60, horizon_start: "2026-04", horizon_end: "2027-03" },
};

function req(over: Record<string, unknown> = {}) {
  return {
    id: "r1", request_type: "change_amount", platform: "virtualpos1", subscription_external_id: "SUB-100", status: "pendiente",
    requested_by_user_id: "u1", requested_by: "ana", new_amount: 8000, previous_amount: 5000, new_charge_day: null, previous_charge_day: null,
    new_charge_date: null, horizon_months: 12, horizon_start_month: "2026-04", approvals_required: 1, approvals_count: 0,
    requester_comment: null, approved_by_user_id: null, approved_by: null, self_approved: false, decided_at: null,
    decision_comment: null, write_run_id: null, expires_at: null, executed_at: null,
    error_message: null, created_at: "2026-03-01T10:00:00+00:00", updated_at: null, ...over,
  };
}
const EV = { id: "e1", event_type: "creada", actor_user_id: "u1", actor: "ana", detail: {}, created_at: "2026-03-01T10:00:00+00:00" };
function detail(over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) {
  return { ...req(over), plan_preview: PLAN, rules_snapshot: {}, events: [EV], ...extra };
}
const applyOk = (over: Record<string, unknown> = {}) => ({
  request_id: "r1", status: "ejecutada", request_status: "ejecutada", already_applied: false, reason: null,
  created: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000 }, { month: "2026-05", charge_date: "2026-05-10", amount: 8000 }],
  cancelled: ["chg-1"], covered_late_months: [], manual_review_months: ["2026-03", "2026-02"], drift_accepted: false, plan_summary: null, ...over,
});

let listItems: ReturnType<typeof req>[] = [];
let listTotal: number | null = null;
let detailData = detail();
const listCalls = () => mocks.getJson.mock.calls.map((c) => c[0] as string).filter((p) => p.startsWith("/api/v1/billing/changes?"));
const detailCalls = () => mocks.getJson.mock.calls.map((c) => c[0] as string).filter((p) => /^\/api\/v1\/billing\/changes\/r1$/.test(p));

beforeEach(() => {
  mocks.getJson.mockReset(); mocks.postJson.mockReset(); mocks.putJson.mockReset(); mocks.setCsrfToken.mockReset();
  listItems = [req()];
  listTotal = null;
  detailData = detail();
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: [] };
    if (path === "/api/v1/auth/me") return { user: { id: "u1" }, csrf_token: "token-nuevo" };
    if (path.startsWith("/api/v1/billing/renewal-tasks")) return { items: [], total: 0, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes?")) return { items: listItems, total: listTotal ?? listItems.length, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes/")) return detailData;
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

async function openDetail(props: Record<string, unknown> = {}, perms = ADMIN) {
  render(<BillingInbox can={canOf(perms)} {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de la suscripción SUB-100/ }));
  await screen.findByRole("heading", { name: /Cambio de monto/ });
}
async function runApply() {
  fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
  const dialog = await screen.findByRole("dialog", { name: "Aplicar cambio en VirtualPOS" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Aplicar ahora" }));
  return dialog;
}
const approved = () => { listItems = [req({ status: "aprobada" })]; detailData = detail({ status: "aprobada" }); };

describe("1-2. resultado de aplicar", () => {
  it("1: muestra los conteos con la forma real (listas) sin [object Object]", async () => {
    approved();
    mocks.postJson.mockResolvedValue(applyOk());
    await openDetail();
    await runApply();
    const note = await screen.findByText(/Cambio aplicado/);
    expect(note.textContent).toContain("Cambio aplicado: 2 cobros creados y 1 cancelados; 2 meses quedan en revisión manual.");
    expect(document.body.textContent).not.toContain("[object Object]");
  });

  it("2: no_ejecutable se muestra como advertencia, no como exito, y sin el texto del servidor", async () => {
    approved();
    mocks.postJson.mockResolvedValue(applyOk({ status: "no_ejecutable", request_status: "no_ejecutable", reason: "subscription_not_active", created: [], cancelled: [], manual_review_months: [] }));
    await openDetail();
    await runApply();
    const note = await screen.findByText(/La solicitud no se pudo ejecutar/);
    expect(note.className).toContain("bx-notice-warning");
    expect(note.textContent).toMatch(/la suscripción ya no es ejecutable/);
    expect(document.body.textContent).not.toContain("Cambio aplicado");
    expect(document.body.textContent).not.toContain("subscription_not_active");
  });
});

describe("3. errores de aplicar/reabrir sin respuesta definitiva", () => {
  it.each([[500, "Internal Server Error"], [504, "Gateway Timeout"], [null, undefined]] as Array<[number | null, unknown]>)(
    "apply con %s recarga el detalle y avisa que se revise el estado", async (status, body) => {
      approved();
      mocks.postJson.mockRejectedValue(apiError(status, body));
      await openDetail();
      const before = detailCalls().length;
      const listBefore = listCalls().length;
      const dialog = await runApply();
      const alert = await within(dialog).findByRole("alert");
      expect(alert.textContent).toMatch(/Revise el estado de la solicitud antes de reintentar/);
      expect(alert.textContent).toMatch(/puede haberse aplicado/);
      await waitFor(() => expect(detailCalls().length).toBe(before + 1));
      await waitFor(() => expect(listCalls().length).toBe(listBefore + 1));
    });

  it("reabrir con 500 tambien recarga", async () => {
    listItems = [req({ status: "fallida" })];
    detailData = detail({ status: "fallida" });
    mocks.postJson.mockRejectedValue(apiError(500, "boom"));
    await openDetail();
    const before = detailCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Reabrir" }));
    const dialog = await screen.findByRole("dialog", { name: "Reabrir solicitud" });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "revisado" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reabrir" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/Revise el estado de la solicitud antes de reintentar/);
    await waitFor(() => expect(detailCalls().length).toBe(before + 1));
  });

  it("una falla definitiva con codigo (apply_failed) no agrega la advertencia de incertidumbre", async () => {
    approved();
    mocks.postJson.mockRejectedValue(apiError(502, { code: "apply_failed", message: "x" }));
    await openDetail();
    const dialog = await runApply();
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).not.toMatch(/puede haberse aplicado/);
  });
});

describe("4. CSRF obsoleto", () => {
  it("403 sin code: refresca el token y reintenta una sola vez con exito", async () => {
    mocks.postJson.mockRejectedValueOnce(apiError(403, "Invalid CSRF token")).mockResolvedValueOnce(detail({ status: "aprobada" }));
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    const dialog = await screen.findByRole("dialog", { name: "Aprobar solicitud" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aprobar" }));
    expect(await screen.findByText(/Solicitud aprobada/)).toBeTruthy();
    expect(mocks.postJson).toHaveBeenCalledTimes(2);
    expect(mocks.getJson).toHaveBeenCalledWith("/api/v1/auth/me");
    expect(mocks.setCsrfToken).toHaveBeenCalledWith("token-nuevo");
  });

  it("si vuelve a fallar: un solo reintento y mensaje de sesion desactualizada", async () => {
    mocks.postJson.mockRejectedValue(apiError(403, "Invalid CSRF token"));
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    const dialog = await screen.findByRole("dialog", { name: "Aprobar solicitud" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aprobar" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Sesión desactualizada: recargue la página");
    expect(mocks.postJson).toHaveBeenCalledTimes(2);
  });

  it("403 con code estructurado nunca se reintenta", async () => {
    mocks.postJson.mockRejectedValue(apiError(403, { code: "not_approver", message: "x" }));
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
    const dialog = await screen.findByRole("dialog", { name: "Aprobar solicitud" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aprobar" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/no es aprobador/);
    expect(mocks.postJson).toHaveBeenCalledTimes(1);
    expect(mocks.setCsrfToken).not.toHaveBeenCalled();
  });
});

describe("5. paginacion tras actuar sobre el ultimo item", () => {
  it("bandeja: items vacios con total>0 reposiciona a la ultima pagina y no muestra el vacio", async () => {
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path === "/api/v1/billing/requesters") return { items: [] };
      if (path.startsWith("/api/v1/billing/renewal-tasks")) return { items: [], total: 0, limit: 25, offset: 0 };
      if (path.includes("offset=25")) return { items: [], total: 25, limit: 25, offset: 25 };
      if (path.startsWith("/api/v1/billing/changes?")) return { items: [req()], total: 30, limit: 25, offset: 0 };
      throw new Error(`ruta ${path}`);
    });
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(listCalls().some((p) => p.includes("offset=25"))).toBe(true));
    await waitFor(() => expect(listCalls().filter((p) => p.includes("offset=0")).length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByText(/No hay solicitudes/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/26-25 de 25/);
  });

  it("renovaciones: igual", async () => {
    const task = { id: "t1", platform: "virtualpos1", subscription_external_id: "SUB-777", status: "abierta", priority: "normal", last_scheduled_date: "2026-12-01", scheduled_amount: 1, due_date: "2026-12-01", days_remaining: 5, data_stale: false, request_id: null, close_reason: null };
    mocks.getJson.mockImplementation(async (path: string) => {
      if (path === "/api/v1/billing/requesters") return { items: [] };
      if (path.startsWith("/api/v1/billing/renewal-tasks")) {
        if (path.includes("limit=1&")) return { items: [], total: 0, limit: 1, offset: 0 };
        if (path.includes("offset=25")) return { items: [], total: 25, limit: 25, offset: 25 };
        return { items: [task], total: 30, limit: 25, offset: 0 };
      }
      if (path.startsWith("/api/v1/billing/changes?")) return { items: [], total: 0, limit: 25, offset: 0 };
      throw new Error(`ruta ${path}`);
    });
    render(<BillingInbox can={canOf(ADMIN)} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
    await screen.findByRole("table", { name: /Tareas de renovación/ });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    const calls = () => mocks.getJson.mock.calls.map((c) => c[0] as string).filter((p) => p.startsWith("/api/v1/billing/renewal-tasks") && !p.includes("limit=1&"));
    await waitFor(() => expect(calls().filter((p) => p.includes("offset=0")).length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByText(/No hay renovaciones/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/26-25 de 25/);
    expect(await screen.findByRole("table", { name: /Tareas de renovación/ })).toBeTruthy();
  });

  it("el vacio solo se muestra con total=0", async () => {
    listItems = [];
    render(<BillingInbox can={canOf(ADMIN)} />);
    expect(await screen.findByText(/No hay solicitudes pendientes/)).toBeTruthy();
  });
});

describe("6. zona horaria y filtros de fecha", () => {
  it("muestra horas de Chile con rotulo y los filtros de fecha avisan UTC", async () => {
    await openDetail();
    // 2026-03-01T10:00Z -> 07:00 en Chile (verano, UTC-3)
    expect(screen.getAllByText("2026-03-01 07:00").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/hora de Chile/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Filtros por fecha en UTC · resultados en hora de Chile")).toBeTruthy();
  });
});

describe("7. onCreated", () => {
  const preview = { plan_preview: PLAN, summary: PLAN.summary, approvals_required: 1, would_self_approve: false, expires_in_days: 7, open_request: null };
  it("vuelve a Pendientes sin filtro de estado y carga la lista una sola vez", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "pendiente" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => expect(listCalls().some((p) => p.includes("status=pendiente"))).toBe(true));
    await waitFor(() => expect((screen.getByRole("button", { name: "Buscar" }) as HTMLButtonElement).disabled).toBe(false));

    mocks.postJson.mockResolvedValueOnce(preview).mockResolvedValueOnce(detail());
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    const dialog = await screen.findByRole("dialog", { name: /Nueva solicitud/ });
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    await within(dialog).findByText("Vista previa del plan");
    const before = listCalls().length;
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar solicitud" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /Nueva solicitud/ })).toBeNull());
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(before));
    await new Promise((r) => setTimeout(r, 60));
    expect(listCalls().length - before).toBe(1);
    expect(listCalls()[listCalls().length - 1]).toContain("status=aprobada"); // ya no filtra solo «pendiente»
    expect((screen.getByLabelText("Estado") as HTMLSelectElement).value).toBe("");
  });
});

describe("8. permisos finos", () => {
  it("Retirar solo para el solicitante o un admin (cuando se conoce el usuario)", async () => {
    await openDetail({ currentUserId: "u2" });
    expect(screen.queryByRole("button", { name: "Retirar" })).toBeNull();
    cleanup();
    await openDetail({ currentUserId: "u1" });
    expect(screen.getByRole("button", { name: "Retirar" })).toBeTruthy();
    cleanup();
    await openDetail({ currentUserId: "u2", isAdmin: true });
    expect(screen.getByRole("button", { name: "Retirar" })).toBeTruthy();
  });

  it("Aprobar queda deshabilitado con motivo si el usuario ya aprobó", async () => {
    detailData = detail({ approvals_required: 2, approvals_count: 1 }, { events: [EV, { ...EV, id: "e2", event_type: "aprobada", actor_user_id: "u2", actor: "beto" }] });
    await openDetail({ currentUserId: "u2" });
    const btn = screen.getByRole("button", { name: "Aprobar" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByText(/Usted ya aprobó esta solicitud/)).toBeTruthy();
    cleanup();
    await openDetail({ currentUserId: "u3" });
    expect((screen.getByRole("button", { name: "Aprobar" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("las aprobaciones anteriores a una reapertura no cuentan", async () => {
    detailData = detail({ approvals_required: 2, approvals_count: 0 }, { events: [EV, { ...EV, id: "e2", event_type: "aprobada", actor_user_id: "u2" }, { ...EV, id: "e3", event_type: "reintentada", actor_user_id: "u1", detail: {} }] });
    await openDetail({ currentUserId: "u2" });
    expect((screen.getByRole("button", { name: "Aprobar" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("el solicitante no puede aprobar si hay doble aprobacion (salvo autoaprobacion vigente en la regla)", async () => {
    detailData = detail({ approvals_required: 2 });
    await openDetail({ currentUserId: "u1" });
    expect((screen.getByRole("button", { name: "Aprobar" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/solicitante no puede aprobar/i)).toBeTruthy();
    cleanup();
    detailData = detail({ approvals_required: 2 }, { rules_snapshot: { self_approval_enabled: true } });
    await openDetail({ currentUserId: "u1" });
    expect((screen.getByRole("button", { name: "Aprobar" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("9. textos del servidor nunca se renderizan", () => {
  it("avisos y errores del plan por codigo, kept_due_today y motivos de revision manual", async () => {
    detailData = detail({}, {
      plan_preview: {
        ...PLAN,
        warnings: [{ code: "due_today_kept", message: "SERVIDOR aviso 12.345.678-9", month: "2026-04" }, { code: "codigo_nuevo", message: "SERVIDOR otro" }],
        errors: [{ code: "invalid_amount", message: "SERVIDOR error 77", month: null }],
        manual_review: [{ month: "2026-02", target_date: "2026-02-05", days_overdue: 40, reason: "older_than_window" }],
        kept_due_today: ["2026-04"],
      },
    });
    await openDetail();
    expect(document.body.textContent).not.toContain("SERVIDOR");
    expect(document.body.textContent).not.toContain("older_than_window");
    expect(screen.getByText("Cobros de hoy conservados")).toBeTruthy();
    expect(screen.getByText("Aviso del plan no reconocido.")).toBeTruthy();
  });

  it("plan_errors de una accion y del dialogo de creacion", async () => {
    approved();
    mocks.postJson.mockRejectedValue(apiError(422, { code: "plan_errors", message: "x", errors: [{ code: "past_charge_date", message: "SERVIDOR fecha", month: null }] }));
    await openDetail();
    const dialog = await runApply();
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).not.toContain("SERVIDOR");
    expect(alert.textContent).toMatch(/fecha/i);
  });

  it("vista previa de una solicitud abierta usa la etiqueta del estado", async () => {
    mocks.postJson.mockResolvedValueOnce({ plan_preview: PLAN, summary: PLAN.summary, approvals_required: 1, would_self_approve: false, expires_in_days: 7, open_request: { id: "x", status: "pendiente" } });
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    const dialog = await screen.findByRole("dialog", { name: /Nueva solicitud/ });
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-100" } });
    fireEvent.change(within(dialog).getByLabelText("Monto (CLP)"), { target: { value: "8000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Calcular vista previa" }));
    expect((await within(dialog).findByText(/Ya existe una solicitud abierta/)).textContent).toMatch(/estado: Pendiente/);
  });
});

describe("10. errores nuevos en la interfaz", () => {
  const cases: Array<[number, Record<string, unknown>, RegExp]> = [
    [502, { code: "provider_listing_incomplete", message: "x" }, /No se pudo leer completo el listado de cobros del proveedor; reintente/],
    [422, { code: "unparseable_charges", message: "x", count: 2, by_status: { pagado: 2 } }, /2 cobros/],
    [409, { code: "billing_flow_conflict", message: "x" }, /flujo de solicitudes/],
    [409, { code: "charge_not_found", message: "x" }, /ya no existe/],
    [409, { code: "billing_apply_error", message: "x" }, /No se pudo aplicar/],
  ];
  it.each(cases)("aplicar con %i %o", async (status, body, re) => {
    approved();
    mocks.postJson.mockRejectedValue(apiError(status, body));
    await openDetail();
    const dialog = await runApply();
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(re);
  });
  it("subscription_blocked al reabrir", async () => {
    listItems = [req({ status: "fallida" })];
    detailData = detail({ status: "fallida" });
    mocks.postJson.mockRejectedValue(apiError(409, { code: "subscription_blocked", message: "x" }));
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Reabrir" }));
    const dialog = await screen.findByRole("dialog", { name: "Reabrir solicitud" });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "ok" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reabrir" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/conciliación/);
  });
});

describe("11. etiqueta tecnica y linea de tiempo", () => {
  it("fallida muestra 'Código técnico' en mono con nota generica", async () => {
    detailData = detail({ status: "fallida", error_message: "VirtualPOSAPIError E-113" }, {
      events: [EV, { ...EV, id: "e2", event_type: "fallida", detail: { error: "RuntimeError" } }],
    });
    listItems = [req({ status: "fallida" })];
    await openDetail();
    const tags = screen.getAllByText("VirtualPOSAPIError E-113");
    expect(tags[0].className).toContain("mono");
    expect(screen.getAllByText(/Código técnico/).length).toBeGreaterThan(0);
    expect(screen.getByText("RuntimeError").className).toContain("mono");
  });
  it("evento reintentada con claves nuevas y sin ellas", async () => {
    detailData = detail({}, {
      events: [EV,
        { ...EV, id: "e2", event_type: "reintentada", detail: { to_status: "pendiente", previous_approvals_count: 1, previous_approvals_required: 2, new_approvals_required: 2, previous_error: "StuckApplying", comment: "revisado" } },
        { ...EV, id: "e3", event_type: "reintentada", detail: {} }],
    });
    await openDetail();
    expect(screen.getAllByText("Reabierta").length).toBe(2);
    expect(screen.getAllByText(/aprobaciones reiniciadas/i).length).toBe(2);
    expect(screen.getByText("StuckApplying").className).toContain("mono");
  });
});

describe("13. accesibilidad y diseño", () => {
  it("pestañas: roles, aria-controls/labelledby y flechas", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    const pending = await screen.findByRole("tab", { name: "Pendientes" });
    const panel = screen.getByRole("tabpanel");
    expect(pending.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(pending.id);
    pending.focus();
    fireEvent.keyDown(pending, { key: "ArrowRight" });
    const history = screen.getByRole("tab", { name: "Historial" });
    expect(history.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(history);
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(history.id);
    fireEvent.keyDown(history, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Pendientes" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Pendientes" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: /Renovaciones/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("el dialogo deja inert/aria-hidden el resto de la pagina y lo restaura", async () => {
    const { container } = render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    await screen.findByRole("dialog");
    expect(container.hasAttribute("inert")).toBe(true);
    expect(container.getAttribute("aria-hidden")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(container.hasAttribute("inert")).toBe(false);
    expect(container.hasAttribute("aria-hidden")).toBe(false);
  });

  it("clic en el fondo con cambios en Nueva solicitud no cierra; sin cambios si", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    let dialog = await screen.findByRole("dialog");
    const backdrop = () => dialog.parentElement as HTMLElement;
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "SUB-1" } });
    fireEvent.mouseDown(backdrop());
    expect(screen.queryByRole("dialog")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("ID de suscripción"), { target: { value: "" } });
    fireEvent.mouseDown(backdrop());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    dialog = await screen.findByRole("dialog");
    fireEvent.mouseDown(backdrop());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
