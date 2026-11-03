import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChannelKpiStrip } from "./ChannelKpiStrip";
import { churnSparkline } from "./chartModel";
import { normalizeKpis } from "../features/shared/kpis";

afterEach(cleanup);

const base = { mrr: 1000, arpu: 500, active_subscribers: 2, active_clients: 2, churn_rate: 1.5, ltv: 900, rejected_charges: { count: 3, amount: 1500 } };
const history = [
  { year: 2026, month: 2, rate: 2 },
  { year: 2025, month: 12, rate: 1 },
  { year: 2026, month: 1, rate: null },
  { year: 2026, month: 3, rate: 1.5 },
];

describe("churnSparkline", () => {
  it("ordena por mes, descarta sin dato y toma los últimos N", () => {
    expect(churnSparkline(history)).toEqual([1, 2, 1.5]);
    expect(churnSparkline(history, 2)).toEqual([2, 1.5]);
    expect(churnSparkline(null)).toEqual([]);
  });
});

describe("ChannelKpiStrip: tarjeta de churn D20 sin meta (DEC-37, DEC-38)", () => {
  it("muestra el chip «sin meta», sin barra de avance, con la definición unificada y la sparkline", () => {
    const { container } = render(<ChannelKpiStrip kpis={normalizeKpis("toku", base)} churnHistory={history} />);
    const card = screen.getByText("Churn").closest("article")!;
    expect(card).toHaveTextContent("sin meta");
    expect(card).toHaveTextContent("Bajas del mes ÷ socios al inicio del mes");
    expect(card.querySelector("[role='progressbar']")).toBeNull();
    expect(card.querySelector(".kpi-spark")).not.toBeNull();
    expect(container.querySelectorAll(".kpi-chip")).toHaveLength(1); // solo la de churn lleva chip
  });

  it("sin historia no dibuja sparkline", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("payku", base)} />);
    expect(screen.getByText("Churn").closest("article")!.querySelector(".kpi-spark")).toBeNull();
  });
});
