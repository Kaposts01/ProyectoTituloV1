import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelChart, ChartTooltipContent } from "./ChannelChart";
import { fmt, plotRowsFor, rankItems, waterfallFill } from "./chartModel";
import { buildChartRows } from "./chartRows";
import { RankingChart } from "./RankingChart";

// VIZ-03 (porcentajes y teclado), VIZ-04 (variantes) y VIZ-09 (pruebas del sprint). Datos sintéticos.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div data-testid="rc">{cloneElement(children, { width: 600, height: 280 })}</div>
    ),
  };
});

afterEach(cleanup);

const flow = [
  { key: "activations", label: "Altas", color: "var(--flow-in)" },
  { key: "cancellations", label: "Bajas", color: "var(--flow-out)" },
];
const flowData = [
  { year: 2026, month: 1, activations: 10, cancellations: 4 },
  { year: 2026, month: 2, activations: 3, cancellations: 6 },
  { year: 2026, month: 3, activations: 8, cancellations: 2 },
];
const yTicks = (c: HTMLElement) => [...c.querySelectorAll(".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value")].map((t) => t.textContent ?? "");
const openTable = () => {
  fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
  return screen.getByRole("table");
};
const cellsOf = (table: HTMLElement, row: number) => within(within(table).getAllByRole("row")[row]).getAllByRole("cell").map((c) => c.textContent);

describe("fmt", () => {
  it("formatea porcentaje con coma decimal, monto con $ y sin dato como guion", () => {
    expect(fmt(2.5, "percent")).toBe("2,5 %");
    expect(fmt(12, "percent")).toBe("12 %");
    expect(fmt(-1500, "amount")).toBe("-$1.500");
    expect(fmt(null, "count")).toBe("—");
    expect(fmt(undefined, "percent")).toBe("—");
  });
});

describe("ChannelChart: serie en porcentaje (VIZ-03)", () => {
  const churn = [{ key: "rate", label: "Churn mensual", color: "var(--series-1)" }];
  const rates = [{ year: 2026, month: 1, rate: 1.5 }, { year: 2026, month: 2, rate: 3.25 }];

  it("el eje Y y la tabla están en %", () => {
    const { container } = render(<ChannelChart series={churn} data={rates} kind="line" mode="percent" year={2026} showDataToggle />);
    const ticks = yTicks(container);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.every((t) => / %$/.test(t))).toBe(true);
    const table = openTable();
    expect(cellsOf(table, 1)).toEqual(["1,5 %"]);
    expect(cellsOf(table, 2)).toEqual(["3,3 %"]);
  });

  it("el tooltip único muestra el valor en %", () => {
    render(<ChartTooltipContent active label="Feb" mode="percent" payload={[{ name: "Churn mensual", value: 3.25, dataKey: "rate", color: "x", payload: { rate: 3.25 } }]} />);
    expect(screen.getByText(/Churn mensual/)).toHaveTextContent("3,3 %");
  });
});

describe("ChannelChart: teclado (VIZ-03)", () => {
  it("las flechas recorren los meses y leen los valores del mes en una región aria-live", () => {
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="grouped" mode="count" year={2026} ariaLabel="Altas y bajas" />);
    const plot = screen.getByRole("group", { name: /Altas y bajas \(recorrer con flechas\)/ });
    expect(plot).toHaveAttribute("tabindex", "0");
    const live = container.querySelector(".chart-readout")!;
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live.textContent).toBe("");
    fireEvent.keyDown(plot, { key: "ArrowRight" });
    expect(live.textContent).toBe("Ene: Altas 10 · Bajas 4");
    fireEvent.keyDown(plot, { key: "ArrowRight" });
    expect(live.textContent).toBe("Feb: Altas 3 · Bajas 6");
    fireEvent.keyDown(plot, { key: "End" });
    expect(live.textContent).toMatch(/^Mar:/);
    fireEvent.keyDown(plot, { key: "ArrowRight" }); // no pasa del último
    expect(live.textContent).toMatch(/^Mar:/);
    fireEvent.keyDown(plot, { key: "Home" });
    expect(live.textContent).toMatch(/^Ene:/);
    fireEvent.keyDown(plot, { key: "ArrowLeft" }); // no pasa del primero
    expect(live.textContent).toMatch(/^Ene:/);
    fireEvent.keyDown(plot, { key: "Escape" });
    expect(live.textContent).toBe("");
  });

  it("el mes elegido se marca en el gráfico con una línea de foco", () => {
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="grouped" mode="count" year={2026} />);
    expect(container.querySelector(".chart-focus-marker")).toBeNull();
    fireEvent.keyDown(screen.getByRole("group"), { key: "ArrowLeft" });
    expect(container.querySelector(".chart-focus-marker")).not.toBeNull();
  });

  it("la flecha izquierda sin selección empieza por el último mes (el más reciente)", () => {
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="bar" mode="count" year={2026} />);
    fireEvent.keyDown(screen.getByRole("group"), { key: "ArrowLeft" });
    expect(container.querySelector(".chart-readout")!.textContent).toMatch(/^Mar:/);
  });

  it("otras teclas no hacen nada (Tab sigue su curso)", () => {
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="bar" mode="count" year={2026} />);
    const ev = fireEvent.keyDown(screen.getByRole("group"), { key: "Tab" });
    expect(ev).toBe(true); // no se llamó preventDefault
    expect(container.querySelector(".chart-readout")!.textContent).toBe("");
  });
});

