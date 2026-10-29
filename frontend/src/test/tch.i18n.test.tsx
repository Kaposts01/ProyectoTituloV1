/**
 * Paso 8 de la traducción: los valores propios de TCH (estado de suscripción y de transacción, estado
 * secundario, estado del último ETL) se ven en español, no en mayúsculas del Excel ni en inglés. Datos sintéticos.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appReady, mountApp, resetApp } from "./appHarness";
import { resetUnknownWarnings } from "../i18n/label";

afterEach(resetApp);
beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

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
const summary = (etlStatus: string | null) => ({
  suscripciones: { vigentes: 40, eliminadas: 10, total: 50, monto_vigentes: 400000, monto_eliminadas: 100000, monto_total: 500000 },
  transacciones: { total: 200, aceptadas: 180, rechazadas: 20, tasa_rechazo_pct: 10, monto: 1800000 },
  kpis: { mrr: 400000, arpu: 10000, active_clients: 38, active_subscribers: 40, churn_rate: 2.5, ltv: 120000 },
  years: [2025], transacciones_mensuales: [], activaciones_mensuales: [], bajas_mensuales: [], active_subs_monthly: [], churn_rate_monthly: [],
  ultimo_etl: { id: "etl-1", status: etlStatus, started_at: "2025-03-31T10:00:00", records_upserted: 10 }, alerts: [],
});
const page = (items: unknown[]) => ({ total: items.length, page: 1, limit: 50, pages: 1, items });

describe("TCH: valores en español", () => {
  it("lista de suscripciones: estado y estado secundario traducidos", async () => {
    mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", page([sub(1), sub(2, { estado: "ELIMINADA", secondary_status: "inactiva" }), sub(3, { secondary_status: "nunca_cobrado" })])]]);
    await appReady();
    await screen.findByRole("button", { name: "1001" });
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Vigente")).toBeTruthy();
    expect(within(rows[0]).getByText("Cobrable")).toBeTruthy();
    expect(within(rows[1]).getByText("Eliminada")).toBeTruthy();
    expect(within(rows[1]).getByText("Inactiva")).toBeTruthy();
    expect(within(rows[2]).getByText("Nunca cobrado")).toBeTruthy();
    expect(screen.queryByText("VIGENTE")).toBeNull();
    expect(screen.queryByText("cobrable")).toBeNull();
  });

  it("lista de transacciones: estado traducido", async () => {
    mountApp("/tch/transacciones", [["GET", "/api/v1/tch/transacciones", page([trx(1), trx(2, { estado: "RECHAZADA" })])]]);
    await appReady();
    await screen.findAllByRole("button", { name: /^100[12]$/ });
    expect(screen.getByText("Aceptada")).toBeTruthy();
    expect(screen.getByText("Rechazada")).toBeTruthy();
    expect(screen.queryByText("ACEPTADA")).toBeNull();
  });

  it("ficha de suscripción y de transacción: estado en el encabezado y en el historial", async () => {
    mountApp("/tch/suscripciones/1001", [["GET", "/api/v1/tch/suscripciones/1001", { ...sub(1), transacciones: [trx(1)] }]]);
    await appReady();
    expect(await screen.findByText("Ficha 1001")).toBeTruthy();
    // El encabezado puede aparecer antes que los datos del mandato: se espera el estado traducido.
    expect(await screen.findByText("Vigente")).toBeTruthy();
    expect(screen.getAllByText("Vigente").length).toBe(1);
    expect(screen.getAllByText("Aceptada").length).toBe(1);
    expect(screen.getByText("Cobrable")).toBeTruthy();
  });

  it("un estado de TCH que el catálogo no conoce se ve «Desconocido (X)»", async () => {
    mountApp("/tch/suscripciones", [["GET", "/api/v1/tch/suscripciones", page([sub(1, { estado: "ZZ_NUEVO", secondary_status: "ZZ_SEC" })])]]);
    await appReady();
    await screen.findByRole("button", { name: "1001" });
    expect(screen.getByText("Desconocido (ZZ_NUEVO)")).toBeTruthy();
    expect(screen.getByText("Desconocido (ZZ_SEC)")).toBeTruthy();
  });

  it("resumen: estado del último ETL en español y «Sin ETL» si falta", async () => {
    mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", summary("completed")]]);
    await appReady();
    expect(await screen.findByText("Completada")).toBeTruthy();
    expect(screen.queryByText("completed")).toBeNull();
    resetApp();
    mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", summary("failed")]]);
    await appReady();
    expect(await screen.findByText("Fallida")).toBeTruthy();
    resetApp();
    mountApp("/tch/resumen", [["GET", "/api/v1/tch/summary", summary(null)]]);
    await appReady();
    expect(await screen.findByText("Sin ETL")).toBeTruthy();
  });
});
