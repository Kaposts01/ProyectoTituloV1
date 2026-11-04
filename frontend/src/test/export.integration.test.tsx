/**
 * Botón «Exportar» en cada lista (EXP-04): la entidad, el canal y los filtros activos que se envían
 * al contrato de /api/v1/export, el nombre del archivo y los permisos. Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ALL_PERMISSIONS, appReady, listSettled, mountApp, resetApp, type Call, type Handler } from "./appHarness";
import { page, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPlan, paykuClient } from "./fixtures";

let saved: string[];
beforeEach(() => {
  saved = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:sintetico"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { saved.push(this.download); });
});
afterEach(() => { vi.restoreAllMocks(); resetApp(); });

const recordsHandler = (body: unknown): Handler => ["GET", "/api/v1/staging/records", body];
const exportHandlers = (entity: string, rows: number, includePii = false, disposition = `attachment; filename="${entity}-20261029.csv"`): Handler[] => [
  ["GET", `/api/v1/export/${entity}/count`, { entity, rows, canales: [], include_pii: includePii }],
  ["GET", `/api/v1/export/${entity}`, { __file: { text: "id\n1\n", disposition } }],
];
const lastExport = (app: { calls: Call[] }, suffix = "") => app.calls.filter((c) => c.path === `/api/v1/export/${suffix}`).at(-1)!;

async function exportAll() {
  fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
  fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
  return screen.findByRole("button", { name: /Descargar/ });
}

describe("Exportar: clientes y suscripciones consolidados", () => {
  it("clientes: envía búsqueda y campo activos, sin canal, y guarda el archivo con el nombre del header", async () => {
    const app = mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 100 }],
      ...exportHandlers("clientes", 42, true),
    ]);
    await appReady();
    fireEvent.change(await screen.findByLabelText("Campo de búsqueda de clientes"), { target: { value: "email" } });
    fireEvent.change(screen.getByLabelText("Buscar cliente consolidado"), { target: { value: "socio" } });
    const download = await exportAll();
    expect(screen.getByText("42 filas")).toBeTruthy();
    expect(screen.getByText(/incluirá datos personales/)).toBeTruthy();
    const count = lastExport(app, "clientes/count");
    expect(Object.fromEntries(count.query)).toEqual({ filter_field: "email", query: "socio" });
    fireEvent.click(download);
    await waitFor(() => expect(saved).toEqual(["clientes-20261029.csv"]));
    expect(Object.fromEntries(lastExport(app, "clientes").query)).toEqual({ filter_field: "email", query: "socio", all: "true" });
  });

  // Cambio deliberado (UX-08): la vista unificada pagina de a 50 en el servidor.
  it("suscripciones: «Esta vista» envía el offset de la página", async () => {
    const app = mountApp("/central/suscripciones?offset=100", [
      ["GET", "/api/v1/general/subscriptions", { items: [], total: 300, offset: 100, limit: 50, by_channel: {}, canales: [] }],
      ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [], canales: [] }],
      ...exportHandlers("suscripciones", 300),
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Descargar CSV" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    const q = lastExport(app, "suscripciones").query;
    expect([q.get("offset"), q.get("limit"), q.has("all")]).toEqual(["100", "50", false]);
  });
});

describe("Exportar: listas de staging", () => {
  it("Toku clientes: entidad clientes, canal toku y la búsqueda activa", async () => {
    const app = mountApp("/toku/clientes", [recordsHandler(page([tokuCustomer(1)])), ...exportHandlers("clientes", 3)]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 22222221-2" });
    fireEvent.change(screen.getByLabelText("Campo"), { target: { value: "government_id" } });
    fireEvent.change(screen.getByPlaceholderText("Buscar por RUT"), { target: { value: "2222" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/records").at(-1)?.query.get("query")).toBe("2222"));
    await listSettled();
    await exportAll();
    expect(Object.fromEntries(lastExport(app, "clientes/count").query)).toEqual({ canal: "toku", filter_field: "rut", query: "2222" });
  });

  it("Toku suscripciones: el filtro de estado va como `status`", async () => {
    const app = mountApp("/toku/suscripciones", [
      recordsHandler(page([tokuSubscription(1)])),
      ["GET", "/api/v1/staging/records/filter-values", { values: ["ACTIVE"] }],
      ...exportHandlers("suscripciones", 1),
    ]);
    await appReady();
    await screen.findByText("TOKU / STAGING");
    fireEvent.change(screen.getByLabelText("Campo"), { target: { value: "status" } });
    fireEvent.change(await screen.findByDisplayValue("Todos los estados"), { target: { value: "ACTIVE" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/records").at(-1)?.query.get("query")).toBe("ACTIVE"));
    await exportAll();
    expect(Object.fromEntries(lastExport(app, "suscripciones/count").query)).toEqual({ canal: "toku", status: "ACTIVE" });
  });

  it("Toku deudas se exporta como cobros y Toku transacciones como pagos", async () => {
    for (const [path, entity] of [["/toku/deudas", "cobros"], ["/toku/transacciones", "pagos"]] as const) {
      const app = mountApp(path, [recordsHandler(page([])), ...exportHandlers(entity, 0)]);
      await appReady();
      fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
      fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
      await screen.findByText("0 filas");
      expect(lastExport(app, `${entity}/count`).query.get("canal")).toBe("toku");
      resetApp();
    }
  });

  it("Payku clientes: canal payku", async () => {
    const app = mountApp("/payku/clientes", [recordsHandler(page([paykuClient(1)])), ...exportHandlers("clientes", 9)]);
    await appReady();
    await exportAll();
    expect(lastExport(app, "clientes/count").query.get("canal")).toBe("payku");
  });

  it("VirtualPOS cargos: plataforma elegida, filtros por columna y avisos de lo que no se puede enviar", async () => {
    const app = mountApp("/virtualpos/cargos", [recordsHandler(page([vpCharge(1, "PAID")])), ...exportHandlers("cobros", 8)]);
    await appReady();
    await screen.findByRole("button", { name: "VP 1" });
    fireEvent.click(screen.getByRole("button", { name: "VP 1" }));
    fireEvent.change(await screen.findByLabelText("Monto mínimo"), { target: { value: "500" } });
    fireEvent.change(await screen.findByLabelText("Fecha de cargo desde"), { target: { value: "2025-01-01" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/records").at(-1)?.query.get("amount_min")).toBe("500"));
    await listSettled();
    await exportAll();
    expect(Object.fromEntries(lastExport(app, "cobros/count").query)).toEqual({ canal: "virtualpos1", amount_min: "500", date_from: "2025-01-01" });
  });

  it("VirtualPOS sin plataforma específica usa el canal virtualpos; los planes no tienen botón", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page([vpClient(1)])), ...exportHandlers("clientes", 2)]);
    await appReady();
    await exportAll();
    expect(lastExport(app, "clientes/count").query.get("canal")).toBe("virtualpos");
    resetApp();
    mountApp("/virtualpos/planes", [recordsHandler(page([vpPlan(1)]))]);
    await appReady();
    await screen.findByText("VIRTUALPOS / STAGING");
    expect(screen.queryByRole("button", { name: /Exportar/ })).toBeNull();
  });

  it("error 403 del servidor: mensaje claro y ninguna descarga", async () => {
    const app = mountApp("/toku/clientes", [
      recordsHandler(page([tokuCustomer(1)])),
      ["GET", "/api/v1/export/clientes/count", { __status: 403, body: { detail: "Sin permiso" } }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    expect((await screen.findByRole("alert")).textContent).toBe("Tu rol no puede exportar este recurso.");
    expect(app.calls.some((c) => c.path === "/api/v1/export/clientes")).toBe(false);
    expect(saved).toHaveLength(0);
  });

  it("la pista de datos personales sale del permiso export.pii de la sesión", async () => {
    mountApp("/toku/clientes", [recordsHandler(page([tokuCustomer(1)])), ...exportHandlers("clientes", 1)], { permissions: [...ALL_PERMISSIONS, "export.pii"] });
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
    expect(screen.getByText(/puede exportar con datos personales/)).toBeTruthy();
    resetApp();
    mountApp("/toku/clientes", [recordsHandler(page([tokuCustomer(1)])), ...exportHandlers("clientes", 1)]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: /Exportar/ }));
    expect(screen.getByText(/exporta sin datos personales/)).toBeTruthy();
  });
});

describe("Exportar: TCH", () => {
  const tchList = { total: 0, page: 1, limit: 100, pages: 1, items: [] };

  it("transacciones: entidad cobros, canal tch y el período como mes completo", async () => {
    const app = mountApp("/tch/transacciones", [["GET", "/api/v1/tch/transacciones", tchList], ...exportHandlers("cobros", 12, false, 'attachment; filename="cobros-tch-20261029.csv"')]);
    await appReady();
    fireEvent.change(await screen.findByLabelText("Filtrar por período"), { target: { value: "2025-02" } });
    const download = await exportAll();
    expect(Object.fromEntries(lastExport(app, "cobros/count").query)).toEqual({ canal: "tch", date_from: "2025-02-01", date_to: "2025-02-28" });
    fireEvent.click(download);
    await waitFor(() => expect(saved).toEqual(["cobros-tch-20261029.csv"]));
  });

  it("suscripciones: el estado va como `status`; clientes: el nombre como búsqueda", async () => {
    const app = mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", tchList], ...exportHandlers("suscripciones", 4)]);
    await appReady();
    fireEvent.change(await screen.findByLabelText("Filtrar por estado"), { target: { value: "VIGENTE" } });
    await exportAll();
    expect(Object.fromEntries(lastExport(app, "suscripciones/count").query)).toEqual({ canal: "tch", status: "VIGENTE" });
    resetApp();
    const app2 = mountApp("/tch/clientes", [["GET", "/api/v1/tch/clientes", tchList], ...exportHandlers("clientes", 4)]);
    await appReady();
    fireEvent.change(await screen.findByLabelText("Buscar cliente"), { target: { value: "ana" } });
    const download = await exportAll();
    expect(within(download.closest("[role=group]") as HTMLElement).getByText("4 filas")).toBeTruthy();
    expect(Object.fromEntries(lastExport(app2, "clientes/count").query)).toEqual({ canal: "tch", filter_field: "name", query: "ana" });
  });
});
