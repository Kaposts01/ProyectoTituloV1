import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { formatKpi } from "./formatKpi";
import { KpiCard } from "./KpiCard";

afterEach(cleanup);

describe("KpiCard", () => {
  it("formatea CLP con clase mono", () => {
    render(<KpiCard label="MRR" value={1234567} format="clp" />);
    const value = screen.getByText("$1.234.567");
    expect(value.tagName).toBe("STRONG");
    expect(value).toHaveClass("mono");
  });

  it("muestra guion largo cuando el valor es null", () => {
    render(<KpiCard label="ARPU" value={null} format="clp" />);
    expect(screen.getByText("—")).toHaveClass("mono");
  });

  it("formatea porcentaje y conteo", () => {
    render(<><KpiCard label="Churn" value={4.25} format="percent" /><KpiCard label="Subs" value={1500} format="count" /></>);
    expect(screen.getByText("4,3%")).toBeInTheDocument();
    expect(screen.getByText("1.500")).toBeInTheDocument();
  });
});

describe("KpiCard sin datos", () => {
  it("el guion lleva texto accesible 'sin datos' y subtexto en lugar del caption engañoso", () => {
    render(<KpiCard label="Churn" value={null} format="percent" caption="Bajas / activos" emptyCaption="Sin base para calcular" />);
    const dash = screen.getByLabelText("sin datos");
    expect(dash).toHaveTextContent("—");
    expect(dash).toHaveClass("mono");
    expect(screen.getByText("Sin base para calcular")).toBeInTheDocument();
    expect(screen.queryByText("Bajas / activos")).not.toBeInTheDocument();
  });

  it("trata undefined y NaN como sin datos", () => {
    render(<><KpiCard label="A" value={undefined} format="clp" /><KpiCard label="B" value={NaN} format="count" /></>);
    expect(screen.getAllByLabelText("sin datos")).toHaveLength(2);
  });

  it("el cero real se muestra como cero y conserva su caption", () => {
    render(<><KpiCard label="Churn" value={0} format="percent" caption="c1" emptyCaption="Sin base para calcular" /><KpiCard label="MRR" value={0} format="clp" /><KpiCard label="Subs" value={0} format="count" /></>);
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("$0")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByLabelText("sin datos")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin base para calcular")).not.toBeInTheDocument();
    expect(screen.getByText("c1")).toBeInTheDocument();
  });
});

describe("formatKpi", () => {
  it("usa coma decimal en porcentajes", () => {
    expect(formatKpi(14.25, "percent")).toBe("14,3%");
    expect(formatKpi(0, "percent")).toBe("0%");
  });
  it("devuelve guion largo para NaN, Infinity y null", () => {
    for (const v of [NaN, Infinity, -Infinity, null, undefined]) expect(formatKpi(v, "clp")).toBe("—");
  });
  it("pone el signo antes del símbolo en CLP", () => {
    expect(formatKpi(-5, "clp")).toBe("-$5");
    expect(formatKpi(-1234567, "clp")).toBe("-$1.234.567");
  });
  it("normaliza -0 y redondeos a cero", () => {
    expect(formatKpi(0, "clp")).toBe("$0");
    expect(formatKpi(-0, "clp")).toBe("$0");
    expect(formatKpi(-0.4, "clp")).toBe("$0");
    expect(formatKpi(-0, "count")).toBe("0");
    expect(formatKpi(-0.04, "percent")).toBe("0%");
    expect(formatKpi(-0, "percent")).toBe("0%");
  });
  it("mantiene negativos en count y percent", () => {
    expect(formatKpi(-3, "count")).toBe("-3");
    expect(formatKpi(-2.5, "percent")).toBe("-2,5%");
  });
});
