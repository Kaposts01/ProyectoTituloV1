/**
 * Caracterización de las vistas TCH de AppCore (UX-04): textos, columnas y
 * peticiones tal como están hoy. Deben pasar igual antes y después de extraer
 * la vista a `features/tch`. Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, listSettled, failWith, mountApp, resetApp } from "./appHarness";

afterEach(resetApp);

const summary = {
  suscripciones: { vigentes: 40, eliminadas: 10, total: 50, monto_vigentes: 400000, monto_eliminadas: 100000, monto_total: 500000 },
  transacciones: { total: 200, aceptadas: 180, rechazadas: 20, tasa_rechazo_pct: 10, monto: 1800000 },
  kpis: { mrr: 400000, arpu: 10000, active_clients: 38, active_subscribers: 40, churn_rate: 2.5, ltv: 120000 },
  years: [2024, 2025],
  transacciones_mensuales: [{ year: 2025, month: 3, status: "Aceptadas", count: 90, amount: 900000 }, { year: 2025, month: 3, status: "Rechazadas", count: 10, amount: 100000 }],
  transacciones_fuente: "transacciones",
  activaciones_mensuales: [{ year: 2025, month: 3, status: null, count: 5, amount: 50000 }],
  bajas_mensuales: [{ year: 2025, month: 3, status: null, count: 2, amount: 20000 }],
  active_subs_monthly: [{ year: 2025, month: 3, count: 40 }],
  churn_rate_monthly: [{ year: 2025, month: 3, rate: 2.5 }],
  ultimo_etl: { id: "etl-1", status: "completed", started_at: "2025-03-31T10:00:00", records_upserted: 1234 },
  alerts: [],
};

const sub = (n: number, over: Record<string, unknown> = {}) => ({
  id: `sub-${n}`, numero_ficha: 1000 + n, numero_mandato: n, cliente_rut: `1111111${n}-1`, banco_nombre: "Banco Sintético",
  tipo_mandato: "FISICO", tipo_cuenta: "CORRIENTE", origen: "CALLE", centro_costo: "CC-1", captador: "Captador Uno",
  monto: "10000", equivalente_pesos: "10000", fecha_activacion: "2025-01-15", fecha_rechazo: null, fecha_eliminacion: null,
  fecha_fin: null, razon_baja: null, estado: "VIGENTE", last_paid_date: "2025-03-10T00:00:00", secondary_status: "cobrable",
  created_at: null, updated_at: null, ...over,
});
const trx = (n: number, over: Record<string, unknown> = {}) => ({
  id: `trx-${n}`, numero_ficha: 1000 + n, periodo: "2025-03", numero_cuota: "3", total_cuotas: "12", monto: "10000",
  fecha_cargo: "2025-03-05", tipo_transaccion: "COBRO", estado: "ACEPTADA", entidad_recaudadora: "Entidad Sintética",
  razon_rechazo: null, archivo_origen: null, ...over,
});
const cliente = (n: number) => ({
  id: `cli-${n}`, rut: `2222222${n}-2`, nombre: `Nombre${n}`, apellido: `Apellido${n}`, fecha_nacimiento: "1990-01-01",
  profesion: "Profesión Sintética", tipo_persona: "NATURAL", tipo_socio: "REGULAR", telefono: "000", email: `socio${n}@example.invalid`,
  direccion: "Calle 1", comuna: "Comuna Uno", ciudad: "Ciudad Uno",
});

describe("TCH: resumen (/tch/resumen)", () => {
  it("pide el resumen y muestra encabezado, KPIs, tarjetas, gráficos y accesos a las vistas", async () => {
    const app = mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", summary]]);
    await appReady();
    expect(await screen.findByText("TCH / CANAL")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Resumen operativo/ })).toBeTruthy();
    expect(screen.getByText("Datos cargados desde reportes Excel mensuales vía ETL.")).toBeTruthy();
    const metrics = screen.getByLabelText("KPIs TCH");
    for (const label of ["Suscripciones vigentes", "Suscripciones eliminadas", "Total suscripciones", "Total transacciones"]) {
      expect(within(metrics).getByText(label)).toBeTruthy();
    }
    expect(within(metrics).getByText("40")).toBeTruthy();
    expect(screen.getByLabelText("KPIs transacciones TCH")).toBeTruthy();
    for (const label of ["Aceptadas", "Rechazadas", "Tasa de rechazo"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getByText("Transacciones mensuales")).toBeTruthy();
    expect(screen.getByText("Altas vs bajas")).toBeTruthy();
    expect(screen.getByText("Crecimiento real mensual")).toBeTruthy();
    expect(screen.getByText("Churn mensual (%)")).toBeTruthy();
    expect(screen.getByText("Último ETL: 2025-03-31 · 1.234 registros")).toBeTruthy();
    expect(screen.getByText("Vistas disponibles")).toBeTruthy();
    expect((screen.getByLabelText("Año TCH") as HTMLSelectElement).value).toBe("2025");
    expect(app.find("GET", "/api/v1/tch/summary")).toHaveLength(1);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("alterna cantidad/monto, cambia el año y abre el diálogo de reporte", async () => {
    mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", summary]]);
    await appReady();
    await screen.findByText("TCH / CANAL");
    const metrics = screen.getByLabelText("KPIs TCH");
    expect(metrics.querySelector(".metric-value-money")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Monto" }));
    expect(metrics.querySelector(".metric-value-money")?.textContent).toBe("$400.000");
    fireEvent.click(screen.getByRole("button", { name: "Cantidad" }));
    expect(metrics.querySelector(".metric-value-money")).toBeNull();
    fireEvent.change(screen.getByLabelText("Año TCH"), { target: { value: "2024" } });
    expect((screen.getByLabelText("Año TCH") as HTMLSelectElement).value).toBe("2024");
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte" }));
    expect(screen.getByRole("heading", { name: "TCH" })).toBeTruthy();
    expect(screen.getByLabelText("Generar reporte")).toBeTruthy();
  });

  it("muestra el error de carga y el estado de carga", async () => {
    mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", failWith(500, "falla simulada")]]);
    await appReady();
    expect(await screen.findByText("falla simulada")).toBeTruthy();
  });

  it("el botón Suscripciones navega a /tch/suscripciones y pide la lista", async () => {
    const app = mountApp("/tch/resumen", [
      ["GET", "/api/v1/tch/summary", summary],
      ["GET", "/api/v1/tch/suscripciones", { total: 0, page: 1, limit: 50, pages: 1, items: [] }],
    ]);
    await appReady();
    await screen.findByText("Vistas disponibles");
    fireEvent.click(screen.getByRole("button", { name: /^Suscripciones50$/ }));
    await waitFor(() => expect(window.location.pathname).toBe("/tch/suscripciones"));
    await screen.findByText("Suscripciones TCH");
    expect(app.find("GET", "/api/v1/tch/suscripciones")).toHaveLength(1);
  });
});

describe("TCH: suscripciones (/tch/suscripciones)", () => {
  const list = { total: 120, page: 1, limit: 50, pages: 3, items: [sub(1), sub(2, { estado: "ELIMINADA", secondary_status: "inactiva", last_paid_date: null, equivalente_pesos: null, monto: null })] };

  it("pide la página 1 con límite 50 y muestra columnas y filas", async () => {
    const app = mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", list]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "1001" })).toBeTruthy();
    expect(screen.getByText("Suscripciones TCH")).toBeTruthy();
    expect(screen.getByText("Mandatos activos e históricos de débito físico.")).toBeTruthy();
    const call = app.find("GET", "/api/v1/tch/suscripciones")[0];
    expect(call.query.get("limit")).toBe("50");
    expect(call.query.get("page")).toBe("1");
    expect(call.query.has("estado")).toBe(false);
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["Ficha", "RUT cliente", "Banco", "Tipo mandato", "Origen", "Centro costo", "Monto", "F. Activación", "Estado", "Estado sec.", "Último cobro"]);
    expect(screen.getByRole("button", { name: "1001" })).toBeTruthy();
    expect(screen.getByText("$10.000")).toBeTruthy();
    expect(screen.getByText("2025-03-10")).toBeTruthy();
    expect(screen.getByText("ELIMINADA").className).toContain("status-attention");
    expect(screen.getByText("1 / 3 (120 total)")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("filtra por estado y vuelve a la página 1; la paginación pide la página siguiente", async () => {
    const app = mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", list]]);
    await appReady();
    await screen.findByRole("button", { name: "1001" });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.find("GET", "/api/v1/tch/suscripciones").at(-1)?.query.get("page")).toBe("2"));
    fireEvent.change(screen.getByLabelText("Filtrar por estado"), { target: { value: "VIGENTE" } });
    await waitFor(() => {
      const last = app.find("GET", "/api/v1/tch/suscripciones").at(-1)!;
      expect(last.query.get("estado")).toBe("VIGENTE");
      expect(last.query.get("page")).toBe("1");
    });
  });

  it("sin resultados muestra «Sin registros.»", async () => {
    mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", { total: 0, page: 1, limit: 50, pages: 1, items: [] }]]);
    await appReady();
    expect(await screen.findByText("Sin registros.")).toBeTruthy();
  });

  // Hallazgo 1 de UX-04 (corregido): antes, el detalle provisional `{ numero_ficha }` no traía
  // `transacciones` y el JSX hacía `.map` sobre `undefined`: la ficha lanzaba TypeError y no se podía abrir.
  it("la ficha de una suscripción se abre, pide /tch/suscripciones/{ficha} y muestra mandato y cargos (antes: TypeError)", async () => {
    const detail = { ...sub(1), transacciones: [trx(1), trx(2, { estado: "RECHAZADA", periodo: "2025-04" })] };
    const app = mountApp("/tch/suscripciones", [
      ["GET", "/api/v1/tch/suscripciones", list],
      ["GET", "/api/v1/tch/suscripciones/1001", detail],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "1001" }));
    expect(window.location.pathname).toBe("/tch/suscripciones/1001");
    expect(await screen.findByText("TCH / SUSCRIPCIÓN")).toBeTruthy();
    expect(await screen.findByText("Ficha 1001")).toBeTruthy();
    expect(screen.getByText("Mandato físico e historial de cargos.")).toBeTruthy();
    expect(screen.getByText("Historial")).toBeTruthy();
    expect(screen.getByRole("button", { name: "2025-03" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "2025-04" })).toBeTruthy();
    expect(screen.getByText("RECHAZADA").className).toContain("status-attention");
    expect(app.find("GET", "/api/v1/tch/suscripciones/1001").length).toBeGreaterThan(0);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole("button", { name: "← Suscripciones TCH" }));
    expect(await screen.findByText("Mandatos activos e históricos de débito físico.")).toBeTruthy();
  });

  it("la ficha de una suscripción no falla si la respuesta no trae cargos", async () => {
    mountApp("/tch/suscripciones/1001", [["GET", "/api/v1/tch/suscripciones/1001", sub(1)]]);
    await appReady();
    expect(await screen.findByText("Ficha 1001")).toBeTruthy();
    expect(screen.getByText("Historial")).toBeTruthy();
  });

  it("si falla la carga de la ficha de suscripción muestra el error", async () => {
    mountApp("/tch/suscripciones/1001", [["GET", "/api/v1/tch/suscripciones/1001", failWith(500, "ficha rota")]]);
    await appReady();
    expect(await screen.findByText("ficha rota")).toBeTruthy();
  });
});

describe("TCH: transacciones (/tch/transacciones)", () => {
  const list = { total: 2, page: 1, limit: 100, pages: 1, items: [trx(1), trx(2, { estado: "RECHAZADA", numero_cuota: "4", total_cuotas: null, monto: null, periodo: null })] };

  it("pide límite 100, muestra columnas y filas y filtra por período", async () => {
    const app = mountApp("/tch/transacciones", [["GET", "/api/v1/tch/transacciones", list]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "1001" })).toBeTruthy();
    expect(screen.getByText("Transacciones TCH")).toBeTruthy();
    expect(screen.getByText("Historial de cargos aceptados y rechazados.")).toBeTruthy();
    expect(app.find("GET", "/api/v1/tch/transacciones")[0].query.get("limit")).toBe("100");
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Ficha", "Período", "Entidad", "Monto", "Fecha cargo", "Cuota", "Estado"]);
    expect(screen.getByText("3/12")).toBeTruthy();
    expect(screen.getByText("RECHAZADA").className).toContain("status-attention");
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.change(screen.getByLabelText("Filtrar por período"), { target: { value: "2025-03" } });
    await waitFor(() => expect(app.find("GET", "/api/v1/tch/transacciones").at(-1)?.query.get("periodo")).toBe("2025-03"));
  });

  it("la ficha de un cargo pide /tch/transacciones/{id} y muestra su detalle sin cambiar la URL", async () => {
    const detail = { ...trx(1), suscripcion: sub(1) };
    const app = mountApp("/tch/transacciones", [
      ["GET", "/api/v1/tch/transacciones", list],
      ["GET", "/api/v1/tch/transacciones/trx-1", detail],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "1001" }));
    expect(await screen.findByText("TCH / TRANSACCIÓN")).toBeTruthy();
    expect(await screen.findByText("Cargo 2025-03")).toBeTruthy();
    expect(screen.getByText("Detalle del cargo")).toBeTruthy();
    expect(screen.getByText("Entidad Sintética")).toBeTruthy();
    expect(window.location.pathname).toBe("/tch/transacciones");
    expect(app.find("GET", "/api/v1/tch/transacciones/trx-1").length).toBeGreaterThan(0);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole("button", { name: "← Transacciones TCH" }));
    expect(await screen.findByText("Transacciones TCH")).toBeTruthy();
  });
});

describe("TCH: clientes (/tch/clientes)", () => {
  const list = { total: 120, page: 1, limit: 50, pages: 3, items: [cliente(1), { ...cliente(2), nombre: null, apellido: null, profesion: null }] };

  it("pide la lista, muestra columnas y filas y busca por nombre volviendo a la página 1", async () => {
    const app = mountApp("/tch/clientes", [["GET", "/api/v1/tch/clientes", list]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "22222221-2" })).toBeTruthy();
    expect(screen.getByText("Clientes TCH")).toBeTruthy();
    expect(screen.getByText("Socios asociados a mandatos físicos.")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["RUT", "Nombre", "Fecha nacimiento", "Profesión", "Tipo socio"]);
    expect(screen.getByText("Nombre1 Apellido1")).toBeTruthy();
    expect(screen.getByText("1 / 3 (120 total)")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.find("GET", "/api/v1/tch/clientes").at(-1)?.query.get("page")).toBe("2"));
    fireEvent.change(screen.getByLabelText("Buscar cliente"), { target: { value: "Nombre1" } });
    await waitFor(() => {
      const last = app.find("GET", "/api/v1/tch/clientes").at(-1)!;
      expect(last.query.get("nombre")).toBe("Nombre1");
      expect(last.query.get("page")).toBe("1");
    });
  });

  it("la ficha del cliente pide /tch/clientes/{rut} y lista sus mandatos", async () => {
    const detail = { ...cliente(1), suscripciones: [sub(1)] };
    const app = mountApp("/tch/clientes", [
      ["GET", "/api/v1/tch/clientes", list],
      ["GET", /^\/api\/v1\/tch\/clientes\/[^/]+$/, detail],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "22222221-2" }));
    expect(await screen.findByText("TCH / CLIENTE")).toBeTruthy();
    expect(await screen.findByText("Datos personales")).toBeTruthy();
    expect(screen.getByText("Mandatos asociados")).toBeTruthy();
    expect(screen.getByText("Suscripciones TCH asociadas")).toBeTruthy();
    expect(app.find("GET", "/api/v1/tch/clientes/22222221-2").length).toBeGreaterThan(0);
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
  });
});
