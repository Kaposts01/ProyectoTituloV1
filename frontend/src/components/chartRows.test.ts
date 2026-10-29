import { describe, expect, it } from "vitest";
import { fillMonths, pivotByStatus } from "./chartRows";

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
    expect(series.map((s) => s.color)).toEqual(["var(--status-rejected)", "var(--status-paid)"]);
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

  it("el color depende del estado, no de su posición alfabética", () => {
    const a = pivotByStatus([{ year: 2025, month: 1, status: "paid", count: 1 }]).series[0].color;
    const b = pivotByStatus([
      { year: 2025, month: 1, status: "aaa_otro", count: 1 },
      { year: 2025, month: 1, status: "PAGADO", count: 1 },
      { year: 2025, month: 1, status: "cancelled", count: 1 },
    ]).series;
    expect(b.find((s) => s.key === "PAGADO")?.color).toBe(a);
    expect(b.find((s) => s.key === "cancelled")?.color).toBe("var(--status-neutral)");
    expect(b.find((s) => s.key === "aaa_otro")?.color).toBe("var(--status-unknown)");
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
