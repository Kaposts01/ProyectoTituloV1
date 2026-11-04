import { describe, expect, it } from "vitest";
import { adaptSummary } from "./summaryAdapter";
import { churnHistory, flowRows, membersRows, netGrowthHistory, parseMonth, revenueRows, sparkValues } from "./summaryChartData";
import { formatDataDate, monthLabel, shiftMonth } from "./summaryFormat";
import { rawSingleChannel, rawSummary } from "./summaryFixtures";

const summary = adaptSummary(rawSummary());

describe("parseMonth / shiftMonth / monthLabel", () => {
  it("lee YYYY-MM y rechaza lo demás", () => {
    expect(parseMonth("2026-10")).toEqual({ year: 2026, month: 10 });
    expect(parseMonth("2026-13")).toBeNull();
    expect(parseMonth("")).toBeNull();
    expect(parseMonth("26-1")).toBeNull();
  });
  it("shiftMonth cruza el cambio de año", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-10", -1)).toBe("2026-09");
  });
  it("monthLabel escribe el mes en español", () => {
    expect(monthLabel("2026-10")).toBe("octubre de 2026");
    expect(monthLabel("malo")).toBe("malo");
  });
  it("formatDataDate da la fecha en hora de Chile o null", () => {
    expect(formatDataDate("2026-10-15T12:00:00-03:00")).toBe("15-10-2026");
    expect(formatDataDate(null)).toBeNull();
    expect(formatDataDate("no es fecha")).toBeNull();
  });
});

describe("filas de gráfico desde las series del endpoint", () => {
  it("ingreso por canal: una columna por canal efectivo; el null se omite (sin dato, no 0)", () => {
    const rows = revenueRows(summary.series, summary.channels);
    expect(rows).toHaveLength(12);
    expect(rows[0]).toEqual({ year: 2025, month: 11, virtualpos: 10000, toku: 10000, tch: 20000 });
    expect("payku" in rows[0]).toBe(false);
    expect(rows[11]).toMatchObject({ year: 2026, month: 10, payku: 5000 });
  });

  it("un canal sin permiso no tiene columna", () => {
    const only = adaptSummary(rawSingleChannel("toku"));
    const rows = revenueRows(only.series, only.channels);
    expect(Object.keys(rows[0]).sort()).toEqual(["month", "toku", "year"]);
  });

  it("socios totales: una fila por mes con la clave members", () => {
    const rows = membersRows(summary.series);
    expect(rows[0]).toEqual({ year: 2025, month: 11, members: 5 });
    expect(rows).toHaveLength(12);
  });

  it("activaciones, bajas y crecimiento neto (activaciones - bajas)", () => {
    const rows = flowRows(summary.series);
    expect(rows[0]).toEqual({ year: 2025, month: 11, activations: 1, cancellations: 0, net: 1 });
    expect(rows[1]).toEqual({ year: 2025, month: 12, activations: 2, cancellations: 1, net: 1 });
  });

  it("si falta activaciones o bajas del mes, el neto queda sin dato", () => {
    const raw = rawSummary();
    (raw.series.bajas as Array<{ month: string; valor: number | null }>)[0].valor = null;
    const rows = flowRows(adaptSummary(raw).series);
    expect(rows[0]).toEqual({ year: 2025, month: 11, activations: 1 });
  });

  it("un mes con formato inválido se descarta", () => {
    const raw = rawSummary();
    (raw.series.socios_totales as Array<{ month: string; valor: number | null }>)[0].month = "xx";
    expect(membersRows(adaptSummary(raw).series)).toHaveLength(11);
  });
});

describe("historias para las miniaturas (sparkline)", () => {
  it("sparkValues descarta los null", () => {
    expect(sparkValues([{ month: "2026-01", value: 1 }, { month: "2026-02", value: null }, { month: "2026-03", value: 3 }])).toEqual([1, 3]);
  });
  it("netGrowthHistory = activaciones - bajas por mes", () => {
    expect(netGrowthHistory(summary.series).slice(0, 2)).toEqual([1, 1]);
  });
  it("churnHistory = bajas del mes / socios del mes anterior x 100, sin inventar meses sin base", () => {
    const history = churnHistory(summary.series);
    // Nov-25 no tiene mes anterior; Dic-25: bajas 1 / socios nov 5 = 20 %
    expect(history).toHaveLength(11);
    expect(history[0]).toBe(20);
  });
  it("churnHistory omite los meses con socios previos nulos o cero", () => {
    const raw = rawSummary();
    (raw.series.socios_totales as Array<{ month: string; valor: number | null }>)[0].valor = 0;
    (raw.series.socios_totales as Array<{ month: string; valor: number | null }>)[1].valor = null;
    expect(churnHistory(adaptSummary(raw).series)).toHaveLength(9);
  });
});
