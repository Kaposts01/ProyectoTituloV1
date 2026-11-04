import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EtlPanel } from "./EtlPanel";
import { resetUnknownWarnings } from "../../i18n/label";
import type { EtlRun } from "../shared/types";

afterEach(cleanup);
beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

const run = (over: Partial<EtlRun> = {}): EtlRun => ({
  id: "r1", status: "completed", phase: null, started_at: "2026-03-01T10:00:00Z", finished_at: "2026-03-01T10:01:00Z",
  records_upserted: 5, channels_processed: null, error_message: null, ...over,
});
const panel = (lastEtlRun: EtlRun | null, etlRunning = false) =>
  render(<EtlPanel etlRunning={etlRunning} lastEtlRun={lastEtlRun} etlError={null} runFullSync={() => {}} />);

describe("EtlPanel: estado y fase de la última corrida en español", () => {
  it.each([["completed", "Completada"], ["failed", "Fallida"], ["running", "En curso"], ["partial", "Parcial"]])("estado %s se ve %s", (status, expected) => {
    panel(run({ status }));
    expect(screen.getByText(expected)).toBeTruthy();
    expect(screen.queryByText(status)).toBeNull();
  });

  it("un estado desconocido se marca", () => {
    panel(run({ status: "zz_nuevo" }));
    expect(screen.getByText("Desconocido (zz_nuevo)")).toBeTruthy();
  });

  it("la fase en curso se ve traducida en la etiqueta y en el botón", () => {
    panel(run({ status: "running", phase: "sync_toku", finished_at: null }), true);
    expect(screen.getAllByText("Sincronización de Toku").length).toBe(1);
    expect(screen.getByRole("button", { name: "Sincronización de Toku…" })).toBeTruthy();
    expect(screen.queryByText(/sync_toku/)).toBeNull();
  });

  it("el mensaje de error de la corrida va crudo, rotulado y marcado como texto del servidor", () => {
    const { container } = panel(run({ status: "failed", error_message: "RuntimeError: connection failed" }));
    expect(screen.getByText(/Texto del proveedor:/)).toBeTruthy();
    expect(container.querySelector("[data-raw-text]")?.textContent).toBe("RuntimeError: connection failed");
  });
});
