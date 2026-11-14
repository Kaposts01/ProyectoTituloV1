/**
 * Caracterización de las vistas consolidadas de AppCore (UX-04): clientes y suscripciones
 * consolidados y panel ETL. Datos sintéticos.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, listSettled, failWith, mountApp, resetApp, type Handler } from "./appHarness";

afterEach(resetApp);

// La vista anterior del dashboard general (/central/resumen-clasico) se retiró en UX-15; su redirección al Resumen se
// prueba en navigation.characterization. El panel del ETL sigue en el marco de Socios.
describe("Panel ETL en Socios (/central/clientes)", () => {
  const clientsHandler: Handler = ["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 100 }];

  it("Sync completo: envía los proveedores habilitados, muestra el progreso y el resultado de la corrida", async () => {
    const app = mountApp("/central/clientes", [
      clientsHandler,
      ["POST", "/api/v1/etl/full-sync", { run_id: "run-1" }],
      ["GET", "/api/v1/etl/runs/run-1", { id: "run-1", status: "completed", phase: null, started_at: "2025-03-31T10:00:00", finished_at: "2025-03-31T10:05:00", records_upserted: 1234, channels_processed: ["virtualpos"], error_message: null }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "↻ Sync completo" }));
    // QA-02: el primer clic no sincroniza; pide confirmación y dice qué canales va a leer
    const dialog = screen.getByRole("alertdialog", { name: "Confirmar Sync completo" });
    expect(dialog.textContent).toContain("VirtualPOS, Toku y Payku");
    expect(app.find("POST", "/api/v1/etl/full-sync")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Sí, sincronizar VirtualPOS, Toku y Payku" }));
    await waitFor(() => expect(app.find("POST", "/api/v1/etl/full-sync")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/etl/full-sync")[0].body).toEqual({ providers: ["virtualpos", "toku", "payku"] });
    const busy = screen.getByRole("button", { name: "Procesando…" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(await screen.findByText(/1\.234 registros/, undefined, { timeout: 6000 })).toBeTruthy();
    expect(document.querySelector(".etl-status .status-pill")?.textContent).toBe("Completada");
    expect(screen.getByRole("button", { name: "↻ Sync completo" })).toBeTruthy();
    expect(app.find("GET", "/api/v1/etl/runs/run-1")).toHaveLength(1);
  }, 15000);

  it("QA-02: Cancelar cierra la confirmación sin sincronizar; sin etl.run no hay botón", async () => {
    const app = mountApp("/central/clientes", [clientsHandler, ["POST", "/api/v1/etl/full-sync", { run_id: "run-x" }]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "↻ Sync completo" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(app.find("POST", "/api/v1/etl/full-sync")).toHaveLength(0);
    resetApp();
    mountApp("/central/clientes", [clientsHandler], { permissions: ["dashboard.view"] });
    await appReady();
    expect(await screen.findByRole("heading", { name: "Socios", level: 1 })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "↻ Sync completo" })).toBeNull();
  });

  it("QA-02/QA-10: la cabecera usa el patrón de Cartera y el chip muestra el ambiente real (nunca «Staging local»)", async () => {
    mountApp("/central/clientes", [clientsHandler]);
    await appReady();
    expect(await screen.findByRole("heading", { name: "Socios", level: 1 })).toBeTruthy();
    expect(await screen.findByText("Test", { selector: ".sync-state" })).toBeTruthy();
    expect(screen.queryByText("Staging local")).toBeNull();
    expect(screen.queryByText(/Operación consolidada/)).toBeNull();
  });

  it("QA-02: en producción el chip de ambiente desaparece", async () => {
    mountApp("/central/clientes", [clientsHandler, ["GET", "/api/v1/system/environment", { app_env: "production", label: "Producción", is_production: true }]]);
    await appReady();
    await screen.findByRole("heading", { name: "Socios", level: 1 });
    await waitFor(() => expect(document.querySelector(".topbar .sync-state")).toBeNull());
  });

  it("Sync completo: si falla el inicio muestra el error y vuelve a habilitar el botón", async () => {
    mountApp("/central/clientes", [clientsHandler, ["POST", "/api/v1/etl/full-sync", failWith(409, "ya hay una corrida")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "↻ Sync completo" }));
    fireEvent.click(screen.getByRole("button", { name: /^Sí, sincronizar/ }));
    expect(await screen.findByText("ya hay una corrida")).toBeTruthy();
    expect((screen.getByRole("button", { name: "↻ Sync completo" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

const client = (n: number) => ({ rut: `1111111${n}-1`, name: `Persona Sintética ${n}`, origins: ["VirtualPOS", "Toku"], active_origins: n === 1 ? ["VirtualPOS"] : [] });

describe("Clientes consolidados (/central/clientes)", () => {
  const list = { items: [client(1), client(2)], total: 250, offset: 0, limit: 50 };

  it("UX-10: filtros de canal y estado van a la API, el canal al Exportar y se avisa que el RUT no está verificado", async () => {
    const app = mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", list],
      ["GET", "/api/v1/export/clientes/count", { entity: "clientes", rows: 3, canales: [], include_pii: false }],
    ]);
    await appReady();
    await screen.findByRole("button", { name: "11.111.111-1" });
    expect(screen.getByText(/no verificado/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Canal de los socios"), { target: { value: "tch" } });
    fireEvent.change(screen.getByLabelText("Estado de los socios"), { target: { value: "active" } });
    await waitFor(() => {
      const last = app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)!;
      expect([last.query.get("canal"), last.query.get("status"), last.query.get("offset")]).toEqual(["tch", "active", "0"]);
    });
    fireEvent.click(screen.getByRole("button", { name: /Exportar/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    expect(await screen.findByText(/sin esos filtros/)).toBeTruthy();
    expect(app.find("GET", "/api/v1/export/clientes/count").at(-1)?.query.get("canal")).toBe("tch");
  });

  it("d143: chips de filtros en Socios; «×» quita uno y «Limpiar filtros» los quita todos", async () => {
    const app = mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", list]]);
    await appReady();
    await screen.findByRole("button", { name: "11.111.111-1" });
    expect(document.querySelector(".filter-count")?.textContent).toBe("250 socios");
    fireEvent.change(screen.getByLabelText("Canal de los socios"), { target: { value: "tch" } });
    fireEvent.change(screen.getByLabelText("Estado de los socios"), { target: { value: "active" } });
    fireEvent.click(screen.getByRole("button", { name: "Quitar filtro Canal: TCH" }));
    expect((screen.getByLabelText("Canal de los socios") as HTMLSelectElement).value).toBe("");
    expect(screen.getByText("Estado: Con suscripción activa")).toBeTruthy();
    await waitFor(() => {
      const last = app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)!;
      expect([last.query.get("canal"), last.query.get("status")]).toEqual([null, "active"]);
    });
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    expect((screen.getByLabelText("Estado de los socios") as HTMLSelectElement).value).toBe("");
    expect(screen.queryByRole("list", { name: "Filtros activos" })).toBeNull();
  });

  it("pide la primera página y muestra título, columnas, filas y paginación", async () => {
    const app = mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", list]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "11.111.111-1" })).toBeTruthy();
    const call = app.find("GET", "/api/v1/staging/dashboard/general/clients")[0];
    expect(call.query.get("limit")).toBe("50"); // QA-10: 50 por página, como Cobros y Suscripciones
    expect(call.query.get("offset")).toBe("0");
    expect(call.query.get("filter_field")).toBe("all");
    expect(call.query.has("query")).toBe(false);
    // La vista inicial «summary» no carga el dashboard anterior (retirado en UX-15): el hallazgo 5 sigue resuelto.
    expect(app.exact("GET", "/api/v1/staging/dashboard/general")).toHaveLength(0);
    expect(app.exact("GET", "/api/v1/staging/summary")).toHaveLength(0);
    expect(screen.getByText("CLIENTES CONSOLIDADOS")).toBeTruthy();
    expect(screen.getByText("250 clientes por RUT")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["RUT", "Nombre completo", "Plataforma de origen", "Suscripciones activas"]);
    expect(screen.getAllByText("VirtualPOS · Toku").length).toBe(2);
    expect(screen.getByText("1-2 de 250")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("buscar, cambiar el campo y paginar piden la lista con los parámetros y reflejan campo y offset en la URL", async () => {
    const app = mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", list]]);
    await appReady();
    await screen.findByRole("button", { name: "11.111.111-1" });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)?.query.get("offset")).toBe("50"));
    expect(window.location.search).toBe("?offset=50");
    fireEvent.change(screen.getByLabelText("Campo de búsqueda de clientes"), { target: { value: "rut" } });
    await waitFor(() => {
      const last = app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)!;
      expect(last.query.get("filter_field")).toBe("rut");
      expect(last.query.get("offset")).toBe("0");
    });
    expect(window.location.search).toBe("?campo=rut");
    fireEvent.change(screen.getByLabelText("Buscar cliente consolidado"), { target: { value: " 1111 " } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)?.query.get("query")).toBe("1111"));
  });

  it("un enlace profundo con ?campo y ?offset se aplica a la primera petición", async () => {
    const app = mountApp("/central/clientes?campo=email&offset=200", [["GET", "/api/v1/staging/dashboard/general/clients", { ...list, offset: 200 }]]);
    await appReady();
    await screen.findByRole("button", { name: "11.111.111-1" });
    const last = app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)!;
    expect(last.query.get("filter_field")).toBe("email");
    expect(last.query.get("offset")).toBe("200");
  });

  it("sin clientes muestra «Sin clientes con RUT.»", async () => {
    mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 100 }]]);
    await appReady();
    expect(await screen.findByText("Sin clientes con RUT.")).toBeTruthy();
  });

  it("la ficha general pide el detalle por RUT y permite volver", async () => {
    const detail = {
      rut: "11111111-1",
      clients: [{ portal: "VirtualPOS", id_cliente: "C-1", external_id: "ext-c1" }],
      subscriptions: [{ portal: "VirtualPOS", id_subscription: "S-1", external_id: "ext-s1", status: "ACTIVA" }],
      charges: [{ portal: "VirtualPOS", id_cargo: "G-1", external_id: "ext-g1", status: "pagado", amount: "10000" }],
      transactions: [],
    };
    const app = mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", list],
      ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", detail],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "11.111.111-1" }));
    expect(await screen.findByRole("heading", { name: "Ficha general: 11.111.111-1" })).toBeTruthy();
    expect(app.find("GET", "/api/v1/staging/dashboard/general/clients/11111111-1")).toHaveLength(1);
    for (const title of ["IDs de cliente", "Suscripciones", "Cargos", "Transacciones"]) expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(screen.getByText("$10.000")).toBeTruthy();
    expect(screen.getByText("Sin registros relacionados.")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole("button", { name: "← Volver a clientes" }));
    expect(await screen.findByRole("button", { name: "11.111.111-1" })).toBeTruthy();
  });

  it("si falla la ficha muestra el error", async () => {
    mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", list],
      ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", failWith(500, "ficha rota")],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "11.111.111-1" }));
    expect(await screen.findByText("ficha rota")).toBeTruthy();
  });
});

// Cambio deliberado (UX-08): /central/suscripciones usa la vista unificada paginada en SQL (/api/v1/general/subscriptions)
// en vez de la lista consolidada en memoria. Se caracteriza la nueva vista.
const subscription = (n: number, over: Record<string, unknown> = {}) => ({
  channel: "virtualpos1", subscription_id: `S-${n}`, rut: `1111111${n}-1`, name: `Persona Sintética ${n}`, status: "ACTIVA",
  start_date: "2025-01-10", end_date: null, amount: "10000", currency: "CLP", last_charge: "2025-03-05T00:00:00", secondary_status: "cobrable", ...over,
});

describe("Suscripciones unificadas (/central/suscripciones)", () => {
  const list = {
    items: [subscription(1), subscription(2, { channel: "tch", subscription_id: "900", status: "", name: "", rut: "", amount: null, last_charge: null, secondary_status: "inactiva", end_date: "2025-02-01" })],
    total: 250, offset: 0, limit: 50, by_channel: { virtualpos: 200, tch: 50 }, canales: ["virtualpos1", "tch"],
  };
  const statuses: Handler = ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [{ status: "ACTIVA", count: 200 }], canales: ["virtualpos1", "tch"] }];

  it("pide la primera página y muestra título, columnas, filas y paginación", async () => {
    const app = mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", list], statuses]);
    await appReady();
    expect(await screen.findByRole("button", { name: "S-1" })).toBeTruthy();
    const call = app.exact("GET", "/api/v1/general/subscriptions")[0];
    expect(Object.fromEntries(call.query)).toEqual({ offset: "0", limit: "50" });
    expect(screen.getByRole("heading", { name: "Suscripciones", level: 1 })).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Canal", "ID", "Socio", "RUT", "Estado", "Estado secundario", "Último cobro", "Inicio", "Término", "Monto"]);
    expect(screen.getByText("CLP $10.000")).toBeTruthy();
    expect(screen.getByText("2025-03-05")).toBeTruthy();
    expect(screen.getByText("Cobrable").className).toContain("badge-green");
    expect(screen.getByText("Inactiva").className).toContain("badge-gray");
    expect(app.exact("GET", "/api/v1/staging/dashboard/general/subscriptions")).toHaveLength(0);
  });

  it("filtros de canal, estado y búsqueda y la paginación van a la API; el RUT abre Socios", async () => {
    const app = mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", list], statuses, ["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 100 }]]);
    await appReady();
    await screen.findByRole("button", { name: "S-1" });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/subscriptions").at(-1)?.query.get("offset")).toBe("50"));
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "tch" } });
    fireEvent.change(await screen.findByLabelText("Estado"), { target: { value: "ACTIVA" } });
    fireEvent.change(screen.getByLabelText("Buscar en"), { target: { value: "rut" } });
    fireEvent.change(screen.getByLabelText("Texto"), { target: { value: "1111" } });
    await waitFor(() => expect(Object.fromEntries(app.exact("GET", "/api/v1/general/subscriptions").at(-1)!.query)).toEqual({ canal: "tch", status: "ACTIVA", filter_field: "rut", query: "1111", offset: "0", limit: "50" }));
    fireEvent.click(screen.getByRole("button", { name: "Ver socio 11.111.111-1" }));
    await waitFor(() => expect(window.location.pathname).toBe("/central/clientes"));
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)?.query.get("filter_field")).toBe("rut"));
  });

  it("sin suscripciones muestra «Sin suscripciones.»", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", { ...list, items: [], total: 0 }], statuses]);
    await appReady();
    expect(await screen.findByText("Sin suscripciones.")).toBeTruthy();
  });

  it("si falla la lista muestra el error", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", failWith(500, "lista rota")], statuses]);
    await appReady();
    expect(await screen.findByText("lista rota")).toBeTruthy();
  });

  it("con solo dashboard.view (sin permiso de suscripciones de ningún canal) explica el motivo y no pide la lista", async () => {
    const app = mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", list], statuses], { permissions: ["dashboard.view"] });
    await appReady();
    expect(await screen.findByText(/no puede ver suscripciones de ningún canal/)).toBeTruthy();
    expect(app.exact("GET", "/api/v1/general/subscriptions")).toHaveLength(0);
  });
});
