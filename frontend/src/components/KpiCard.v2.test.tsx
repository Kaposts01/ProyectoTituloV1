import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";
import { ChurnKpiCard, KpiCard } from "./KpiCard";

afterEach(cleanup);

describe("KpiCard v2: variantes", () => {
  it("por defecto es normal; destacada agrega clase y data-variant", () => {
    const { container, rerender } = render(<KpiCard label="Socios" value={7003} format="count" />);
    expect(container.querySelector("article")).toHaveAttribute("data-variant", "normal");
    expect(container.querySelector("article")).not.toHaveClass("kpi-card--featured");
    rerender(<KpiCard label="Socios" value={7003} format="count" variant="featured" />);
    expect(container.querySelector("article")).toHaveAttribute("data-variant", "featured");
    expect(container.querySelector("article")).toHaveClass("kpi-card--featured");
  });

  it("no anida tarjetas dentro de la tarjeta", () => {
    const { container } = render(<KpiCard label="MRR" value={100} format="clp" goal={{ target: 200 }} delta={{ value: 5 }} sparkline={[1, 2, 3]} />);
    expect(container.querySelectorAll("article, .metric-card, .panel").length).toBe(1);
  });
});

describe("KpiCard v2: delta vs mes anterior", () => {
  it("sube: flecha, signo, texto accesible y semántica positiva", () => {
    render(<KpiCard label="Activaciones" value={169} format="count" delta={{ value: 12 }} />);
    const d = screen.getByTestId("kpi-delta");
    expect(d).toHaveTextContent("▲");
    expect(d).toHaveTextContent("+12");
    expect(d).toHaveTextContent("vs mes anterior");
    expect(d).toHaveTextContent("sube");
    expect(d).toHaveClass("good");
  });

  it("baja: flecha hacia abajo y semántica negativa", () => {
    render(<KpiCard label="Activaciones" value={169} format="count" delta={{ value: -183 }} />);
    const d = screen.getByTestId("kpi-delta");
    expect(d).toHaveTextContent("▼");
    expect(d).toHaveTextContent("-183");
    expect(d).toHaveTextContent("baja");
    expect(d).toHaveClass("bad");
  });

  it("goodWhen=down invierte la semántica (bajar el churn es bueno)", () => {
    render(<KpiCard label="Churn" value={1.04} format="percent" delta={{ value: -0.4, goodWhen: "down" }} />);
    const d = screen.getByTestId("kpi-delta");
    expect(d).toHaveClass("good");
    expect(d).toHaveTextContent("▼");
    expect(d).toHaveTextContent("-0,4 pts");
  });

  it("variación cero: sin cambio y neutro", () => {
    render(<KpiCard label="X" value={5} format="count" delta={{ value: 0 }} />);
    const d = screen.getByTestId("kpi-delta");
    expect(d).toHaveClass("flat");
    expect(d).toHaveTextContent("sin cambio");
  });

  it("monto en CLP con signo y etiqueta personalizada", () => {
    render(<KpiCard label="Recaudo" value={91800000} format="clp" delta={{ value: -2700000, label: "vs agosto" }} />);
    expect(screen.getByTestId("kpi-delta")).toHaveTextContent("-$2.700.000 vs agosto");
  });

  it("delta sin dato muestra texto, no un número inventado", () => {
    render(<KpiCard label="X" value={5} format="count" delta={{ value: null }} />);
    const d = screen.getByTestId("kpi-delta");
    expect(d).toHaveClass("flat");
    expect(d).toHaveTextContent("Sin dato vs mes anterior");
  });
});

