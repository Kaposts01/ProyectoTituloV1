import { describe, expect, it } from "vitest";
import { adaptSummary } from "./summaryAdapter";
import { rawSummary } from "./summaryFixtures";
import { metricRecordLinks, observedMonthWindow } from "./dashboardLinks";
import { dashboardSelection, readDashboardContext, readPortfolioLocation } from "./dashboardContext";

const NOW = Date.parse("2026-10-16T01:30:00Z"); // Still October 15 in Chile.
describe("Detalle trazable del Dashboard", () => {
  it("acota el mes por días de Chile, distingue años bisiestos y no abre flujos futuros", () => {
    expect(observedMonthWindow("2026-10", NOW)).toEqual({ from: "2026-10-01", to: "2026-10-15" });
    expect(observedMonthWindow("2024-02", NOW)).toEqual({ from: "2024-02-01", to: "2024-02-29" });
    expect(observedMonthWindow("2025-02", NOW)?.to).toBe("2025-02-28");
    expect(observedMonthWindow("2026-11", NOW)).toBeNull();
    expect(observedMonthWindow("2026-13", NOW)).toBeNull();
  });
  it("abre pagos Payku, cargos VP y fechas observadas; TCH explica su diferencia de granularidad", () => {
    const summary = adaptSummary(rawSummary());
    const links = metricRecordLinks(summary, "revenue", () => true, NOW);
    const payku = new URL(links.find((l) => l.channel === "payku")!.href, "http://local");
    expect(Object.fromEntries(payku.searchParams)).toMatchObject({ canal: "payku", tab: "payments", outcome: "paid", date_from: "2026-10-01", date_to: "2026-10-15", mes: "2026-10" });
    const vp = new URL(links.find((l) => l.channel === "virtualpos")!.href, "http://local");
    expect(vp.searchParams.get("tab")).toBe("charges");
    expect(links.find((l) => l.channel === "tch")!.note).toMatch(/controles mensuales oficiales/);
  });
  it("en Toku no aplica un filtro genérico que excluiría las facturas impagas del no cobrado", () => {
    const links = metricRecordLinks(adaptSummary(rawSummary()), "uncollected", () => true, NOW);
    expect(new URL(links.find((l) => l.channel === "toku")!.href, "http://local").searchParams.has("outcome")).toBe(false);
    expect(new URL(links.find((l) => l.channel === "virtualpos")!.href, "http://local").searchParams.get("outcome")).toBe("rejected");
  });
  it("conserva la fecha de corte del cálculo aunque el listado se abra días después", () => {
    const links = metricRecordLinks(adaptSummary(rawSummary()), "revenue", () => true, Date.parse("2026-11-18T15:00:00Z"));
    expect(new URL(links[0].href, "http://local").searchParams.get("date_to")).toBe("2026-10-15");
  });
  it("respeta canal y permisos, y no representa stocks históricos con filtros de fecha de alta", () => {
    const summary = adaptSummary(rawSummary()); summary.channels = ["virtualpos", "tch"];
    expect(metricRecordLinks(summary, "revenue", () => false, NOW)).toEqual([]);
    const links = metricRecordLinks(summary, "members", (p) => p === "tch.suscripciones.view", NOW);
    expect(links).toHaveLength(1);
    expect(links[0].href).toContain("/central/suscripciones?");
    expect(links[0].href).not.toContain("date_from");
    expect(links[0].note).toContain("estado actual");
    expect(metricRecordLinks({ ...summary, month: "2026-11" }, "revenue", () => true, NOW)).toEqual([]);
  });
  it("valida contextos, no interpreta búsquedas personales y descarta fechas inválidas", () => {
    expect(readDashboardContext("?desde_dashboard=unknown&mes=2026-10&canales=tch")).toBeNull();
    expect(dashboardSelection("?mes=bad&canales=tch,unknown")).toEqual({ month: undefined, channels: undefined });
    const filters = readPortfolioLocation("?canal=payku&tab=payments&date_from=2026-02-31&outcome=unknown&query=PRIVATE&offset=-1");
    expect(filters).toMatchObject({ channel: "payku", tab: "payments", dateFrom: "", outcome: "", offset: 0 });
    expect(JSON.stringify(filters)).not.toContain("PRIVATE");
    expect(readPortfolioLocation("?date_from=2026-10-31&date_to=2026-10-01")).toMatchObject({ dateFrom: "", dateTo: "" });
  });
});
