/**
 * Caracterización del dashboard general de AppCore (UX-04): resumen, clientes y
 * suscripciones consolidados, panel ETL. Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, failWith, mountApp, navTop, resetApp, type Handler } from "./appHarness";

afterEach(resetApp);

const row = (status: string | null, month: number, count: number, amount: number, extra: Record<string, unknown> = {}) => ({ year: 2025, month, status, count, amount, ...extra });

const general = {
  clients: 1200,
  subscriptions: { active: 900, amount: 9000000 },
  transactions: { total: 500, accepted: 450, rejected: 50, amount: 4500000, rejection_rate_pct: 10, basis_label: null },
  channels: [
    { source: "VirtualPOS", clients: 800, active_subscriptions: 600, accepted: 300, amount: 3000000 },
    { source: "TCH", clients: 400, active_subscriptions: 300, accepted: 150, amount: 1500000 },
  ],
  years: [2024, 2025],
  transactions_monthly: [row("Aceptadas", 3, 90, 900000, { source: "VirtualPOS" }), row("Rechazadas", 3, 10, 100000, { source: "VirtualPOS" })],
  activations_monthly: [row("VirtualPOS", 3, 20, 200000)],
  cancellations_monthly: [row("VirtualPOS", 3, 5, 50000)],
  debts_monthly: [row("VirtualPOS", 3, 12, 120000, { charge_status: "pagada" }), row("VirtualPOS", 3, 3, 30000, { charge_status: "rechazada" })],
  transactions_effective_monthly: [row("VirtualPOS", 3, 40, 400000, { charge_status: "pagada" }), row("VirtualPOS", 3, 4, 40000, { charge_status: "rechazada" })],
  alerts: [],
  pending_payments: 82,
  sync_success_rate_pct: 98.5,
  churn_rate_pct: 2.1,
};

const staging = {
  sources: [
    { source: "virtualpos", records: 1000, resources: { client: 500, subscription: 300 }, last_sync: { status: "completed", records_processed: 1000, finished_at: "2025-03-31T10:00:00" } },
  ],
};

const summaryHandlers = (dashboard: unknown = general): Handler[] => [
  ["GET", "/api/v1/staging/summary", staging],
  ["GET", "/api/v1/staging/dashboard/general", dashboard],
];

describe("Dashboard general (/central/resumen)", () => {
  it("pide el resumen de staging y el dashboard general, y muestra cabecera, métricas, gráficos y tarjetas por canal", async () => {
    const app = mountApp("/central/resumen", summaryHandlers());
    await appReady();
    expect(await screen.findByLabelText("Métricas generales")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/summary")).toHaveLength(1);
    expect(app.exact("GET", "/api/v1/staging/dashboard/general")).toHaveLength(1);
    expect(screen.getByText("OPERACIONES RECURRENTES")).toBeTruthy();
    expect(screen.getByText("Staging local")).toBeTruthy();
    expect(screen.getByText("RESUMEN OPERATIVO")).toBeTruthy();
    const metrics = screen.getByLabelText("Métricas generales");
    expect(within(metrics).getByText("Clientes")).toBeTruthy();
    expect(within(metrics).getByText("1.200")).toBeTruthy();
    expect(within(metrics).getByText("Activaciones")).toBeTruthy();
    expect(within(metrics).getByText("Transacciones pagadas")).toBeTruthy();
    expect(within(metrics).getByText("90")).toBeTruthy();
    expect(screen.getByLabelText("KPIs generales")).toBeTruthy();
    for (const title of ["Recaudación mensual por canal", "Altas y bajas por mes", "Comparativa por canal", "Estado mensual consolidado", "Activaciones mensuales por canal", "Bajas mensuales por canal", "Deudas mensuales por canal", "Transacciones efectivas por canal"]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByText("600 suscripciones vigentes")).toBeTruthy();
    expect(screen.getByText("Carga staging")).toBeTruthy();
    expect(screen.getByText("1.000 registros")).toBeTruthy();
    expect(screen.getByText("Histórico TCH integrado")).toBeTruthy();
    expect(screen.getByText("Base de datos unificada")).toBeTruthy();
    expect(screen.getByRole("button", { name: "↻ Sync completo" })).toBeTruthy();
    expect((screen.getByLabelText("Año dashboard general") as HTMLSelectElement).value).toBe("2025");
    expect(contentHtml()).toMatchSnapshot();
  });

  it("antes de recibir datos muestra «Cargando indicadores consolidados...»", async () => {
    mountApp("/central/resumen", [["GET", "/api/v1/staging/dashboard/general", () => new Promise(() => {})], ["GET", "/api/v1/staging/summary", staging]]);
    await appReady();
    expect(await screen.findByText("Cargando indicadores consolidados...")).toBeTruthy();
    expect(screen.getByText("KPIs y actividad mensual calculados desde las entidades centralizadas y TCH.")).toBeTruthy();
  });

  it("muestra el error cuando falla el dashboard", async () => {
    mountApp("/central/resumen", [["GET", "/api/v1/staging/summary", staging], ["GET", "/api/v1/staging/dashboard/general", failWith(500, "falla simulada")]]);
    await appReady();
    expect(await screen.findByText("falla simulada")).toBeTruthy();
  });

  it("alterna cantidad/monto, cambia el año, filtra deudas y transacciones y abre el reporte", async () => {
    mountApp("/central/resumen", summaryHandlers());
    await appReady();
    const metrics = await screen.findByLabelText("Métricas generales");
    fireEvent.click(screen.getByRole("button", { name: "Monto" }));
    expect(metrics.querySelector(".metric-value-money")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Año dashboard general"), { target: { value: "2024" } });
    expect((screen.getByLabelText("Año dashboard general") as HTMLSelectElement).value).toBe("2024");
    const debts = screen.getByText("Deudas mensuales por canal").closest("article")!;
    fireEvent.click(within(debts).getByRole("button", { name: "Rechazada" }));
    expect(within(debts).getByRole("button", { name: "Rechazada" }).className).toBe("active");
    expect(within(debts).getByRole("button", { name: "Todas" }).className).toBe("");
    const trans = screen.getByText("Transacciones efectivas por canal").closest("article")!;
    fireEvent.click(within(trans).getByRole("button", { name: "Pagada" }));
    expect(within(trans).getByRole("button", { name: "Pagada" }).className).toBe("active");
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte" }));
    expect(screen.getByLabelText("Generar reporte")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "operación consolidada" })).toBeTruthy();
  });

  it("muestra el panel de alertas cuando el dashboard trae alertas", async () => {
    mountApp("/central/resumen", summaryHandlers({ ...general, alerts: [{ id: "a1", sev: "alta", tipo: "Rechazos", canal: "VirtualPOS", detalle: "Detalle sintético" }] }));
    await appReady();
    await screen.findByLabelText("Métricas generales");
    expect(screen.getByText("ALERTAS OPERATIVAS")).toBeTruthy();
  });

  it("conserva modo, año y filtros al ir a Clientes y volver al Dashboard desde el menú", async () => {
    mountApp("/central/resumen", [
      ...summaryHandlers(),
      ["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 100 }],
    ]);
    await appReady();
    await screen.findByLabelText("Métricas generales");
    fireEvent.click(screen.getByRole("button", { name: "Monto" }));
    fireEvent.change(screen.getByLabelText("Año dashboard general"), { target: { value: "2024" } });
    fireEvent.click(navTop("Clientes"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/clientes"));
    expect(await screen.findByText("CLIENTES CONSOLIDADOS")).toBeTruthy();
    fireEvent.click(navTop("Dashboard"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    const metrics = await screen.findByLabelText("Métricas generales");
    expect(metrics.querySelector(".metric-value-money")).toBeTruthy();
    expect((screen.getByLabelText("Año dashboard general") as HTMLSelectElement).value).toBe("2024");
  });

  it("Sync completo: envía los proveedores habilitados, muestra el progreso y el resultado de la corrida", async () => {
    const app = mountApp("/central/resumen", [
      ...summaryHandlers(),
      ["POST", "/api/v1/etl/full-sync", { run_id: "run-1" }],
      ["GET", "/api/v1/etl/runs/run-1", { id: "run-1", status: "completed", phase: null, started_at: "2025-03-31T10:00:00", finished_at: "2025-03-31T10:05:00", records_upserted: 1234, channels_processed: ["virtualpos"], error_message: null }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "↻ Sync completo" }));
    await waitFor(() => expect(app.find("POST", "/api/v1/etl/full-sync")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/etl/full-sync")[0].body).toEqual({ providers: ["virtualpos", "toku", "payku"] });
    const busy = screen.getByRole("button", { name: "Procesando…" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(await screen.findByText(/1\.234 registros/, undefined, { timeout: 6000 })).toBeTruthy();
    expect(document.querySelector(".etl-status .status-pill")?.textContent).toBe("completed");
    expect(screen.getByRole("button", { name: "↻ Sync completo" })).toBeTruthy();
    expect(app.find("GET", "/api/v1/etl/runs/run-1")).toHaveLength(1);
  }, 15000);

  it("Sync completo: si falla el inicio muestra el error y vuelve a habilitar el botón", async () => {
    mountApp("/central/resumen", [...summaryHandlers(), ["POST", "/api/v1/etl/full-sync", failWith(409, "ya hay una corrida")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "↻ Sync completo" }));
    expect(await screen.findByText("ya hay una corrida")).toBeTruthy();
    expect((screen.getByRole("button", { name: "↻ Sync completo" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

const client = (n: number) => ({ rut: `1111111${n}-1`, name: `Persona Sintética ${n}`, origins: ["VirtualPOS", "Toku"], active_origins: n === 1 ? ["VirtualPOS"] : [] });

describe("Clientes consolidados (/central/clientes)", () => {
  const list = { items: [client(1), client(2)], total: 250, offset: 0, limit: 100 };

  it("pide la primera página y muestra título, columnas, filas y paginación", async () => {
    const app = mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", list]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "11111111-1" })).toBeTruthy();
    const call = app.find("GET", "/api/v1/staging/dashboard/general/clients")[0];
    expect(call.query.get("limit")).toBe("100");
    expect(call.query.get("offset")).toBe("0");
    expect(call.query.get("filter_field")).toBe("all");
    expect(call.query.has("query")).toBe(false);
    // Rareza actual (sin corregir): en un enlace profundo, antes de aplicar la ruta la vista aún es
    // «summary», así que se pide una vez el dashboard general aunque no se muestre.
    expect(app.exact("GET", "/api/v1/staging/dashboard/general")).toHaveLength(1);
    expect(screen.getByText("CLIENTES CONSOLIDADOS")).toBeTruthy();
    expect(screen.getByText("250 clientes por RUT")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["RUT", "Nombre completo", "Plataforma de origen", "Suscripciones activas"]);
    expect(screen.getAllByText("VirtualPOS · Toku").length).toBe(2);
    expect(screen.getByText("1-2 de 250")).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("buscar, cambiar el campo y paginar piden la lista con los parámetros y reflejan campo y offset en la URL", async () => {
    const app = mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", list]]);
    await appReady();
    await screen.findByRole("button", { name: "11111111-1" });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/clients").at(-1)?.query.get("offset")).toBe("100"));
    expect(window.location.search).toBe("?offset=100");
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
    await screen.findByRole("button", { name: "11111111-1" });
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
    fireEvent.click(await screen.findByRole("button", { name: "11111111-1" }));
    expect(await screen.findByText("Ficha general: 11111111-1")).toBeTruthy();
    expect(app.find("GET", "/api/v1/staging/dashboard/general/clients/11111111-1")).toHaveLength(1);
    for (const title of ["IDs de cliente", "Suscripciones", "Cargos", "Transacciones"]) expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(screen.getByText("$10.000")).toBeTruthy();
    expect(screen.getByText("Sin registros relacionados.")).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole("button", { name: "← Volver a clientes" }));
    expect(await screen.findByRole("button", { name: "11111111-1" })).toBeTruthy();
  });

  it("si falla la ficha muestra el error", async () => {
    mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", list],
      ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", failWith(500, "ficha rota")],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "11111111-1" }));
    expect(await screen.findByText("ficha rota")).toBeTruthy();
  });
});

const subscription = (n: number, over: Record<string, unknown> = {}) => ({
  id: `S-${n}`, platform: "VirtualPOS", rut: `1111111${n}-1`, client: `Persona Sintética ${n}`, status: "ACTIVA",
  started_at: "2025-01-10", ended_at: null, amount: "10000", currency: "CLP", last_paid_date: "2025-03-05T00:00:00", secondary_status: "cobrable", ...over,
});

describe("Suscripciones consolidadas (/central/suscripciones)", () => {
  const list = { items: [subscription(1), subscription(2, { status: "", client: "", rut: "", amount: null, last_paid_date: null, secondary_status: "inactiva", ended_at: "2025-02-01" })], total: 250, offset: 0, limit: 100 };

  it("pide la primera página y muestra título, columnas, filas y paginación", async () => {
    const app = mountApp("/central/suscripciones", [["GET", "/api/v1/staging/dashboard/general/subscriptions", list]]);
    await appReady();
    expect(await screen.findByText("S-1")).toBeTruthy();
    const call = app.find("GET", "/api/v1/staging/dashboard/general/subscriptions")[0];
    expect(call.query.get("limit")).toBe("100");
    expect(call.query.get("offset")).toBe("0");
    expect(call.query.get("filter_field")).toBe("all");
    expect(screen.getByText("SUSCRIPCIONES CONSOLIDADAS")).toBeTruthy();
    expect(screen.getByText("250 suscripciones")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["ID", "Cliente", "RUT", "Plataforma", "Estado", "Estado secundario", "Último cobro", "Inicio", "Término", "Monto"]);
    expect(screen.getByText("CLP $10.000")).toBeTruthy();
    expect(screen.getByText("2025-03-05")).toBeTruthy();
    expect(screen.getByText("cobrable").className).toContain("badge-green");
    expect(screen.getByText("inactiva").className).toContain("badge-gray");
    expect(screen.getByText("1-2 de 250")).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("buscar, cambiar el campo y paginar piden la lista y reflejan campo y offset en la URL", async () => {
    const app = mountApp("/central/suscripciones", [["GET", "/api/v1/staging/dashboard/general/subscriptions", list]]);
    await appReady();
    await screen.findByText("S-1");
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/subscriptions").at(-1)?.query.get("offset")).toBe("100"));
    expect(window.location.search).toBe("?offset=100");
    fireEvent.change(screen.getByLabelText("Campo de búsqueda de suscripciones"), { target: { value: "status" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/subscriptions").at(-1)?.query.get("filter_field")).toBe("status"));
    expect(window.location.search).toBe("?campo=status");
    fireEvent.change(screen.getByLabelText("Buscar suscripción consolidada"), { target: { value: "ACTIVA" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/staging/dashboard/general/subscriptions").at(-1)?.query.get("query")).toBe("ACTIVA"));
  });

  it("sin suscripciones muestra «Sin suscripciones.»", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/staging/dashboard/general/subscriptions", { items: [], total: 0, offset: 0, limit: 100 }]]);
    await appReady();
    expect(await screen.findByText("Sin suscripciones.")).toBeTruthy();
  });

  it("si falla la lista muestra el error", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/staging/dashboard/general/subscriptions", failWith(500, "lista rota")]]);
    await appReady();
    expect(await screen.findByText("lista rota")).toBeTruthy();
  });
});
