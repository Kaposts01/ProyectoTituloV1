import { cleanup, render } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelChart } from "./components/ChannelChart";

type Props = Record<string, unknown>;
const seen = vi.hoisted(() => ({ Bar: [] as Props[], Line: [] as Props[], Area: [] as Props[], YAxis: [] as Props[], XAxis: [] as Props[], CartesianGrid: [] as Props[] }));

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  const spy = (name: "Bar" | "Line" | "Area" | "YAxis" | "XAxis" | "CartesianGrid") => {
    const Real = actual[name] as unknown as (p: Props) => ReactElement;
    return (props: Props) => {
      seen[name].push(props);
      return <Real {...props} />;
    };
  };
  return {
    ...actual,
    Bar: spy("Bar"), Line: spy("Line"), Area: spy("Area"), YAxis: spy("YAxis"), XAxis: spy("XAxis"), CartesianGrid: spy("CartesianGrid"),
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div>{cloneElement(children, { width: 600, height: 280 })}</div>
    ),
  };
});

beforeEach(() => { for (const k of Object.keys(seen) as (keyof typeof seen)[]) seen[k].length = 0; });
afterEach(cleanup);

const series = [{ key: "count", label: "Cantidad", color: "#2a7a64" }];
const one = [{ year: 2025, month: 3, count: 30 }];

describe("ChannelChart: mínimos de gráfico", () => {
  it("limita el ancho de barra para que una sola categoría no ocupe todo el ancho", () => {
    for (const kind of ["bar", "stacked", "grouped"] as const) {
      seen.Bar.length = 0;
      render(<ChannelChart series={series} data={one} kind={kind} mode="count" year={2025} />);
      const max = seen.Bar[0]?.maxBarSize as number;
      expect(max, kind).toBeGreaterThan(0);
      expect(max, kind).toBeLessThanOrEqual(64);
      cleanup();
    }
  });

  it("eje Y sin decimales en modo conteo, con decimales permitidos en monto", () => {
    render(<ChannelChart series={series} data={one} kind="bar" mode="count" year={2025} />);
    expect(seen.YAxis[0].allowDecimals).toBe(false);
    cleanup();
    seen.YAxis.length = 0;
    render(<ChannelChart series={series} data={one} kind="bar" mode="amount" year={2025} />);
    expect(seen.YAxis[0].allowDecimals).not.toBe(false);
  });

  it("el eje Y de montos es lo bastante ancho para «$200.000» y «$12.345.678» (no recorta el «$»)", () => {
    const money = [{ year: 2025, month: 3, count: 200000 }];
    render(<ChannelChart series={series} data={money} kind="bar" mode="amount" year={2025} />);
    const narrow = seen.YAxis[0].width as number;
    expect(narrow).toBeGreaterThanOrEqual(8 * 7);
    cleanup();
    seen.YAxis.length = 0;
    render(<ChannelChart series={series} data={[{ year: 2025, month: 3, count: 12345678 }]} kind="bar" mode="amount" year={2025} />);
    expect(seen.YAxis[0].width as number).toBeGreaterThan(narrow);
    expect(seen.YAxis[0].width as number).toBeGreaterThanOrEqual(11 * 7);
  });

  it("el eje Y de conteos conserva su ancho compacto", () => {
    render(<ChannelChart series={series} data={one} kind="bar" mode="count" year={2025} />);
    expect(seen.YAxis[0].width).toBe(56);
  });

  it("el eje X reduce la densidad de marcas: intervalo automático con separación mínima", () => {
    const months = Array.from({ length: 12 }, (_, i) => ({ year: 2025 + Math.floor(i / 12), month: i + 1, count: 5 }));
    render(<ChannelChart series={series} data={months} kind="grouped" mode="count" year={null} />);
    expect(seen.XAxis[0].interval).toBe("preserveStartEnd");
    expect(seen.XAxis[0].minTickGap as number).toBeGreaterThanOrEqual(24);
  });

  it("las líneas no se suavizan (linear)", () => {
    render(<ChannelChart series={series} data={[...one, { year: 2025, month: 4, count: 3 }]} kind="line" mode="count" year={2025} />);
    expect(seen.Line.length).toBeGreaterThan(0);
    for (const l of seen.Line) expect(l.type).toBe("linear");
  });
});

describe("código muerto borrado (VIZ-06, DEC-39)", () => {
  it("MonthlyStatusChart.tsx (TransactionsVsSubscriptionsChart, MonthlySimpleChart y los 6 restantes) ya no existe", async () => {
    const { existsSync } = await import("node:fs");
    expect(existsSync("src/MonthlyStatusChart.tsx")).toBe(false);
  });
});
