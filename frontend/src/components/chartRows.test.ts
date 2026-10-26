import { describe, expect, it } from "vitest";
import { fillMonths, pivotByStatus, STATUS_PALETTE } from "./chartRows";

describe("pivotByStatus", () => {
  it("devuelve vacío sin datos", () => {
    expect(pivotByStatus([])).toEqual({ rows: [], series: [] });
  });

  it("pivota por estado con series ordenadas por nombre y colores estables", () => {
    const { rows, series } = pivotByStatus([
      { year: 2025, month: 2, status: "paid", count: 3 },
      { year: 2025, month: 1, status: "failed", count: 1 },
      { year: 2025, month: 1, status: "paid", count: 5 },
    ]);
    expect(series.map((s) => s.key)).toEqual(["failed", "paid"]);
    expect(series.map((s) => s.color)).toEqual([STATUS_PALETTE[0], STATUS_PALETTE[1]]);
    expect(rows).toEqual([
      { year: 2025, month: 1, failed: 1, paid: 5 },
      { year: 2025, month: 2, failed: 0, paid: 3 },
    ]);
  });

  it("maneja un solo mes, cruce de año, amount y estados desconocidos", () => {
    const one = pivotByStatus([{ year: 2025, month: 6, status: "paid", amount: 1000 }]);
    expect(one.rows).toEqual([{ year: 2025, month: 6, paid: 1000 }]);
    const cross = pivotByStatus([
      { year: 2026, month: 1, status: "zzz_nuevo", count: 2 },
      { year: 2025, month: 12, status: "paid", count: 1 },
    ]);
    expect(cross.rows.map((r) => `${r.year}-${r.month}`)).toEqual(["2025-12", "2026-1"]);
    expect(cross.series.map((s) => s.key)).toEqual(["paid", "zzz_nuevo"]);
  });

  it("reutiliza la paleta cuando hay más estados que colores", () => {
    const entries = Array.from({ length: STATUS_PALETTE.length + 1 }, (_, i) => ({ year: 2025, month: 1, status: `s${String(i).padStart(2, "0")}`, count: 1 }));
    const { series } = pivotByStatus(entries);
    expect(series[STATUS_PALETTE.length].color).toBe(STATUS_PALETTE[0]);
  });
});

describe("fillMonths", () => {
  it("devuelve vacío sin datos ni rango", () => {
    expect(fillMonths([])).toEqual([]);
  });

  it("rellena huecos con ceros cruzando año", () => {
    const out = fillMonths([{ year: 2025, month: 11, a: 2 }, { year: 2026, month: 2, a: 4 }]);
    expect(out.map((r) => `${r.year}-${r.month}:${r.a}`)).toEqual(["2025-11:2", "2025-12:0", "2026-1:0", "2026-2:4"]);
  });

  it("un solo mes se mantiene", () => {
    expect(fillMonths([{ year: 2025, month: 4, a: 1 }])).toEqual([{ year: 2025, month: 4, a: 1 }]);
  });

  it("respeta from y to extendiendo el rango", () => {
    const out = fillMonths([{ year: 2025, month: 3, a: 1 }], { year: 2025, month: 2 }, { year: 2025, month: 4 });
    expect(out.map((r) => r.a)).toEqual([0, 1, 0]);
  });
});
