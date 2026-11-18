import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SummaryActions } from "./SummaryActions";
import { adaptSummary } from "./summaryAdapter";
import { rawKpi, rawSummary } from "./summaryFixtures";

afterEach(cleanup);
describe("Alertas que orientan", () => {
  it("distingue falta de actualización, progreso y calidad, y solo abre una vista de revisión", () => {
    const summary = adaptSummary(rawSummary({ calidad_datos: { altas_sin_fecha: 2, bajas_sin_fecha: 1 } }));
    const open = vi.fn(), detail = vi.fn();
    render(<SummaryActions summary={summary} healthReady health={{ virtualpos: { channel: "virtualpos", level: "error", state: "failed", last_finished_at: null, age_hours: 30 },
      toku: { channel: "toku", level: "ok", state: "running", last_finished_at: null, age_hours: null } }}
      can={(p) => p === "sync_runs.view"} onOpenPath={open} onDetail={detail} />);
    expect(screen.getByText("Hay una actualización en curso")).toBeTruthy();
    expect(screen.getByText(/2 suscripciones sin fecha de alta válida/)).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Revisar sincronización" }));
    expect(open).toHaveBeenCalledExactlyOnceWith("/admin/sincronizaciones");
    fireEvent.click(screen.getByRole("button", { name: "Revisar no cobrado" }));
    expect(detail).toHaveBeenCalledWith("uncollected", expect.any(HTMLButtonElement));
    expect(screen.queryByRole("button", { name: /Sincronizar ahora|Cobrar|Reintentar cobro/ })).toBeNull();
  });
  it("no inventa fallos mientras carga salud, ni alertas monetarias por cero o dato ausente", () => {
    const raw = rawSummary(); raw.kpis.no_cobrado = rawKpi(null, null, "clp");
    const view = render(<SummaryActions summary={adaptSummary(raw)} health={{}} healthReady={false} can={() => false} onDetail={vi.fn()} />);
    expect(screen.queryByRole("region")).toBeNull();
    raw.kpis.no_cobrado = rawKpi(0, 0, "clp");
    view.rerender(<SummaryActions summary={adaptSummary(raw)} health={{}} healthReady can={() => false} onDetail={vi.fn()} />);
    expect(screen.getByText(/sin información de actualización/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Revisar no cobrado" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Revisar sincronización" })).toBeNull();
    expect(screen.getByText(/Pide a un administrador/)).toBeTruthy();
  });
});
