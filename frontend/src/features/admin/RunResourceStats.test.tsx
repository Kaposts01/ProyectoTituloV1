import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";

vi.mock("../../api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  postForm: vi.fn(),
  friendlyError: (_e: unknown, m: string) => m,
}));
import { getJson } from "../../api";
import { RunResourceStats } from "./RunResourceStats";
import { SchedulerPanel } from "./SchedulerPanel";

const mocked = vi.mocked(getJson);
const PROD = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];
const STATS = [
  {
    id: "s1", source: "toku", status: "completed", duration_seconds: 12.5,
    resource_stats: { transaction: { mode: "window", inserted: 1200, updated: 3, unchanged: 40, seconds: 9.25 } },
  },
];

beforeEach(() => { invalidateCache(); mocked.mockReset(); });
afterEach(() => cleanup());

describe("RunResourceStats", () => {
  it("muestra modo de lectura y conteos por recurso", async () => {
    mocked.mockResolvedValue(STATS);
    render(<RunResourceStats etlRunId="run-1" />);
    expect(await screen.findByText("Transacciones")).toBeTruthy();
    expect(screen.getByText("Ventana")).toBeTruthy();
    expect(screen.getByText((1200).toLocaleString("es-CL"))).toBeTruthy();
    expect(mocked).toHaveBeenCalledWith("/api/v1/sync-runs?etl_run_id=run-1");
  });

  it("sin estadisticas lo dice", async () => {
    mocked.mockResolvedValue([{ ...STATS[0], resource_stats: null }]);
    render(<RunResourceStats etlRunId="run-2" />);
    expect(await screen.findByText("Sin detalle por recurso para esta ejecución.")).toBeTruthy();
  });

  it("el historial abre el detalle de una ejecucion terminada", async () => {
    mocked.mockImplementation(async (path: string) => {
      if (path.endsWith("/environment")) return { app_env: "x", label: "x", is_production: true, enabled_channels: PROD };
      if (path.includes("/scheduler/runs")) {
        return { total: 1, items: [{ id: "etl-9", status: "completed", phase: null, started_at: "2026-03-01T10:00:00Z", finished_at: "2026-03-01T10:01:00Z", records_upserted: 5, channels_processed: ["toku"], error_message: null }] };
      }
      if (path.startsWith("/api/v1/sync-runs?etl_run_id=")) return STATS;
      return [];
    });
    render(<SchedulerPanel canSync={false} canViewRuns canImportTch={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Detalle" }));
    expect(await screen.findByText("Transacciones")).toBeTruthy();
    expect(mocked).toHaveBeenCalledWith("/api/v1/sync-runs?etl_run_id=etl-9");
  });
});