describe("KpiCard v2: meta, chip y barra de progreso", () => {
  it("chip explícito con texto y dot (nunca solo color)", () => {
    const { container } = render(<KpiCard label="Cobrabilidad" value={72.4} format="percent" chip="met" />);
    const chip = screen.getByText("en meta");
    expect(chip.closest(".kpi-chip")).toHaveClass("met");
    expect(container.querySelector(".kpi-chip .kpi-chip-dot")).toBeTruthy();
  });

  it("los tres textos de chip", () => {
    render(<><KpiCard label="A" value={1} format="count" chip="met" /><KpiCard label="B" value={1} format="count" chip="off" /><KpiCard label="C" value={1} format="count" chip="none" /></>);
    expect(screen.getByText("en meta")).toBeInTheDocument();
    expect(screen.getByText("lejos de meta")).toBeInTheDocument();
    expect(screen.getByText("sin meta")).toBeInTheDocument();
  });

  it("barra de progreso con porcentaje en texto y aria", () => {
    render(<KpiCard label="Ingreso total" value={101} format="count" goal={{ target: 123.9 }} />);
    const bar = screen.getByRole("progressbar", { name: /Ingreso total/ });
    expect(bar).toHaveAttribute("aria-valuenow", "82");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.getByText(/82 % de la meta/)).toBeInTheDocument();
    expect(screen.getByText("lejos de meta")).toBeInTheDocument();
  });

  it("superar la meta: barra topada en 100 pero el texto dice el avance real; chip en meta", () => {
    render(<KpiCard label="Altas" value={150} format="count" goal={{ target: 100 }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText(/150 % de la meta/)).toBeInTheDocument();
    expect(screen.getByText("en meta")).toBeInTheDocument();
  });

  it("sin meta: chip «sin meta» y sin barra", () => {
    render(<KpiCard label="Altas" value={150} format="count" goal={{ target: null }} />);
    expect(screen.getByText("sin meta")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("meta de tope (atMost): chip por comparación y texto de meta, sin barra", () => {
    render(<KpiCard label="Churn" value={1.04} format="percent" goal={{ target: 2, direction: "atMost" }} />);
    expect(screen.getByText("en meta")).toBeInTheDocument();
    expect(screen.getByText("Meta: ≤ 2%")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("meta de tope incumplida: lejos de meta", () => {
    render(<KpiCard label="Churn" value={3.5} format="percent" goal={{ target: 2, direction: "atMost" }} />);
    expect(screen.getByText("lejos de meta")).toBeInTheDocument();
  });

  it("el chip explícito gana sobre el derivado", () => {
    render(<KpiCard label="X" value={50} format="count" goal={{ target: 100 }} chip="met" />);
    expect(screen.getByText("en meta")).toBeInTheDocument();
    expect(screen.queryByText("lejos de meta")).not.toBeInTheDocument();
  });

  it("sin dato: ni barra, ni delta, ni chip derivado; conserva «—»", () => {
    render(<KpiCard label="X" value={null} format="clp" goal={{ target: 100 }} delta={{ value: 3 }} emptyCaption="Sin base" />);
    expect(screen.getByLabelText("sin datos")).toHaveTextContent("—");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-delta")).not.toBeInTheDocument();
    expect(screen.queryByText("lejos de meta")).not.toBeInTheDocument();
    expect(screen.getByText("Sin base")).toBeInTheDocument();
  });
});

describe("KpiCard v2: sparkline", () => {
  it("decorativa por defecto (aria-hidden) con polilínea", () => {
    const { container } = render(<KpiCard label="X" value={5} format="count" sparkline={[1, 3, 2, 5]} />);
    const svg = container.querySelector("svg.kpi-spark");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg?.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(4);
  });

  it("con etiqueta se expone como imagen", () => {
    render(<KpiCard label="X" value={5} format="count" sparkline={[1, 3]} sparklineLabel="Últimos 2 meses" />);
    expect(screen.getByRole("img", { name: "Últimos 2 meses" })).toBeInTheDocument();
  });

  it("no dibuja con menos de 2 puntos válidos, descarta NaN y dibuja la serie plana", () => {
    const { container } = render(<><KpiCard label="A" value={5} format="count" sparkline={[1]} /><KpiCard label="B" value={5} format="count" sparkline={[NaN, 2]} /><KpiCard label="C" value={5} format="count" sparkline={[2, 2, 2]} /></>);
    expect(container.querySelectorAll("svg.kpi-spark")).toHaveLength(1);
  });
});

describe("ChurnKpiCard (D20)", () => {
  it("tarjeta con valor, chip, meta y sparkline; no es un velocímetro", () => {
    const { container } = render(<ChurnKpiCard churnRate={1.04} target={2} history={[1.5, 1.3, 1.04]} previous={1.3} windowLabel="Promedio de 3 meses" />);
    expect(screen.getByText("Churn")).toBeInTheDocument();
    expect(screen.getByText("1%")).toHaveClass("mono");
    expect(screen.getByText("en meta")).toBeInTheDocument();
    expect(screen.getByText("Meta: ≤ 2%")).toBeInTheDocument();
    expect(container.querySelector("svg.kpi-spark")).toBeTruthy();
    expect(screen.getByTestId("kpi-delta")).toHaveClass("good");
    expect(screen.getByText("Promedio de 3 meses")).toBeInTheDocument();
    expect(container.querySelector("[role=meter], .gauge")).toBeNull();
  });

  it("sin meta ni dato: «sin meta» y «—»", () => {
    render(<ChurnKpiCard churnRate={null} target={null} />);
    expect(screen.getByLabelText("sin datos")).toBeInTheDocument();
    expect(screen.getByText("sin meta")).toBeInTheDocument();
  });
});

describe("KpiCard v2: estilos (DESIGN.md)", () => {
  const css = readFileSync("src/Staging.css", "utf8");
  it("sin borde lateral de color en las tarjetas KPI", () => {
    const kpi = css.slice(css.indexOf("/* ── KpiCard v2"));
    expect(kpi.length).toBeGreaterThan(100);
    expect(kpi).not.toMatch(/border-(left|inline-start)\s*:/);
  });
  it("la tarjeta destacada usa los tokens de tarjeta destacada", () => {
    const kpi = css.slice(css.indexOf("/* ── KpiCard v2"));
    expect(kpi).toMatch(/--kpi-hero-bg/);
    expect(kpi).toMatch(/--chip-ok-bg/);
    expect(kpi).toMatch(/--delta-up/);
  });
});
