import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelChart, ChartTooltipContent } from "./ChannelChart";

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

// Datos sintéticos: monto por fuente y mes (en pesos).
const series = [
  { key: "pasarelas", label: "Pasarelas", color: "#7f55da" },
  { key: "etas", label: "Etas", color: "#434ce6" },
];
const data = [
  { year: 2026, month: 1, pasarelas: 80, etas: 10 },
  { year: 2026, month: 2, pasarelas: 90, etas: 12 },
  { year: 2026, month: 3, pasarelas: 70, etas: 5 },
];

describe("ChannelChart: línea de referencia y eje en porcentaje", () => {
  it("dibuja la meta como línea punteada con su etiqueta", () => {
    const { container } = render(
      <ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} reference={{ value: 100, label: "Meta del mes" }} />,
    );
    expect(screen.getByText("Meta del mes")).toBeInTheDocument();
    const line = container.querySelector(".recharts-reference-line-line");
    expect(line).toBeTruthy();
    expect(line?.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(line?.getAttribute("stroke")).toBe("var(--chart-ref)");
  });

  it("sin referencia no hay línea de meta", () => {
    const { container } = render(<ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} />);
    expect(container.querySelector(".recharts-reference-line-line")).toBeNull();
  });

  it("percentAxis con meta rotula el eje en % de la meta", () => {
    const { container } = render(
      <ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} reference={{ value: 100, label: "Meta" }} percentAxis />,
    );
    const ticks = [...container.querySelectorAll(".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value")].map((t) => t.textContent);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.every((t) => /%$/.test(t ?? ""))).toBe(true);
    expect(ticks).toContain("100 %");
  });

  it("percentAxis sin meta se ignora (eje en montos)", () => {
    const { container } = render(<ChannelChart series={series} data={data} kind="bar" mode="amount" year={2026} percentAxis />);
    const ticks = [...container.querySelectorAll(".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value")].map((t) => t.textContent);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.some((t) => /%/.test(t ?? ""))).toBe(false);
  });
});

