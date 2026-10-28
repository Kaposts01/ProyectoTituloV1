import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";

vi.mock("../../api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  postForm: vi.fn(),
  friendlyError: (_e: unknown, m: string) => m,
}));
import { getJson } from "../../api";
import { SchedulerPanel, getPhasesForChannels, syncPayloadChannels, vpSubOptions } from "./SchedulerPanel";

const mocked = vi.mocked(getJson);
const PROD = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];
const SANDBOX = ["virtualpos1", "toku", "tch"];

function mockEnv(enabled: string[]) {
  mocked.mockImplementation(async (path: string) => {
    if (path.endsWith("/environment")) return { app_env: "x", label: "x", is_production: enabled.length === 5, enabled_channels: enabled };
    if (path.includes("/runs")) return { total: 0, items: [] };
    return [];
  });
}
beforeEach(() => { invalidateCache(); mocked.mockReset(); });
afterEach(() => cleanup());

describe("SchedulerPanel helpers", () => {
  it("fases en produccion vs sandbox", () => {
    expect(getPhasesForChannels(null, PROD)).toEqual(["sync_virtualpos1", "sync_virtualpos2", "sync_toku", "sync_payku", "consolidating"]);
    expect(getPhasesForChannels(null, SANDBOX)).toEqual(["sync_virtualpos1", "sync_toku", "consolidating"]);
    expect(getPhasesForChannels(["virtualpos1", "virtualpos2", "payku"], SANDBOX)).toEqual(["sync_virtualpos1", "consolidating"]);
  });
  it("presets VP", () => {
    expect(vpSubOptions(PROD).map((o) => o.label)).toEqual(["VP1 + VP2", "Solo VP1", "Solo VP2"]);
    expect(vpSubOptions(SANDBOX).map((o) => o.label)).toEqual(["VP1"]);
  });
  it("payload solo con canales habilitados", () => {
    expect(syncPayloadChannels(null, PROD)).toBeNull();
    expect(syncPayloadChannels(null, SANDBOX)).toEqual(["virtualpos1", "toku"]);
    expect(syncPayloadChannels(["virtualpos1", "virtualpos2"], SANDBOX)).toEqual(["virtualpos1"]);
  });
});

describe("SchedulerPanel render", () => {
  it("sandbox: Payku deshabilitado con title y VP muestra solo VP1", async () => {
    mockEnv(SANDBOX);
    render(<SchedulerPanel canSync canViewRuns canImportTch />);
    const payku = await screen.findByRole("button", { name: "Payku" });
    await waitFor(() => expect(payku).toBeDisabled());
    expect(payku).toHaveAttribute("title", "No disponible en este ambiente");
    expect(screen.getByRole("button", { name: "Toku" })).not.toBeDisabled();
  });
  it("produccion: Payku habilitado", async () => {
    mockEnv(PROD);
    render(<SchedulerPanel canSync canViewRuns canImportTch />);
    const payku = await screen.findByRole("button", { name: "Payku" });
    expect(payku).not.toBeDisabled();
  });
});

describe("SchedulerPanel: estados y jobs de facturacion", () => {
  const run = (over: Record<string, unknown>) => ({ id: "x", status: "completed", phase: null, started_at: "2026-03-01T10:00:00Z", finished_at: "2026-03-01T10:01:00Z", records_upserted: 5, channels_processed: ["virtualpos1"], error_message: null, ...over });
  function mockData(jobs: unknown[], runs: unknown[]) {
    mocked.mockImplementation(async (path: string) => {
      if (path.endsWith("/environment")) return { app_env: "x", label: "x", is_production: true, enabled_channels: PROD };
      if (path.includes("/scheduler/runs")) return { total: runs.length, items: runs };
      if (path.endsWith("/scheduler/jobs")) return jobs;
      return [];
    });
  }
  it("estado partial se muestra como 'Parcial' con badge de advertencia", async () => {
    mockData([], [run({ id: "r1", status: "partial" }), run({ id: "r2", status: "completed" })]);
    render(<SchedulerPanel canSync canViewRuns canImportTch />);
    const badge = await screen.findByText("Parcial");
    expect(badge.className).toContain("badge-orange");
    expect(screen.getByText("OK").className).toContain("badge-green");
  });
  it("el job billing_sweep_applying se lista con su nombre legible y su frecuencia", async () => {
    mockData([
      { id: "billing_sweep_applying", name: "Barrido de solicitudes atascadas en 'aplicando'", cron: "5,20,35,50 * * * *", next_run: "2026-03-01T10:05:00Z", last_run: null, status: "scheduled" },
      { id: "billing_renewal_check", name: "Chequeo de renovación de calendario", cron: "0 3 * * *", next_run: null, last_run: null, status: "scheduled" },
    ], []);
    render(<SchedulerPanel canSync canViewRuns canImportTch />);
    expect(await screen.findByText("Barrido de solicitudes atascadas en 'aplicando'")).toBeTruthy();
    expect(screen.getByText("Cada 15 min (minutos 5, 20, 35 y 50)")).toBeTruthy();
    expect(screen.getByText("Diario a las 03:00 (Santiago)")).toBeTruthy();
  });
});
