import { describe, expect, it } from "vitest";
import {
  activationVsChurnChart, activeSubsLineChart, coverageGapAnnotations, monthlyTrendChart,
  paymentMethodSnapshot, statusStackedChart, tchSourceNote, tokuCollectionsChart,
} from "./channelCharts";

describe("statusStackedChart", () => {
  it("vacío", () => {
    expect(statusStackedChart([], "count")).toEqual({ rows: [], series: [] });
    expect(statusStackedChart(undefined, "count").rows).toEqual([]);
  });
  it("un solo mes y estado nulo", () => {
    const r = statusStackedChart([{ year: 2025, month: 3, status: null, count: 4, amount: 400 }], "amount");
    expect(r.rows).toEqual([{ year: 2025, month: 3, "Sin estado": 400 }]);
    expect(r.series.map((s) => s.key)).toEqual(["Sin estado"]);
  });
  it("cruce de año rellena meses y estados desconocidos tienen color", () => {
    const r = statusStackedChart([
      { year: 2024, month: 12, status: "pagado", count: 2, amount: 0 },
      { year: 2025, month: 2, status: "zzz_nuevo", count: 5, amount: 0 },
    ], "count");
    expect(r.rows.map((x) => [x.year, x.month])).toEqual([[2024, 12], [2025, 1], [2025, 2]]);
    expect(r.rows[1]).toMatchObject({ pagado: 0, zzz_nuevo: 0 });
    expect(r.series.every((s) => !!s.color)).toBe(true);
  });
});

describe("activeSubsLineChart", () => {
  it("vacío", () => expect(activeSubsLineChart(null).rows).toEqual([]));
  it("arrastra el valor en meses sin movimiento y cruza año", () => {
    const r = activeSubsLineChart([{ year: 2025, month: 1, count: 10 }, { year: 2024, month: 11, count: 7 }]);
    expect(r.rows.map((x) => x.count)).toEqual([7, 7, 10]);
    expect(r.rows[1]).toMatchObject({ year: 2024, month: 12 });
  });
  it("un solo mes", () => expect(activeSubsLineChart([{ year: 2025, month: 5, count: 3 }]).rows).toHaveLength(1));
});

describe("activationVsChurnChart", () => {
  it("vacío", () => expect(activationVsChurnChart([], [], "count").rows).toEqual([]));
  it("suma estados y une meses de ambas series", () => {
    const r = activationVsChurnChart(
      [{ year: 2025, month: 1, count: 2, amount: 20 }, { year: 2025, month: 1, count: 3, amount: 30 }],
      [{ year: 2025, month: 2, count: 1, amount: 10 }],
      "count",
    );
    expect(r.rows).toEqual([{ year: 2025, month: 1, altas: 5, bajas: 0 }, { year: 2025, month: 2, altas: 0, bajas: 1 }]);
    expect(r.series.map((s) => s.key)).toEqual(["altas", "bajas"]);
  });
  it("modo monto", () => {
    expect(activationVsChurnChart([{ year: 2025, month: 1, count: 2, amount: 20 }], [], "amount").rows[0].altas).toBe(20);
  });
});

describe("tendencia Toku", () => {
  it("vacío y un mes", () => {
    expect(tokuCollectionsChart([], "count").rows).toEqual([]);
    const r = tokuCollectionsChart([{ year: 2025, month: 1, count: 3, amount: 99 }], "amount");
    expect(r.rows).toEqual([{ year: 2025, month: 1, amount: 99 }]);
    expect(r.series[0]).toMatchObject({ key: "amount", label: "Monto cobrado" });
  });
  it("monthlyTrendChart rellena hueco", () => {
    const r = monthlyTrendChart([{ year: 2024, month: 12, count: 1 }, { year: 2025, month: 2, count: 2 }], "count", "x");
    expect(r.rows.map((x) => x.count)).toEqual([1, 0, 2]);
  });
});

describe("paymentMethodSnapshot", () => {
  it("filtra solo payment_method", () => {
    expect(paymentMethodSnapshot([{ resource: "payment_method", status: "chargeable", count: 3 }, { resource: "invoice", status: "PAID", count: 9 }]))
      .toEqual([{ resource: "payment_method", status: "chargeable", count: 3 }]);
    expect(paymentMethodSnapshot(undefined)).toEqual([]);
  });
});

describe("coverageGapAnnotations", () => {
  it("vacío", () => expect(coverageGapAnnotations([])).toEqual([]));
  it("agrupa consecutivos, cruza año y separa bandas", () => {
    const r = coverageGapAnnotations([
      { year: 2025, month: 1 }, { year: 2024, month: 11 }, { year: 2024, month: 12 }, { year: 2025, month: 4 }, { year: 2025, month: 4 },
    ]);
    expect(r).toEqual([
      { from: { year: 2024, month: 11 }, to: { year: 2025, month: 1 }, label: "Sin cobros" },
      { from: { year: 2025, month: 4 }, to: { year: 2025, month: 4 }, label: "Sin cobros" },
    ]);
  });
});

describe("tchSourceNote", () => {
  it("mapea fuentes", () => {
    expect(tchSourceNote("recaudacion_mensual")).toBe("Fuente: reportes Excel oficiales");
    expect(tchSourceNote("transacciones")).toMatch(/respaldo/);
    expect(tchSourceNote(undefined)).toBeNull();
  });
});
