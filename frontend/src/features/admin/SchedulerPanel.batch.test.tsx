import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";

vi.mock("../../api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  postForm: vi.fn(),
  friendlyError: (_e: unknown, m: string) => m,
}));
import { getJson, postJson } from "../../api";
import { SchedulerPanel } from "./SchedulerPanel";

const getMock = vi.mocked(getJson);
const postMock = vi.mocked(postJson);
const PROD = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];

class FakeEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
}

const lastRun = (status: string) => ({
  id: `r-${status}`, status, phase: null, started_at: "2026-11-09T05:00:00Z", finished_at: "2026-11-09T05:03:20Z",
  records_upserted: 10, channels_processed: ["toku"], error_message: null,
});
const JOBS = [
  { id: "sync_all_channels", name: "Sincronización diaria de canales", cron: "0 2 * * *", next_run: null, last_run: lastRun("failed"), status: "scheduled", manual_run: true, kind: "sync" },
  { id: "billing_renewal_check", name: "Chequeo de renovación de calendario", cron: "0 3 * * *", next_run: null, last_run: null, status: "scheduled", manual_run: true, kind: "maintenance" },
  { id: "webhook_processor", name: "Procesador de webhooks", cron: "*/30 * * * *", next_run: null, last_run: null, status: "scheduled", manual_run: false, kind: "maintenance" },
];

function mockBackend(jobsAfterRun: () => unknown[]) {
  let started = false;
  getMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/environment")) return { app_env: "x", label: "x", is_production: true, enabled_channels: PROD };
    if (path.includes("/scheduler/runs")) return { total: 0, items: [] };
    if (path.endsWith("/scheduler/jobs")) return started ? jobsAfterRun() : JOBS;
    if (path.endsWith("/sync-runs/health")) {
      return [
        { channel: "toku", level: "warn", last_finished_at: "2026-11-09T05:03:20Z", age_hours: 96, state: "stale" },
        { channel: "payku", level: "error", last_finished_at: "2026-11-12T05:03:20Z", age_hours: 2, state: "failed" },
      ];
    }
    return [];
  });
  postMock.mockImplementation(async (path: string) => {
    started = true;
    return { run_id: path.includes("sync_all") ? "run-sync" : "run-billing" };
  });
}

beforeEach(() => {
  invalidateCache();
  getMock.mockReset();
  postMock.mockReset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("13D: panel de procesos", () => {
  it("cada proceso muestra estado, última corrida, duración y su propio botón; los automáticos lo dicen", async () => {
    mockBackend(() => JOBS);
    render(<SchedulerPanel canSync canViewRuns canImportTch={false} batchPollMs={1} />);
    const syncCard = (await screen.findByText("Sincronización diaria de canales")).closest(".scheduler-job-card") as HTMLElement;
    expect(within(syncCard).getByText("Falló")).toBeTruthy();
    expect(within(syncCard).getByText("3m 20s")).toBeTruthy();
    expect(within(syncCard).getByRole("button", { name: "Sincronizar todos los canales" })).toBeTruthy();
    const billingCard = screen.getByText("Chequeo de renovación de calendario").closest(".scheduler-job-card") as HTMLElement;
    expect(within(billingCard).getByRole("button", { name: "Ejecutar" })).toBeTruthy();
    expect(within(billingCard).getByText("Sin corridas registradas")).toBeTruthy();
    const webhookCard = screen.getByText("Procesador de webhooks").closest(".scheduler-job-card") as HTMLElement;
    expect(within(webhookCard).queryByRole("button")).toBeNull();
    expect(within(webhookCard).getByText(/Solo automático/)).toBeTruthy();
  });

  it("13B: el estado por canal distingue «Atrasada · hace 4 d» de «Falló»", async () => {
    mockBackend(() => JOBS);
    render(<SchedulerPanel canSync canViewRuns canImportTch={false} batchPollMs={1} />);
    const strip = await screen.findByRole("region", { name: "Estado de sincronización por canal" });
    expect(within(strip).getByText("Atrasada · hace 4 d")).toBeTruthy();
    expect(within(strip).getByText("Falló · hace 2 h")).toBeTruthy();
  });

  it("«Ejecutar todos» pide confirmación, lista los procesos y los corre uno tras otro", async () => {
    let polls = 0;
    mockBackend(() => {
      polls += 1;
      // Primer sondeo: la sync sigue en curso; después termina y luego termina el job de facturación.
      if (polls === 1) return [{ ...JOBS[0], status: "running", active_run_id: "run-sync" }, JOBS[1], JOBS[2]];
      return [{ ...JOBS[0], last_run: lastRun("completed") }, { ...JOBS[1], last_run: lastRun("completed") }, JOBS[2]];
    });
    render(<SchedulerPanel canSync canViewRuns canImportTch={false} batchPollMs={1} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ejecutar todos (2)" }));
    const dialog = screen.getByRole("alertdialog", { name: "Confirmar ejecutar todos los procesos" });
    expect(within(dialog).getByText("Sincronización diaria de canales")).toBeTruthy();
    expect(within(dialog).getByText("Chequeo de renovación de calendario")).toBeTruthy();
    expect(within(dialog).getByText("1 proceso solo corre por calendario y no se incluye.")).toBeTruthy();
    expect(postMock).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sí, ejecutar 2 procesos" }));
    const progress = await screen.findByRole("region", { name: "Avance de la ejecución" });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2));
    expect(postMock.mock.calls.map((c) => c[0])).toEqual([
      "/api/v1/scheduler/jobs/sync_all_channels/run",
      "/api/v1/scheduler/jobs/billing_renewal_check/run",
    ]);
    expect(postMock.mock.calls[0][1]).toEqual({ channels: null });
    expect(polls).toBeGreaterThanOrEqual(2); // el segundo se lanzó solo después de ver terminada la sync
    await waitFor(() => expect(within(progress).getAllByText("Completada")).toHaveLength(2));
    expect(within(progress).getByText("Última ejecución manual")).toBeTruthy();
  });

  it("un proceso suelto también confirma y solo lanza ese proceso", async () => {
    mockBackend(() => [JOBS[0], { ...JOBS[1], last_run: lastRun("completed") }, JOBS[2]]);
    render(<SchedulerPanel canSync canViewRuns canImportTch={false} batchPollMs={1} />);
    const billingCard = (await screen.findByText("Chequeo de renovación de calendario")).closest(".scheduler-job-card") as HTMLElement;
    fireEvent.click(within(billingCard).getByRole("button", { name: "Ejecutar" }));
    fireEvent.click(within(billingCard).getByRole("button", { name: "Sí, ejecutar" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock.mock.calls[0]).toEqual(["/api/v1/scheduler/jobs/billing_renewal_check/run", {}]);
  });

  it("sin permiso sync.run no hay botones de ejecución", async () => {
    mockBackend(() => JOBS);
    render(<SchedulerPanel canSync={false} canViewRuns canImportTch={false} batchPollMs={1} />);
    await screen.findByText("Sincronización diaria de canales");
    expect(screen.queryByRole("button", { name: /Ejecutar todos/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ejecutar" })).toBeNull();
  });
});