describe("ChannelChart: variantes (VIZ-04)", () => {
  it("divergente: la primera serie arriba y las demás abajo; tabla y tooltip en valor absoluto", () => {
    const rows = plotRowsFor("diverging", buildChartRows(flowData, 2026), flow);
    expect(rows[0].__neg_cancellations).toBe(-4);
    expect(rows[0].activations).toBe(10);
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="diverging" mode="count" year={2026} showDataToggle />);
    expect(yTicks(container).some((t) => t.startsWith("-"))).toBe(false); // el eje no muestra negativos
    expect(container.querySelector(".recharts-reference-line")).not.toBeNull(); // línea de cero
    expect(cellsOf(openTable(), 1)).toEqual(["10", "4"]);
    cleanup();
    render(<ChartTooltipContent active label="Ene" mode="count" absolute payload={[{ name: "Bajas", value: -4, dataKey: "__neg_cancellations", color: "x", payload: {} }]} />);
    expect(screen.getByText(/Bajas/)).toHaveTextContent("Bajas: 4");
  });

  it("apilada al 100 %: cada mes suma 100 y el eje va de 0 a 100 %", () => {
    const rows = plotRowsFor("stacked100", buildChartRows(flowData, 2026), flow);
    for (const r of rows) expect(Number(r.__pct_activations) + Number(r.__pct_cancellations)).toBeCloseTo(100, 0);
    expect(rows[1].__pct_cancellations).toBe(66.7);
    const { container } = render(<ChannelChart series={flow} data={flowData} kind="stacked100" mode="count" year={2026} showDataToggle />);
    const ticks = yTicks(container);
    expect(ticks[0]).toBe("0 %");
    expect(ticks[ticks.length - 1]).toBe("100 %");
    const table = openTable();
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Período", "Altas", "Altas (%)", "Bajas", "Bajas (%)", "Total"]);
    expect(cellsOf(table, 2)).toEqual(["3", "33,3 %", "6", "66,7 %", "9"]);
  });

  it("apilada al 100 %: un mes sin total no inventa porcentajes", () => {
    const rows = plotRowsFor("stacked100", buildChartRows([{ year: 2026, month: 1, activations: 0, cancellations: 0 }], 2026), flow);
    expect(rows[0].__pct_activations).toBeNull();
  });

  it("apilada al 100 %: el tooltip muestra el % y el valor original", () => {
    render(<ChartTooltipContent active label="Feb" mode="count" share payload={[{ name: "Bajas", value: 66.7, dataKey: "__pct_cancellations", color: "x", payload: { cancellations: 6 } }]} />);
    expect(screen.getByText(/Bajas/)).toHaveTextContent("Bajas: 66,7 % (6)");
  });

  it("waterfall: cada barra flota desde el acumulado anterior; sube en azul y baja en naranja", () => {
    const net = [{ key: "net", label: "Crecimiento neto", color: "var(--flow-in)" }];
    const data = [{ year: 2026, month: 1, net: 6 }, { year: 2026, month: 2, net: -3 }, { year: 2026, month: 3, net: 6 }];
    const rows = plotRowsFor("waterfall", buildChartRows(data, 2026), net, 100);
    expect(rows.map((r) => r.__range)).toEqual([[100, 106], [103, 106], [103, 109]]);
    expect(rows.map((r) => r.__cum)).toEqual([106, 103, 109]);
    const { container } = render(<ChannelChart series={net} data={data} kind="waterfall" mode="count" year={2026} legend showDataToggle />);
    expect(container.querySelectorAll(".recharts-bar-rectangle")).toHaveLength(3);
    expect(rows.map((r) => waterfallFill(Number(r.__delta)))).toEqual(["var(--flow-in)", "var(--flow-out)", "var(--flow-in)"]);
    expect(screen.getByText("Sube")).toBeInTheDocument();
    expect(screen.getByText("Baja")).toBeInTheDocument();
    const table = openTable();
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Período", "Crecimiento neto", "Acumulado"]);
    expect(cellsOf(table, 1)).toEqual(["+6", "6"]);
    expect(cellsOf(table, 2)).toEqual(["-3", "3"]);
  });

  it("waterfall: el tooltip muestra la variación con signo y el acumulado", () => {
    render(<ChartTooltipContent active label="Feb" mode="count" waterfall payload={[{ name: "Crecimiento neto", value: [3, 6], dataKey: "__range", color: "x", payload: { __delta: -3, __cum: 3 } }]} />);
    expect(screen.getByText(/Variación/)).toHaveTextContent("Variación: -3");
    expect(screen.getByText(/Acumulado/)).toHaveTextContent("Acumulado: 3");
  });
});

describe("RankingChart: barras horizontales ordenadas (VIZ-04)", () => {
  const items = [
    { key: "toku", label: "Toku", value: 40 },
    { key: "vp", label: "VirtualPOS", value: 120 },
    { key: "tch", label: "TCH", value: null },
    { key: "payku", label: "Payku", value: 40 },
  ];

  it("ordena de mayor a menor (empate por nombre) y omite los sin dato", () => {
    expect(rankItems(items).map((i) => i.key)).toEqual(["vp", "payku", "toku"]);
  });

  it("dibuja barras horizontales con role img y tabla de posiciones", () => {
    const { container } = render(<RankingChart items={items} mode="amount" ariaLabel="Recaudación por canal" showDataToggle valueLabel="Recaudación" />);
    expect(screen.getByRole("img", { name: "Recaudación por canal" })).toBeInTheDocument();
    expect(container.querySelectorAll(".recharts-bar-rectangle")).toHaveLength(3);
    const table = openTable();
    expect(within(table).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["VirtualPOS", "Payku", "Toku"]);
    expect(cellsOf(table, 1)).toEqual(["1", "$120"]);
  });

  it("sin ningún dato muestra el vacío", () => {
    render(<RankingChart items={[{ key: "a", label: "A", value: null }]} mode="count" ariaLabel="x" />);
    expect(screen.getByText("Sin datos para comparar.")).toBeInTheDocument();
  });
});
