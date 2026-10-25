import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { formatKpi } from "./formatKpi";
import { KpiCard } from "./KpiCard";

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

describe("formatKpi", () => {
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
