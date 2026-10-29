import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChannelKpiStrip } from "./ChannelKpiStrip";
import { normalizeKpis } from "../features/shared/kpis";

afterEach(cleanup);

const base = { mrr: 1000, arpu: 500, active_subscribers: 2, active_clients: 2, churn_rate: 1.5, ltv: 900, rejected_charges: { count: 3, amount: 1500 } };

describe("ChannelKpiStrip", () => {
  it("churn null y ARPU null muestran guion y subtexto honesto", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("toku", { ...base, churn_rate: null, arpu: null })} />);
    expect(screen.getAllByLabelText("sin datos").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Sin base para calcular").length).toBeGreaterThanOrEqual(2);
  });

  it("MRR 0 y churn 0 son valores reales", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("toku", { ...base, mrr: 0, churn_rate: 0 })} />);
    expect(screen.getByText("$0")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.queryByLabelText("sin datos")).not.toBeInTheDocument();
  });

  it("usa churn_window_label como subtexto y el título genérico 'Churn'", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("virtualpos", { ...base, churn_window_label: "promedio de 3 meses" })} />);
    expect(screen.getByText("Churn")).toBeInTheDocument();
    expect(screen.getByText("promedio de 3 meses")).toBeInTheDocument();
    expect(screen.queryByText(/churn mensual/i)).not.toBeInTheDocument();
  });

  it("acepta la etiqueta de ventana a nivel de payload (fallback)", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("tch", base, "acumulado histórico")} />);
    expect(screen.getByText("acumulado histórico")).toBeInTheDocument();
  });

  it("forma vieja (sin etiqueta) no rompe y no afirma ventana mensual", () => {
    render(<ChannelKpiStrip kpis={normalizeKpis("payku", base)} />);
    expect(screen.getByText("Churn")).toBeInTheDocument();
    expect(screen.queryByText(/churn mensual/i)).not.toBeInTheDocument();
  });

  it("sin kpis todo queda en guion", () => {
    render(<ChannelKpiStrip kpis={null} />);
    expect(screen.getAllByLabelText("sin datos").length).toBeGreaterThanOrEqual(4);
  });
});
