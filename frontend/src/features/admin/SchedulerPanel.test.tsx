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
