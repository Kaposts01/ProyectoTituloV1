import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appReady, mountApp, resetApp, type Handler } from "./appHarness";
import { rawKpi, rawSummary } from "../features/summary/summaryFixtures";

beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-18T15:00:00Z")));
afterEach(() => { resetApp(); vi.restoreAllMocks(); });
const paykuPermissions = ["dashboard.view", "payku.dashboard.view", "general.charges.view"];
function singleSummary(channel: "payku" | "tch") {
  const data = rawSummary({ channels: [channel], is_current_month: false, generated_at: "2026-11-18T15:00:00Z" });
  const revenue = (data.kpis.ingreso_por_canal as Record<string, unknown>)[channel];
  data.kpis.ingreso_total = revenue;
  data.kpis.ingreso_por_canal = { [channel]: revenue };
  data.kpis.mrr = rawKpi(null, null, "clp", { por_canal: { [channel]: null } });
  data.kpis.arpu = rawKpi(null, null, "clp");
  data.series.ingreso_por_canal = (data.series.ingreso_por_canal as Array<{ month: string; canales: Record<string, number | null> }>).map((point) => ({ month: point.month, total: point.canales[channel], canales: { [channel]: point.canales[channel] } }));
  return data;
}
const payment = { channel: "payku", payment_id: "DEMO-PAY", charge_id: null, status: "paid", payment_date: "2026-10-10", amount: "7000", currency: "CLP", name: null, rut: null };
const payments = { items: [payment], total: 1, offset: 0, limit: 50, canales: ["payku"], by_channel: { payku: 1 } };
const paykuHandlers: Handler[] = [
  ["GET", "/api/v1/dashboard/general", singleSummary("payku")],
  ["GET", "/api/v1/general/payments", payments],
  ["GET", "/api/v1/general/payments/statuses", { statuses: [], canales: ["payku"] }],
];

describe("Dashboard: detalle con contexto", () => {
  it("prioriza cuatro KPIs, conserva los otros ocho y devuelve foco al cerrar detalle", async () => {
    mountApp("/central/resumen", paykuHandlers, { permissions: paykuPermissions });
    await appReady(); await screen.findByRole("region", { name: "Indicadores del mes" });
    expect(screen.getAllByRole("article")).toHaveLength(4);
    const button = screen.getByRole("button", { name: "Ver detalle de Ingreso total" });
    fireEvent.click(button);
    const heading = screen.getByRole("heading", { name: "Detalle de Ingreso total" });
    expect(heading).toHaveFocus();
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByText("Más indicadores (8)"));
    expect(screen.getAllByRole("article")).toHaveLength(12);
  });
  it("abre pagos Payku con el mismo canal/mes y vuelve a la selección del Dashboard", async () => {
    const app = mountApp("/central/resumen?mes=2026-10&canales=payku", paykuHandlers, { permissions: paykuPermissions });
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver detalle de Ingreso total" }));
    fireEvent.click(screen.getByRole("link", { name: "Consultar movimientos de Payku" }));
    await screen.findByText("DEMO-PAY");
    expect(screen.queryByRole("button", { name: "DEMO-PAY" })).toBeNull(); // Provider record access is separate.
    expect(screen.getByRole("tab", { name: "Pagos" })).toHaveAttribute("aria-selected", "true");
    expect(Object.fromEntries(app.exact("GET", "/api/v1/general/payments").at(-1)!.query)).toMatchObject({ canal: "payku", outcome: "paid", date_from: "2026-10-01", date_to: "2026-10-31" });
    expect(app.exact("GET", "/api/v1/general/charges")).toHaveLength(0);
    fireEvent.click(screen.getByRole("link", { name: "Volver al Dashboard" }));
    await screen.findByRole("region", { name: "Indicadores del mes" });
    await waitFor(() => expect(screen.getByLabelText("Mes")).toHaveValue("2026-10"));
    expect(within(await screen.findByRole("group", { name: "Canales" })).getByRole("checkbox", { name: "Payku" })).toBeChecked();
    expect(window.location.search).toContain("canales=payku");
  });
  it("las suscripciones relacionadas conservan canal/contexto sin fingir una base histórica", async () => {
    const app = mountApp("/central/resumen?mes=2026-10&canales=tch", [
      ["GET", "/api/v1/dashboard/general", singleSummary("tch")],
      ["GET", "/api/v1/general/subscriptions", { items: [], total: 0, offset: 0, limit: 50, canales: ["tch"], by_channel: {} }],
      ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [], canales: ["tch"] }],
    ], { permissions: ["dashboard.view", "tch.dashboard.view", "general.subscriptions.view"] });
    await appReady(); fireEvent.click(await screen.findByRole("button", { name: "Ver detalle de Socios totales" }));
    fireEvent.click(screen.getByRole("link", { name: "Consultar suscripciones actuales de TCH" }));
    await screen.findByRole("heading", { level: 1, name: "Suscripciones" });
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/subscriptions").length).toBeGreaterThan(0));
    const query = app.exact("GET", "/api/v1/general/subscriptions").at(-1)!.query;
    expect(query.get("canal")).toBe("tch"); expect(query.has("date_from")).toBe(false);
    expect(screen.getByRole("complementary", { name: "Origen del Dashboard" })).toHaveTextContent("no reconstruye la base histórica");
    expect(window.location.search).toContain("desde_dashboard=members");
  });
  it("sin permisos de listado muestra el indicador sin ofrecer accesos prohibidos", async () => {
    mountApp("/central/resumen", [["GET", "/api/v1/dashboard/general", singleSummary("payku")]], { permissions: ["dashboard.view", "payku.dashboard.view"] });
    await appReady(); fireEvent.click(await screen.findByRole("button", { name: "Ver detalle de Ingreso total" }));
    expect(screen.queryByRole("link", { name: /Consultar movimientos/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Revisar sincronización" })).toBeNull();
    expect(screen.getByText(/No hay accesos a listados habilitados/)).toBeTruthy();
  });
});
