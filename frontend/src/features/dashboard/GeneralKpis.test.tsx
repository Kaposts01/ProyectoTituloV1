import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { GeneralKpis } from "./GeneralKpis";
import { rejectionRate } from "./generalKpiData";

afterEach(cleanup);

describe("rejectionRate", () => {
  it("devuelve null sin denominador y 0 real con denominador", () => {
    expect(rejectionRate(0, 0)).toBeNull();
    expect(rejectionRate(0, 10)).toBe(0);
    expect(rejectionRate(1, 6)).toBeCloseTo(14.3, 1);
  });
});

const view = (data: object, rejected = 2, accepted = 8) =>
  render(<GeneralKpis data={data} rejectedCount={rejected} acceptedCount={accepted} selectedYear={2026} />);

const noData = (title: string) => screen.getByText(title).closest("article")!.querySelector("[aria-label='sin datos']");

describe("GeneralKpis", () => {
  it("tasa de rechazo sin transacciones es guion, no 0%", () => {
    view({}, 0, 0);
    expect(noData("Tasa de rechazo")).not.toBeNull();
    expect(screen.getByText("Tasa de rechazo").closest("article")).toHaveTextContent("Sin base para calcular");
  });

  it("tasa de rechazo 0 con transacciones es 0%", () => {
    view({}, 0, 10);
    expect(screen.getByText("Tasa de rechazo").closest("article")).toHaveTextContent("0%");
  });

  it("churn null muestra guion; churn 0 muestra 0%", () => {
    const { unmount } = view({ churn_rate_pct: null });
    expect(noData("Churn")).not.toBeNull();
    unmount();
    view({ churn_rate_pct: 0 });
    expect(screen.getByText("Churn").closest("article")).toHaveTextContent("0%");
  });

  it("el título sigue la etiqueta del backend y nunca dice 'este mes' sin ventana", () => {
    const { unmount } = view({ churn_rate_pct: 2.5, churn_window_label: "promedio de 3 meses" });
    expect(screen.getByText("Churn")).toBeInTheDocument();
    expect(screen.getByText("promedio de 3 meses")).toBeInTheDocument();
    expect(screen.getByText("2,5%")).toBeInTheDocument();
    unmount();
    view({ churn_rate_pct: 2.5 });
    expect(screen.getByText("Churn")).toBeInTheDocument();
    expect(screen.queryByText(/este mes|mensual/i)).not.toBeInTheDocument();
  });

  it("pagos pendientes usa pending_payments_label cuando llega y el rótulo viejo si no", () => {
    const { unmount } = view({ pending_payments: 4, pending_payments_label: "Cargos pendientes" });
    expect(screen.getByText("Cargos pendientes")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    unmount();
    view({ pending_payments: 0 });
    expect(screen.getByText("Pagos pendientes").closest("article")).toHaveTextContent("0");
  });

  it("pending_payments ausente es guion (forma muy vieja no rompe)", () => {
    view({});
    expect(noData("Pagos pendientes")).not.toBeNull();
  });

  it("rotula cargos (no transacciones) y explica la tasa", () => {
    view({}, 2, 8);
    expect(screen.getByText("Cargos rechazados")).toBeInTheDocument();
    expect(screen.getByText("Cargos rechazados hasta hoy · no incluye cancelados")).toBeInTheDocument();
    expect(screen.getByText("Tasa de rechazo · rechazados / (pagados + rechazados)")).toBeInTheDocument();
    expect(screen.queryByText(/Transacciones rechazadas|total del año/)).not.toBeInTheDocument();
  });

  it("usa transactions.basis_label del backend si llega", () => {
    view({ transactions: { basis_label: "Cargos al 29-10 (Chile)" } });
    expect(screen.getByText("Cargos al 29-10 (Chile)")).toBeInTheDocument();
  });
});
