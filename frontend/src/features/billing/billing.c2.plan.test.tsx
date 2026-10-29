import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { buildPlanRows, reconcilePlan } from "./billingPlan";
import { PlanPreviewView } from "./PlanPreviewView";
import type { PlanPreview } from "./types";

afterEach(cleanup);

const monthOf = (i: number) => { const t = 2026 * 12 + 3 + i; return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`; };

/** Plan de 12 meses: 1 mes conservado (cobro de hoy) y 1 mes con dos cobros pendientes (uno extra). */
function bigPlan(over: Partial<PlanPreview> = {}): PlanPreview {
  const months = Array.from({ length: 12 }, (_, i) => monthOf(i));
  const today = months[0];
  const dup = months[3];
  const createMonths = months.filter((m) => m !== today);
  const cancel = [
    ...createMonths.map((m, i) => ({ month: m, charge_date: `${m}-10`, amount: 10000, charge_id: `chg-${i}` })),
    { month: dup, charge_date: `${dup}-11`, amount: 10000, charge_id: "chg-extra" },
  ];
  return {
    noop: false,
    create: createMonths.map((m) => ({ month: m, charge_date: `${m}-15`, amount: 9000, internal_code: `S1-${m}` })),
    cancel, covered: [], manual_review: [], unchanged: [], kept_automatic_after_horizon: [],
    kept_due_today: [today],
    warnings: [
      { code: "due_today_kept", message: "texto del servidor 1", month: today },
      { code: "multiple_pending", message: "texto del servidor 2", month: dup },
    ],
    errors: [],
    summary: {
      creates: 11, cancels: 12, covered_months: 0, manual_review_months: 0, unchanged_months: 0, affected_charges: 23,
      previous_amount: 10000, new_amount: 9000, amount_delta: -1000, total_delta: -10000, variation_pct: -10,
      horizon_start: months[0], horizon_end: months[11],
    },
    ...over,
  };
}

describe("D1 conciliacion del plan", () => {
  it("explica 12 meses con un conservado hoy y un cobro adicional, calculado desde los arreglos", () => {
    const r = reconcilePlan(bigPlan());
    expect(r.text).toBe(
      "12 meses en el horizonte · 1 conservado (cobro de hoy) · 11 cobros nuevos reemplazan a 12 actuales (11 del calendario + 1 con más de un pendiente en el mes)",
    );
    expect(r.extraCancels).toBe(1);
    expect(r.calendarCancels).toBe(11);
  });

  it("sin duplicados ni conservados no inventa desglose", () => {
    const plan = bigPlan({ kept_due_today: [], warnings: [] });
    plan.cancel = plan.cancel!.filter((c) => c.charge_id !== "chg-extra");
    plan.summary = { ...plan.summary!, cancels: 11 };
    expect(reconcilePlan(plan).text).toBe("12 meses en el horizonte · 11 cobros nuevos reemplazan a 11 actuales");
  });

  it("incluye cubiertos y revision manual cuando existen, con plurales correctos", () => {
    const plan: PlanPreview = {
      create: [{ month: "2026-05", charge_date: "2026-05-10", amount: 9000, internal_code: "x" }],
      cancel: [{ month: "2026-05", charge_date: "2026-05-05", amount: 10000, charge_id: "c1" }],
      covered: [{ month: "2026-04", reason: "pagado" }],
      manual_review: [{ month: "2026-03", target_date: "2026-03-10", days_overdue: 90, reason: "older_than_window" }],
      unchanged: [], kept_due_today: [], warnings: [], errors: [],
      summary: { creates: 1, cancels: 1, covered_months: 1, manual_review_months: 1, unchanged_months: 0, affected_charges: 2, previous_amount: 10000, new_amount: 9000, amount_delta: -1000, total_delta: -1000, variation_pct: -10, horizon_start: "2026-03", horizon_end: "2026-05" },
    };
    expect(reconcilePlan(plan).text).toBe("3 meses en el horizonte · 1 cubierto · 1 en revisión manual · 1 cobro nuevo reemplaza a 1 actual");
  });

  it("si los totales del resumen no cuadran con los arreglos, omite la frase de reemplazo y muestra solo lo seguro", () => {
    const plan = bigPlan();
    plan.summary = { ...plan.summary!, creates: 99 };
    const text = reconcilePlan(plan).text!;
    expect(text).toContain("12 meses en el horizonte");
    expect(text).toContain("1 conservado (cobro de hoy)");
    expect(text).not.toContain("reemplaz");
  });

  it("sin resumen ni datos devuelve null", () => {
    expect(reconcilePlan(null).text).toBeNull();
    expect(reconcilePlan({ noop: true, create: [], cancel: [], warnings: [], summary: null }).text).toBeNull();
  });

  it("marca como multiple_pending solo el mes con aviso y mas de un cancel, sin depender del codigo DUP", () => {
    const rows = buildPlanRows(bigPlan());
    const dupMonth = monthOf(3);
    const inDup = rows.filter((r) => r.month === dupMonth);
    expect(inDup.filter((r) => r.kind === "cancelar").every((r) => r.sharedCancels === 2)).toBe(true);
    expect(inDup.filter((r) => r.showMultiplePending)).toHaveLength(1);
    expect(rows.filter((r) => r.month !== dupMonth).some((r) => r.showMultiplePending || r.sharedCancels)).toBe(false);
  });

  it("un aviso multiple_pending con un solo cancel en el mes no etiqueta cobros como adicionales", () => {
    const plan = bigPlan();
    plan.cancel = plan.cancel!.filter((c) => c.charge_id !== "chg-extra");
    const rows = buildPlanRows(plan);
    expect(rows.some((r) => r.sharedCancels)).toBe(false);
    expect(rows.filter((r) => r.showMultiplePending)).toHaveLength(1); // la insignia sigue por el aviso
    expect(reconcilePlan(plan).extraCancels).toBe(0);
  });
});

describe("D1 vista del plan", () => {
  it("muestra la linea de conciliacion bajo los totales y la insignia con texto", () => {
    render(<PlanPreviewView plan={bigPlan()} />);
    const totals = screen.getByLabelText("Totales del plan");
    const line = screen.getByTestId("plan-reconciliation");
    expect(line.textContent).toContain("11 cobros nuevos reemplazan a 12 actuales");
    expect(totals.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const table = screen.getByRole("table", { name: "Plan por mes" });
    expect(within(table).getAllByText("Más de un cobro pendiente")).toHaveLength(1);
    expect(within(table).getAllByText("Uno de 2 cobros pendientes del mes")).toHaveLength(2);
  });

  it("no muestra la linea cuando no hay nada que conciliar", () => {
    render(<PlanPreviewView plan={{ noop: true, create: [], cancel: [], warnings: [], summary: null }} />);
    expect(screen.queryByTestId("plan-reconciliation")).toBeNull();
  });

  it("nunca muestra el message del servidor", () => {
    render(<PlanPreviewView plan={bigPlan()} />);
    expect(screen.queryByText(/texto del servidor/)).toBeNull();
  });
});
