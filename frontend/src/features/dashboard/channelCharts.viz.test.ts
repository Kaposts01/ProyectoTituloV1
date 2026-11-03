import { describe, expect, it } from "vitest";
import {
  activationVsChurnChart, activationVsChurnWithNet, churnRateChart, netGrowthChart, rankingByStatus, seriesStackedChart,
} from "./channelCharts";

// VIZ-09: mapeos de datos de los gráficos migrados (VIZ-06 a VIZ-08). Datos sintéticos.

describe("altas y bajas (DEC-36, VIZ-08)", () => {
  it("altas en azul (--flow-in) y bajas en naranja (--flow-out), nunca el rojo de rechazo", () => {
    const { series } = activationVsChurnChart([{ year: 2026, month: 1, count: 1 }], [{ year: 2026, month: 1, count: 1 }], "count");
    expect(series.map((s) => s.color)).toEqual(["var(--flow-in)", "var(--flow-out)"]);
    expect(series.map((s) => s.color)).not.toContain("var(--status-rejected)");
  });
  it("una suscripción fallida de VirtualPOS no cuenta como alta", () => {
    const { rows } = activationVsChurnChart(
      [{ year: 2026, month: 1, status: "ACTIVA", count: 4 }, { year: 2026, month: 1, status: "SUSCRIPCION_FALLIDA", count: 9 }],
      [{ year: 2026, month: 1, count: 1 }],
      "count",
    );
    expect(rows[0]).toMatchObject({ activations: 4, cancellations: 1 });
  });
  it("agrega el neto (altas − bajas) por mes, con meses intermedios en cero", () => {
    const { rows } = activationVsChurnWithNet([{ year: 2026, month: 1, count: 5 }, { year: 2026, month: 3, count: 1 }], [{ year: 2026, month: 3, count: 4 }], "count");
    expect(rows.map((r) => r.net)).toEqual([5, 0, -3]);
  });
});

describe("netGrowthChart («Crecimiento real mensual» como waterfall, VIZ-06)", () => {
  it("una sola serie `net` con el cambio de cada mes", () => {
    const { rows, series } = netGrowthChart([{ year: 2026, month: 1, count: 3 }, { year: 2026, month: 2, count: 1 }], [{ year: 2026, month: 2, count: 2 }], "count");
    expect(series).toHaveLength(1);
    expect(series[0].key).toBe("net");
    expect(rows).toEqual([{ year: 2026, month: 1, net: 3 }, { year: 2026, month: 2, net: -1 }]);
  });
  it("monto usa los montos", () => {
    const { rows } = netGrowthChart([{ year: 2026, month: 1, count: 1, amount: 1000 }], [{ year: 2026, month: 1, count: 1, amount: 300 }], "amount");
    expect(rows[0].net).toBe(700);
  });
  it("sin datos no hay filas", () => {
    expect(netGrowthChart(undefined, undefined, "count").rows).toEqual([]);
  });
});

describe("churnRateChart («Churn %» en porcentaje, VIZ-06)", () => {
  it("ordena por mes, descarta sin dato y usa la serie `rate`", () => {
    const { rows, series } = churnRateChart([
      { year: 2026, month: 2, rate: 2.5 },
      { year: 2025, month: 12, rate: 1 },
      { year: 2026, month: 1, rate: null },
    ]);
    expect(series[0].key).toBe("rate");
    expect(rows).toEqual([{ year: 2025, month: 12, rate: 1 }, { year: 2026, month: 2, rate: 2.5 }]);
  });
});

describe("rankingByStatus (motivos de rechazo como ranking, VIZ-08)", () => {
  const rejected = [
    { year: 2026, month: 1, status: "Reintento", count: 3, amount: 300 },
    { year: 2026, month: 2, status: "Reintento", count: 2, amount: 200 },
    { year: 2026, month: 2, status: "Cambio de tarjeta", count: 4, amount: 900 },
    { year: 2025, month: 12, status: "Cambio de tarjeta", count: 10, amount: 1 },
  ];
  it("suma por motivo dentro del año", () => {
    expect(rankingByStatus(rejected, "count", 2026)).toEqual([
      { key: "Reintento", label: "Reintento", value: 5 },
      { key: "Cambio de tarjeta", label: "Cambio de tarjeta", value: 4 },
    ]);
  });
  it("year null suma todo y monto suma montos", () => {
    expect(rankingByStatus(rejected, "amount", null).find((i) => i.key === "Cambio de tarjeta")?.value).toBe(901);
  });
});

describe("seriesStackedChart (dashboard general, VIZ-07)", () => {
  it("rellena meses intermedios y rotula y colorea los canales como canales", () => {
    const { rows, series } = seriesStackedChart([
      { year: 2026, month: 1, status: "Toku", count: 1, amount: 0 },
      { year: 2026, month: 3, status: "Payku", count: 2, amount: 0 },
    ], "count");
    expect(rows.map((r) => r.month)).toEqual([1, 2, 3]);
    expect(series.map((s) => s.label)).toEqual(["Payku", "Toku"]);
    expect(series.map((s) => s.color)).toEqual(["var(--series-4)", "var(--series-2)"]);
  });
});
