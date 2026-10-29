/**
 * Caracterización de las listas de staging (VirtualPOS, Toku, Payku) y del dashboard de canal
 * de AppCore (UX-04). Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, listSettled, failWith, mountApp, resetApp, type Call, type Handler } from "./appHarness";
import { page, paykuClient, paykuSubscription, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPayment, vpPlan, vpSubscription } from "./fixtures";

afterEach(resetApp);

const recordsHandler = (body: unknown | ((q: URLSearchParams) => unknown)): Handler => ["GET", "/api/v1/staging/records", (call: Call) => (typeof body === "function" ? (body as (q: URLSearchParams) => unknown)(call.query) : body)];
const lastRecordsCall = (app: ReturnType<typeof mountApp>) => app.exact("GET", "/api/v1/staging/records").at(-1)!;
const headers = () => screen.getAllByRole("columnheader").map((th) => (th.textContent ?? "").replace(/[↕↑↓]$/, ""));

describe("Lista VirtualPOS: clientes (/virtualpos/clientes)", () => {
  const items = [vpClient(1), vpClient(2, { status: "BLOQUEADO", first_name: "", last_name: "" })];

  it("pide la lista (source, resource_type, offset, limit) y muestra columnas, filas, contador y botón de alta", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page(items))]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" })).toBeTruthy();
    const calls = app.exact("GET", "/api/v1/staging/records");
    expect(calls).toHaveLength(1);
    const q = calls[0].query;
    expect([q.get("source"), q.get("resource_type"), q.get("offset"), q.get("limit")]).toEqual(["virtualpos", "client", "0", "100"]);
    expect(q.has("filters")).toBe(false);
    expect(q.has("sort_field")).toBe(false);
    expect(screen.getByText("Volver al resumen VirtualPOS")).toBeTruthy();
    expect(screen.getByText("VIRTUALPOS / STAGING")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Clientes" })).toBeTruthy();
    expect(screen.getByText("Payloads saneados almacenados localmente")).toBeTruthy();
    expect(screen.getByText("2 registros")).toBeTruthy();
    expect(headers().slice(0, 7)).toEqual(["RUT", "Nombre", "Email", "Telefono", "Plataforma", "Estado", "Acciones"]);
    expect(screen.getByText("Persona1 Sintética")).toBeTruthy();
    expect(screen.getAllByText("VP 1").length).toBeGreaterThan(1);
    expect(screen.getAllByRole("button", { name: "Editar" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "+ Nuevo cliente" })).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("filtra por columna (debounce) con filters=campo:valor y reinicia el offset; «Limpiar filtros» los borra", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page(items))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    const clear = screen.getByRole("button", { name: "Limpiar filtros" }) as HTMLButtonElement;
    expect(clear.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Buscar por Email"), { target: { value: "p1@" } });
    await waitFor(() => expect(lastRecordsCall(app).query.getAll("filters")).toEqual(["email:p1@"]));
    expect((screen.getByRole("button", { name: "Limpiar filtros" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    await waitFor(() => expect(lastRecordsCall(app).query.has("filters")).toBe(false));
  });

  it("ordena por columna (sort_field/sort_direction) y refleja orden y dirección en la URL", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page(items))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    fireEvent.click(screen.getByTitle(/Ordenar por Nombre/));
    await waitFor(() => expect([lastRecordsCall(app).query.get("sort_field"), lastRecordsCall(app).query.get("sort_direction")]).toEqual(["name", "asc"]));
    expect(window.location.search).toBe("?orden=Nombre&direccion=asc");
    fireEvent.click(screen.getByTitle(/Ordenar por Nombre/));
    await waitFor(() => expect(lastRecordsCall(app).query.get("sort_direction")).toBe("desc"));
    expect(window.location.search).toBe("?orden=Nombre&direccion=desc");
  });

  it("los botones de cuenta cambian source a virtualpos1/virtualpos2 y lo reflejan en ?cuenta", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page(items))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    const filter = document.querySelector(".vp-platform-filter") as HTMLElement;
    expect(Array.from(filter.querySelectorAll(".vp-platform-btn")).map((b) => b.textContent)).toEqual(["Todas", "VP 1", "VP 2"]);
    fireEvent.click(within(filter).getByRole("button", { name: "VP 2" }));
    await waitFor(() => expect(lastRecordsCall(app).query.get("source")).toBe("virtualpos2"));
    expect(window.location.search).toBe("?cuenta=virtualpos2");
    fireEvent.click(within(filter).getByRole("button", { name: "Todas" }));
    await waitFor(() => expect(lastRecordsCall(app).query.get("source")).toBe("virtualpos"));
    expect(window.location.search).toBe("");
  });

  it("un enlace profundo con ?cuenta, ?orden y ?offset se aplica a la petición", async () => {
    const app = mountApp("/virtualpos/clientes?cuenta=virtualpos1&orden=Nombre&direccion=desc&offset=100", [recordsHandler(page(items, 150, 100))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    const q = lastRecordsCall(app).query;
    expect([q.get("source"), q.get("sort_field"), q.get("sort_direction"), q.get("offset")]).toEqual(["virtualpos1", "name", "desc", "100"]);
  });

  it("«Ver más» pide el siguiente offset y agrega los registros sin duplicar", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler((q: URLSearchParams) => (q.get("offset") === "0" ? page(items, 3) : page([items[1], vpClient(3)], 3, 100)))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    expect(screen.getByText("Mostrando 2 de 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ver más" }));
    await waitFor(() => expect(lastRecordsCall(app).query.get("offset")).toBe("100"));
    expect(await screen.findByRole("button", { name: "Ver ficha de cliente 11111113-1" })).toBeTruthy();
    expect(screen.getAllByRole("row").length).toBe(2 + 3);
    expect(screen.queryByText(/Mostrando/)).toBeNull();
  });

  it("sin registros muestra «Sin registros sincronizados para este recurso.»; si falla muestra el error", async () => {
    mountApp("/virtualpos/clientes", [recordsHandler(page([]))]);
    await appReady();
    expect(await screen.findByText("Sin registros sincronizados para este recurso.")).toBeTruthy();
    resetApp();
    mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", failWith(500, "lista rota")]]);
    await appReady();
    expect(await screen.findByText("lista rota")).toBeTruthy();
  });

  it("«Volver al resumen VirtualPOS» abre el dashboard del canal", async () => {
    const app = mountApp("/virtualpos/clientes", [recordsHandler(page(items)), ["GET", "/api/v1/staging/dashboard/virtualpos", channelDashboard("virtualpos")]]);
    await appReady();
    fireEvent.click(await screen.findByText("Volver al resumen VirtualPOS"));
    await waitFor(() => expect(window.location.pathname).toBe("/virtualpos/resumen"));
    expect(await screen.findByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/dashboard/virtualpos")).toHaveLength(1);
  });
});

describe("Listas VirtualPOS: planes, suscripciones, cargos y transacciones", () => {
  it("planes: columnas, botón «+ Nuevo plan» y enlace de nombre a la ficha", async () => {
    mountApp("/virtualpos/planes", [recordsHandler(page([vpPlan(1)]))]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Ver ficha de plan Plan Sintético 1" })).toBeTruthy();
    expect(headers().slice(0, 9)).toEqual(["Nombre", "Monto", "Subscripciones", "Activas", "Cobrables", "Renovacion", "Estado", "Activo en POS", "Plataforma"]);
    expect(screen.getByRole("button", { name: "+ Nuevo plan" })).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("suscripciones: columnas, acciones solo para activas, badge secundario y botón de alta", async () => {
    const list = [vpSubscription(1), vpSubscription(2, { status: "CANCELADA" }, { secondary_status: "inactiva" })];
    mountApp("/virtualpos/suscripciones", [recordsHandler(page(list))]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Ver ficha de subscripción 11111111-1" })).toBeTruthy();
    expect(headers().slice(0, 9)).toEqual(["RUT cliente", "Estado", "Estado sec.", "Monto", "F. Inicio", "F. Cancelacion", "Último cobro", "Plataforma", "Acciones"]);
    expect(screen.getAllByRole("button", { name: "Cancelar Sub" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "+ Cargo" })).toHaveLength(1);
    expect(screen.getByText("cobrable").className).toContain("badge-green");
    expect(screen.getByText("inactiva").className).toContain("badge-gray");
    expect(screen.getByRole("button", { name: "+ Nueva suscripción" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Monto mínimo"), { target: { value: "5000" } });
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("suscripciones: los filtros de monto y fecha usan amount_min/date_from", async () => {
    const app = mountApp("/virtualpos/suscripciones", [recordsHandler(page([vpSubscription(1)]))]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de subscripción 11111111-1" });
    fireEvent.change(screen.getByLabelText("Monto mínimo"), { target: { value: "5000" } });
    await waitFor(() => expect(lastRecordsCall(app).query.get("amount_min")).toBe("5000"));
    fireEvent.change(screen.getByLabelText("F. Inicio desde"), { target: { value: "2025-01-01" } });
    await waitFor(() => expect(lastRecordsCall(app).query.get("date_from")).toBe("2025-01-01"));
  });

  it("cargos: enlace de suscripción y acciones Cancelar (pendiente) / Reintentar (rechazado, con permiso)", async () => {
    const list = [vpCharge(1, "pendiente"), vpCharge(2, "rechazado"), vpCharge(3, "pagado")];
    mountApp("/virtualpos/cargos", [recordsHandler(page(list))]);
    await appReady();
    expect((await screen.findAllByRole("button", { name: "Ver ficha de subscripción sub-1" }))).toHaveLength(3);
    expect(headers().slice(0, 8)).toEqual(["ID subscripción", "Cliente", "RUT cliente", "Fecha de cargo", "Estado", "Monto", "Plataforma", "Acciones"]);
    expect(screen.getAllByRole("button", { name: "Cancelar" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Reintentar" })).toHaveLength(1);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("cargos: sin el permiso de reintento no se ofrece «Reintentar»", async () => {
    mountApp("/virtualpos/cargos", [recordsHandler(page([vpCharge(2, "rechazado")]))], { permissions: ["dashboard.view", "virtualpos.charges.view"] });
    await appReady();
    await screen.findAllByRole("button", { name: "Ver ficha de subscripción sub-1" });
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  it("transacciones: columnas y enlace de RUT a la ficha", async () => {
    mountApp("/virtualpos/transacciones", [recordsHandler(page([vpPayment(1)]))]);
    await appReady();
    expect(await screen.findByRole("button", { name: /Ver ficha de transacción/ })).toBeTruthy();
    expect(headers().slice(0, 7)).toEqual(["RUT cliente", "Cliente", "F. Pago", "Monto", "Estado", "Plataforma", "Acciones"]);
  });
});

describe("Listas Toku y Payku", () => {
  it("Toku clientes: controles de filtro (campo y búsqueda), petición con filter_field/query y «Restablecer»", async () => {
    const app = mountApp("/toku/clientes", [recordsHandler(page([tokuCustomer(1)]))]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Ver ficha de cliente 22222221-2" })).toBeTruthy();
    expect(screen.getByText("TOKU / STAGING")).toBeTruthy();
    expect(screen.getByText("Filtrar registros")).toBeTruthy();
    expect(headers()).toEqual(["RUT", "Nombre", "Mail", "Telefono", "Acciones"]);
    expect(lastRecordsCall(app).query.get("source")).toBe("toku");
    expect(lastRecordsCall(app).query.has("filter_field")).toBe(false);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    const reset = screen.getByRole("button", { name: "Restablecer" }) as HTMLButtonElement;
    expect(reset.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Campo"), { target: { value: "name" } });
    fireEvent.change(screen.getByPlaceholderText("Buscar por Nombre"), { target: { value: "Toku 1" } });
    await waitFor(() => {
      const q = lastRecordsCall(app).query;
      expect([q.get("filter_field"), q.get("query")]).toEqual(["name", "Toku 1"]);
    });
    fireEvent.click(screen.getByRole("button", { name: "Restablecer" }));
    await waitFor(() => expect(lastRecordsCall(app).query.has("query")).toBe(false));
  });

  it("Toku suscripciones: el filtro de estado pide los valores y filtra por status; ?filtro/?estado se aplican al abrir", async () => {
    const app = mountApp("/toku/suscripciones", [
      recordsHandler(page([tokuSubscription(1)])),
      ["GET", "/api/v1/staging/records/filter-values", { values: ["ACTIVE", "CANCELLED"] }],
    ]);
    await appReady();
    await screen.findByRole("button", { name: /Ver ficha de/ });
    fireEvent.change(screen.getByLabelText("Campo"), { target: { value: "status" } });
    expect(await screen.findByRole("option", { name: "CANCELLED" })).toBeTruthy();
    const valuesCall = app.exact("GET", "/api/v1/staging/records/filter-values").at(-1)!;
    expect([valuesCall.query.get("source"), valuesCall.query.get("resource_type"), valuesCall.query.get("filter_field")]).toEqual(["toku", "subscription", "status"]);
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "CANCELLED" } });
    await waitFor(() => {
      const q = lastRecordsCall(app).query;
      expect([q.get("filter_field"), q.get("query")]).toEqual(["status", "CANCELLED"]);
    });
    expect(window.location.search).toBe("?filtro=status&estado=CANCELLED");
  });

  it("Toku suscripciones: ?filtro=status&estado=X en la URL se aplica a la primera lista", async () => {
    const app = mountApp("/toku/suscripciones?filtro=status&estado=ACTIVE", [
      recordsHandler(page([tokuSubscription(1)])),
      ["GET", "/api/v1/staging/records/filter-values", { values: ["ACTIVE"] }],
    ]);
    await appReady();
    await screen.findByRole("button", { name: /Ver ficha de/ });
    await waitFor(() => {
      const q = lastRecordsCall(app).query;
      expect([q.get("filter_field"), q.get("query")]).toEqual(["status", "ACTIVE"]);
    });
  });

  it("Payku clientes y suscripciones: columnas y enlaces por ID", async () => {
    mountApp("/payku/clientes", [recordsHandler(page([paykuClient(1)]))]);
    await appReady();
    expect(await screen.findByRole("button", { name: /Ver ficha de Clientes pcl-1/ })).toBeTruthy();
    expect(screen.getByText("PAYKU / STAGING")).toBeTruthy();
    expect(headers()).toEqual(["ID", "RUT", "Nombre", "Email", "Telefono", "Acciones"]);
    resetApp();
    mountApp("/payku/suscripciones", [recordsHandler(page([paykuSubscription(1)]))]);
    await appReady();
    expect(await screen.findByRole("button", { name: /Ver ficha de Suscripciones psu-1/ })).toBeTruthy();
    expect(headers()).toEqual(["ID", "Estado", "Estado sec.", "Último cobro", "RUT", "F. Inicio", "F. Cancelacion", "Acciones"]);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });
});

function channelDashboard(source: string) {
  return {
    source, records: 1000, resources: { client: 500, plan: 5, subscription: 300, charge: 150, payment: 100 },
    resource_amounts: { charge: 1500000, payment: 1000000 },
    statuses: [{ resource: "subscription", status: "ACTIVA", count: 250 }, { resource: "subscription", status: "CANCELADA", count: 50 }],
    activity_resource: "payment", activity: [{ year: 2025, month: 3, count: 10, amount: 100000 }], years: [2024, 2025],
    last_sync: { status: "completed", records_processed: 1000, finished_at: "2025-03-31T10:00:00" },
    kpis: { mrr: 3000000, active_subscribers: 250, active_clients: 240, arpu: 12000, churn_rate: 2.5, ltv: 400000 },
    charges_monthly: [{ year: 2025, month: 3, status: "pagado", count: 90, amount: 900000 }],
    payments_monthly: [{ year: 2025, month: 3, status: "pagado", count: 80, amount: 800000 }],
    alerts: [],
  };
}

describe("Dashboard de canal (/virtualpos/resumen)", () => {
  it("pide dashboard/{canal} una vez y muestra el resumen operativo con los accesos a recursos", async () => {
    const app = mountApp("/virtualpos/resumen", [["GET", "/api/v1/staging/dashboard/virtualpos", channelDashboard("virtualpos")]]);
    await appReady();
    expect(await screen.findByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/dashboard/virtualpos")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS")).toBeTruthy();
    expect(screen.getByText("Sincronización completada")).toBeTruthy();
    expect(screen.getByLabelText("Explorar recursos")).toBeTruthy();
    expect((screen.getByLabelText("Año") as HTMLSelectElement).value).toBe("2025");
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("muestra «Cargando mini dashboard...» mientras llega", async () => {
    mountApp("/virtualpos/resumen", [["GET", "/api/v1/staging/dashboard/virtualpos", () => new Promise(() => {})]]);
    await appReady();
    expect(await screen.findByText("Cargando mini dashboard...")).toBeTruthy();
  });

  // Hallazgo 4 de UX-04 (corregido): antes el mensaje quedaba en `error`, que esta vista no pinta,
  // y la pantalla se quedaba en «Cargando mini dashboard...».
  it("si falla la carga muestra el error con «Reintentar» y, al reintentar, el dashboard", async () => {
    let calls = 0;
    const app = mountApp("/toku/resumen", [[
      "GET", "/api/v1/staging/dashboard/toku",
      () => (++calls === 1 ? failWith(500, "dashboard roto") : channelDashboard("toku")),
    ]]);
    await appReady();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("dashboard roto");
    expect(screen.queryByText("Cargando mini dashboard...")).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(app.exact("GET", "/api/v1/staging/dashboard/toku")).toHaveLength(2);
  });

  it("cambiar de modo y de año conserva la selección; abrir un recurso navega a su lista", async () => {
    const app = mountApp("/virtualpos/resumen", [
      ["GET", "/api/v1/staging/dashboard/virtualpos", channelDashboard("virtualpos")],
      recordsHandler(page([vpClient(1)])),
    ]);
    await appReady();
    await screen.findByText("Indicadores y actividad del período seleccionado.");
    fireEvent.click(screen.getByRole("button", { name: "Monto" }));
    expect(screen.getByRole("button", { name: "Monto" }).className).toBe("active");
    fireEvent.change(screen.getByLabelText("Año"), { target: { value: "2024" } });
    expect((screen.getByLabelText("Año") as HTMLSelectElement).value).toBe("2024");
    const quick = screen.getByLabelText("Explorar recursos");
    fireEvent.click(within(quick).getAllByRole("button")[0]);
    await waitFor(() => expect(window.location.pathname).toBe("/virtualpos/clientes"));
    await waitFor(() => expect(app.exact("GET", "/api/v1/staging/records").length).toBeGreaterThan(0));
  });

  it("«↻ Sincronizar» envía POST /staging/sync/{canal}, invalida la caché y vuelve a pedir el dashboard y lo muestra de nuevo (antes quedaba en «Cargando…»)", async () => {
    const app = mountApp("/virtualpos/resumen", [
      ["GET", "/api/v1/staging/dashboard/virtualpos", channelDashboard("virtualpos")],
      ["POST", "/api/v1/staging/sync/virtualpos", { status: "ok" }],
    ]);
    await appReady();
    await screen.findByText("Indicadores y actividad del período seleccionado.");
    fireEvent.click(screen.getByRole("button", { name: "↻ Sincronizar" }));
    await waitFor(() => expect(app.exact("POST", "/api/v1/staging/sync/virtualpos")).toHaveLength(1));
    await waitFor(() => expect(app.exact("GET", "/api/v1/staging/dashboard/virtualpos")).toHaveLength(2));
    // Hallazgo 2 de UX-04 (corregido): antes `channelLoading` quedaba en true y la vista no volvía.
    expect(await screen.findByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    expect(screen.queryByText("Cargando mini dashboard...")).toBeNull();
    expect(screen.getByRole("button", { name: "↻ Sincronizar" })).toBeTruthy();
  });

  it("«Generar reporte» abre el diálogo del canal", async () => {
    mountApp("/toku/resumen", [["GET", "/api/v1/staging/dashboard/toku", channelDashboard("toku")]]);
    await appReady();
    await screen.findByText("Indicadores y actividad del período seleccionado.");
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte" }));
    expect(screen.getByRole("heading", { name: "Toku" })).toBeTruthy();
  });
});