describe("ChartTooltipContent: tooltip único con total y % de la meta", () => {
  const payload = [
    { name: "Pasarelas", value: 91800000, color: "#7f55da", dataKey: "pasarelas", payload: { pasarelas: 91800000, etas: 4200000 } },
    { name: "Etas", value: 4200000, color: "#434ce6", dataKey: "etas", payload: { pasarelas: 91800000, etas: 4200000 } },
  ];

  it("lista cada fuente, el total y el % de la meta", () => {
    render(<ChartTooltipContent active label="Sep 26" payload={payload} mode="amount" showTotal reference={{ value: 120000000, label: "Meta del mes" }} />);
    expect(screen.getByText("Sep 26")).toBeInTheDocument();
    expect(screen.getByText(/Pasarelas/)).toHaveTextContent("$91.800.000");
    expect(screen.getByText(/Etas/)).toHaveTextContent("$4.200.000");
    expect(screen.getByText(/Meta del mes/)).toHaveTextContent("$120.000.000");
    const total = screen.getByText(/Total/);
    expect(total).toHaveTextContent("$96.000.000");
    expect(total).toHaveTextContent("80 % de la meta");
  });

  it("sin meta muestra el total pero no el porcentaje", () => {
    render(<ChartTooltipContent active label="Sep 26" payload={payload} mode="amount" showTotal />);
    expect(screen.getByText(/Total/)).not.toHaveTextContent("%");
  });

  it("inactivo o sin payload no renderiza nada", () => {
    const { container, rerender } = render(<ChartTooltipContent active={false} label="x" payload={payload} mode="amount" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ChartTooltipContent active label="x" payload={[]} mode="amount" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("acumulado: real, ritmo y brecha bajo el ritmo", () => {
    const cp = [
      { name: "Real acumulado", value: 188.1, color: "#7f55da", dataKey: "real", payload: { real: 188.1, pace: 225, projection: null } },
      { name: "Ritmo meta", value: 225, color: "#2b3350", dataKey: "pace", payload: { real: 188.1, pace: 225, projection: null } },
    ];
    render(<ChartTooltipContent active label="Feb" payload={cp} mode="count" cumulative />);
    expect(screen.getByText(/Bajo el ritmo por/)).toHaveTextContent("36,9");
  });

  it("acumulado: sobre el ritmo", () => {
    const cp = [{ name: "Real acumulado", value: 300, color: "#7f55da", dataKey: "real", payload: { real: 300, pace: 225, projection: null } }];
    render(<ChartTooltipContent active label="Feb" payload={cp} mode="count" cumulative />);
    expect(screen.getByText(/Sobre el ritmo por/)).toHaveTextContent("75");
  });
});

describe("ChannelChart: «Ver datos» con tabla alternativa", () => {
  it("no hay botón si no se pide", () => {
    render(<ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} />);
    expect(screen.queryByRole("button", { name: "Ver datos" })).not.toBeInTheDocument();
  });

  it("el botón alterna la tabla con aria-expanded y aria-controls", () => {
    render(<ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} showDataToggle ariaLabel="Ingreso por fuente" />);
    const btn = screen.getByRole("button", { name: "Ver datos" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.getByRole("button", { name: "Ocultar datos" })).toHaveAttribute("aria-expanded", "true");
    const table = screen.getByRole("table", { name: /Ingreso por fuente/ });
    expect(btn.getAttribute("aria-controls")).toBe(table.closest("[id]")?.id);
    fireEvent.click(screen.getByRole("button", { name: "Ocultar datos" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("la tabla apilada trae período, fuentes, total y % de la meta", () => {
    render(
      <ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} showDataToggle reference={{ value: 100, label: "Meta del mes" }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    const table = screen.getByRole("table");
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["Período", "Pasarelas", "Etas", "Total", "% de la meta"]);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    const feb = within(rows[2]).getAllByRole("cell").map((c) => c.textContent);
    expect(within(rows[2]).getByRole("rowheader")).toHaveTextContent("Feb");
    expect(feb).toEqual(["$90", "$12", "$102", "102 %"]);
  });

  it("tabla de líneas sin total ni meta", () => {
    render(<ChannelChart series={series} data={data} kind="line" mode="count" year={2026} showDataToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Período", "Pasarelas", "Etas"]);
  });

  it("el botón se opera con teclado (es un button nativo, Enter/clic lo activa)", () => {
    render(<ChannelChart series={series} data={data} kind="bar" mode="count" year={2026} showDataToggle />);
    const btn = screen.getByRole("button", { name: "Ver datos" });
    expect(btn.tagName).toBe("BUTTON");
    expect(btn).toHaveAttribute("type", "button");
  });
});

describe("ChannelChart: acumulado vs ritmo vs proyección", () => {
  const monthly = [
    { year: 2026, month: 1, total: 100 },
    { year: 2026, month: 2, total: 100 },
    { year: 2026, month: 3, total: 100 },
  ];
  const cumSeries = [{ key: "total", label: "Ingreso", color: "#7f55da" }];

  it("renderiza con role img y trae las tres series en la tabla", () => {
    render(
      <ChannelChart series={cumSeries} data={monthly} kind="cumulative" mode="amount" year={2026} cumulative={{ annualTarget: 1200 }} showDataToggle ariaLabel="Acumulado" legend />,
    );
    expect(screen.getByRole("img", { name: "Acumulado" })).toBeInTheDocument();
    expect(screen.getByText("Real acumulado")).toBeInTheDocument();
    expect(screen.getByText("Ritmo meta")).toBeInTheDocument();
    expect(screen.getByText("Proyección")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Período", "Real acumulado", "Ritmo meta", "Proyección", "Diferencia vs ritmo"]);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(13);
    const mar = within(rows[3]).getAllByRole("cell").map((c) => c.textContent);
    expect(mar).toEqual(["$300", "$300", "$300", "$0"]);
    const abr = within(rows[4]).getAllByRole("cell").map((c) => c.textContent);
    expect(abr).toEqual(["—", "$400", "$400", "—"]);
  });

  it("sin meta: no hay serie ni columna de ritmo", () => {
    render(<ChannelChart series={cumSeries} data={monthly} kind="cumulative" mode="count" year={2026} cumulative={{ annualTarget: null }} showDataToggle legend />);
    expect(screen.queryByText("Ritmo meta")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Período", "Real acumulado", "Proyección"]);
  });

  it("año sin datos: mensaje vacío", () => {
    render(<ChannelChart series={cumSeries} data={monthly} kind="cumulative" mode="count" year={2030} cumulative={{ annualTarget: 10 }} />);
    expect(screen.getByText("Sin datos para el período.")).toBeInTheDocument();
  });
});

describe("ChannelChart: teclado", () => {
  it("el gráfico es UNA parada de Tab (el contenedor), sin el svg de Recharts como segunda parada", () => {
    const { container } = render(<ChannelChart series={series} data={data} kind="stacked" mode="amount" year={2026} />);
    expect(container.querySelectorAll(".chart-plot[tabindex='0']")).toHaveLength(1);
    expect(container.querySelector("svg.recharts-surface[tabindex='0']")).toBeNull();
  });
});
