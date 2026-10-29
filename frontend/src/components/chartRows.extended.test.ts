import { describe, expect, it } from "vitest";
import { buildCumulativeRows, filterByRange, pctOfTarget, type ChannelChartRow } from "./chartRows";

// Datos sintéticos: 3 meses de 2026 y 2 de fines de 2025.
const data: ChannelChartRow[] = [
  { year: 2025, month: 11, a: 10, b: 5 },
  { year: 2025, month: 12, a: 20, b: 5 },
  { year: 2026, month: 1, a: 30, b: 10 },
  { year: 2026, month: 2, a: 40, b: 10 },
  { year: 2026, month: 3, a: 50, b: 10 },
];

describe("pctOfTarget", () => {
  it("redondea al entero y devuelve null sin meta válida", () => {
    expect(pctOfTarget(82, 100)).toBe(82);
    expect(pctOfTarget(101.0, 123.9)).toBe(82);
    expect(pctOfTarget(150, 100)).toBe(150);
    expect(pctOfTarget(5, 0)).toBeNull();
    expect(pctOfTarget(5, null)).toBeNull();
    expect(pctOfTarget(NaN, 10)).toBeNull();
  });
});

describe("filterByRange", () => {
  it("«all» conserva todo ordenado", () => {
    expect(filterByRange([...data].reverse(), "all").map((r) => `${r.year}-${r.month}`)).toEqual(["2025-11", "2025-12", "2026-1", "2026-2", "2026-3"]);
  });
  it("«year» deja el año del último dato", () => {
    expect(filterByRange(data, "year").map((r) => r.month)).toEqual([1, 2, 3]);
  });
  it("«12m» toma los 12 meses terminados en el último dato (calendario, no cantidad de filas)", () => {
    const long: ChannelChartRow[] = [];
    for (let i = 0; i < 20; i++) long.push({ year: 2025 + Math.floor((i + 0) / 12), month: (i % 12) + 1, a: i });
    // 20 meses: ene-2025 .. ago-2026 -> últimos 12 = sep-2025 .. ago-2026
    const out = filterByRange(long, "12m");
    expect(out).toHaveLength(12);
    expect(out[0]).toMatchObject({ year: 2025, month: 9 });
    expect(out[11]).toMatchObject({ year: 2026, month: 8 });
  });
  it("«12m» con menos de 12 meses devuelve todo; vacío devuelve vacío", () => {
    expect(filterByRange(data, "12m")).toHaveLength(5);
    expect(filterByRange([], "12m")).toEqual([]);
  });
});

describe("buildCumulativeRows", () => {
  it("acumula real hasta el último mes con dato, con ritmo de meta y proyección por promedio", () => {
    const rows = buildCumulativeRows(data, ["a", "b"], { year: 2026, annualTarget: 1200 });
    expect(rows).toHaveLength(12);
    expect(rows.map((r) => r.real).slice(0, 4)).toEqual([40, 90, 150, null]);
    expect(rows[0].pace).toBe(100);
    expect(rows[11].pace).toBe(1200);
    // promedio = 150 / 3; la proyección arranca en el último real y sigue lineal
    expect(rows[2].projection).toBe(150);
    expect(rows[3].projection).toBeCloseTo(50 * 4, 5);
    expect(rows[11].projection).toBeCloseTo(50 * 12, 5);
    expect(rows[0].projection).toBeNull();
    expect(rows[1].projection).toBeNull();
  });
  it("sin meta anual no hay ritmo (null) pero sí real y proyección", () => {
    const rows = buildCumulativeRows(data, ["a"], { year: 2026, annualTarget: null });
    expect(rows.every((r) => r.pace === null)).toBe(true);
    expect(rows[2].real).toBe(120);
  });
  it("año sin datos devuelve lista vacía", () => {
    expect(buildCumulativeRows(data, ["a"], { year: 2030, annualTarget: 10 })).toEqual([]);
  });
  it("year null usa el último año con datos y etiqueta los meses", () => {
    const rows = buildCumulativeRows(data, ["a"], { year: null, annualTarget: null });
    expect(rows[0]).toMatchObject({ year: 2026, month: 1, label: "Ene" });
  });
  it("trata un mes sin fila como 0 pero no extiende «real» más allá del último dato", () => {
    const gap: ChannelChartRow[] = [{ year: 2026, month: 1, a: 10 }, { year: 2026, month: 3, a: 10 }];
    const rows = buildCumulativeRows(gap, ["a"], { year: 2026, annualTarget: null });
    expect(rows.map((r) => r.real).slice(0, 4)).toEqual([10, 10, 20, null]);
  });
});
