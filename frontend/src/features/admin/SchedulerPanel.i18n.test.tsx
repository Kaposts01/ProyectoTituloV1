import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";
import { resetUnknownWarnings } from "../../i18n/label";

vi.mock("../../api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  postForm: vi.fn(),
  friendlyError: (_e: unknown, m: string) => m,
}));
import { getJson } from "../../api";
import { SchedulerPanel } from "./SchedulerPanel";
import { phaseText, runTypeLabel } from "./schedulerLabels";
import { SseLogEntry } from "./SseLogEntry";

const mocked = vi.mocked(getJson);
const PROD = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];

beforeEach(() => {
  invalidateCache();
  mocked.mockReset();
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => cleanup());

const run = (over: Record<string, unknown>) => ({ id: "x", status: "completed", phase: null, started_at: "2026-03-01T10:00:00Z", finished_at: "2026-03-01T10:01:00Z", records_upserted: 5, channels_processed: ["virtualpos1"], error_message: null, ...over });
function mockData(jobs: unknown[], runs: unknown[]) {
  mocked.mockImplementation(async (path: string) => {
    if (path.endsWith("/environment")) return { app_env: "x", label: "x", is_production: true, enabled_channels: PROD };
    if (path.includes("/scheduler/runs")) return { total: runs.length, items: runs };
    if (path.endsWith("/scheduler/jobs")) return jobs;
    return [];
  });
}

describe("SchedulerPanel: estados de corrida en español", () => {
  it("los estados sin texto propio pasan por el catálogo y los desconocidos se marcan", async () => {
    mockData(
      [{ id: "j1", name: "Trabajo sintético", cron: "0 3 * * *", next_run: null, last_run: null, status: "scheduled" }],
      [run({ id: "r1", status: "queued" }), run({ id: "r2", status: "cancelled" }), run({ id: "r3", status: "zz_nuevo" })],
    );
    render(<SchedulerPanel canSync canViewRuns canImportTch />);
    expect(await screen.findByText("En cola")).toBeTruthy();
    expect(screen.getByText("Cancelada")).toBeTruthy();
    expect(screen.getByText("Desconocido (zz_nuevo)")).toBeTruthy();
    expect(screen.getByText("Programado")).toBeTruthy();
    expect(screen.queryByText("scheduled")).toBeNull();
    expect(screen.queryByText("queued")).toBeNull();
  });
});

describe("SchedulerPanel: fases y tipos de corrida", () => {
  it("phaseText usa el texto propio del panel y cae al catálogo", () => {
    expect(phaseText("sync_toku")).toBe("Toku");
    expect(phaseText("consolidating")).toBe("Consolidación centralizada");
    expect(phaseText("capture_vp_rejections")).toBe("Captura de rechazos de VirtualPOS");
    expect(phaseText("fase_nueva")).toBe("Desconocido (fase_nueva)");
  });

  it("runTypeLabel traduce un canal desconocido en vez de mostrarlo crudo", () => {
    expect(runTypeLabel(["toku", "payku"], PROD)).toBe("Toku + Payku");
    expect(runTypeLabel(["canal_nuevo"], PROD)).toBe("Desconocido (canal_nuevo)");
  });
});

describe("SseLogEntry: línea del registro en vivo", () => {
  it("traduce fase y recurso; el mensaje libre va crudo, rotulado y marcado como texto del proveedor", () => {
    const { container } = render(<SseLogEntry event={{ type: "progress", phase: "sync_toku", resource: "subscription", pct: 40, records: 1200, msg: "fetched 1200 rows failed once" }} />);
    expect(container.textContent).toBe("[Toku] Suscripciones 40% (1.200) — Texto del proveedor: fetched 1200 rows failed once");
    const raw = container.querySelector("[data-raw-text]");
    expect(raw?.textContent).toBe("fetched 1200 rows failed once");
  });

  it("sin mensaje no agrega el rótulo; una fase desconocida se marca", () => {
    const { container } = render(<SseLogEntry event={{ type: "error", phase: "fase_nueva" }} />);
    expect(container.textContent).toBe("[Desconocido (fase_nueva)]");
    expect(container.querySelector("[data-raw-text]")).toBeNull();
  });
});
