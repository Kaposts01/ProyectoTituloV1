import { cleanup, render } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelChart } from "./components/ChannelChart";
import {
  ActivacionCaidaChart, IngresosMensualesChart, MonthlyStatusChart, MonthlySimpleChart, TransaccionesSuscripcionesChart,
} from "./MonthlyStatusChart";

type Props = Record<string, unknown>;
const seen = vi.hoisted(() => ({ Bar: [] as Props[], Line: [] as Props[], Area: [] as Props[], YAxis: [] as Props[], CartesianGrid: [] as Props[] }));

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  const spy = (name: "Bar" | "Line" | "Area" | "YAxis" | "CartesianGrid") => {
    const Real = actual[name] as unknown as (p: Props) => ReactElement;
    return (props: Props) => {
      seen[name].push(props);
      return <Real {...props} />;
    };
  };
  return {
    ...actual,
    Bar: spy("Bar"), Line: spy("Line"), Area: spy("Area"), YAxis: spy("YAxis"), CartesianGrid: spy("CartesianGrid"),
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div>{cloneElement(children, { width: 600, height: 280 })}</div>
    ),
  };
});

beforeEach(() => { for (const k of Object.keys(seen) as (keyof typeof seen)[]) seen[k].length = 0; });
afterEach(cleanup);

const series = [{ key: "count", label: "Cantidad", color: "#2a7a64" }];
const one = [{ year: 2025, month: 3, count: 30 }];
const entries = [{ year: 2026, month: 1, status: "PAGADO", count: 3, amount: 100 }];
const simple = [{ year: 2026, month: 1, count: 3, amount: 100 }];

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

  it("las líneas no se suavizan (linear)", () => {
    render(<ChannelChart series={series} data={[...one, { year: 2025, month: 4, count: 3 }]} kind="line" mode="count" year={2025} />);
    expect(seen.Line.length).toBeGreaterThan(0);
    for (const l of seen.Line) expect(l.type).toBe("linear");
  });
});

describe("componentes antiguos (dashboard general)", () => {
  it("MonthlyStatusChart: maxBarSize, eje sin decimales en conteo y rejilla tokenizada", () => {
    render(<MonthlyStatusChart data={entries} mode="count" year={null} />);
    expect(seen.Bar[0].maxBarSize).toBeGreaterThan(0);
    expect(seen.YAxis[0].allowDecimals).toBe(false);
    expect(seen.CartesianGrid[0].stroke).toBe("var(--border-subtle)");
  });

  it("MonthlyStatusChart en monto permite decimales", () => {
    render(<MonthlyStatusChart data={entries} mode="amount" year={null} />);
    expect(seen.YAxis[0].allowDecimals).not.toBe(false);
  });

  it("MonthlySimpleChart: maxBarSize y rejilla tokenizada", () => {
    render(<MonthlySimpleChart data={simple} color="#2563EB" mode="count" year={null} />);
    expect(seen.Bar[0].maxBarSize).toBeGreaterThan(0);
    expect(seen.CartesianGrid[0].stroke).toBe("var(--border-subtle)");
  });

  it("ActivacionCaidaChart: línea linear, barra acotada, eje sin decimales en conteo", () => {
    render(<ActivacionCaidaChart activaciones={entries} caidas={simple} year={null} mode="count" />);
    expect(seen.Line.every((l) => l.type === "linear")).toBe(true);
    expect(seen.Bar[0].maxBarSize).toBeGreaterThan(0);
    expect(seen.YAxis[0].allowDecimals).toBe(false);
  });

  it("TransaccionesSuscripcionesChart: líneas linear y ejes sin decimales", () => {
    render(<TransaccionesSuscripcionesChart payments={entries} activeSubs={simple} cobrableSubs={simple} year={null} mode="count" />);
    expect(seen.Line.length).toBe(2);
    expect(seen.Line.every((l) => l.type === "linear")).toBe(true);
    expect(seen.YAxis.every((y) => y.allowDecimals === false)).toBe(true);
  });

  it("IngresosMensualesChart: áreas linear y rejilla tokenizada", () => {
    render(<IngresosMensualesChart data={[{ year: 2026, month: 1, status: "Toku", count: 1, amount: 5000 }]} year={null} />);
    expect(seen.Area.every((a) => a.type === "linear")).toBe(true);
    expect(seen.CartesianGrid[0].stroke).toBe("var(--border-subtle)");
  });
});
