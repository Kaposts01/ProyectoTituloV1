import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../../api", async (original) => ({ ...await original<typeof import("../../api")>(), getJson: get }));
import { ApiError } from "../../api";
import { GeneralRecoveryPage } from "./GeneralRecoveryPage";
import { RecoveryPilot } from "./RecoveryPilot";
import { PILOT_PATH, PILOT_PERMISSIONS, canOpenPilot, parsePilotResults } from "./pilotContract";

export function sample(index = 1, extra = {}) {
  return { id: index.toString(16).padStart(64, "0"), source: "tch", purpose: "synthetic", category: null,
    advice: "review_evidence", method: "unmapped", as_of: "2026-11-25T17:00:00+00:00",
    classification_state: "missing", rules_state: "missing", severity: "unknown", matched_rules: [],
    reasons: ["p1_unavailable", "p2_unavailable", "state_links_or_settlement_unverified"], restrictions: ["no_automatic_retry"],
    engine_version: "rejection-engine-v1-draft", policy_version: "rejection-advice-v1-draft",
    rules_version: "reason-rules-v1-draft", taxonomy_version: "reason-taxonomy-v1-draft",
    recovery_probability: null, confidence: null, execution_allowed: false, ...extra };
}
const can = (permission: string) => (PILOT_PERMISSIONS as readonly string[]).includes(permission);
beforeEach(() => { vi.stubEnv("VITE_ML_RECOVERY_PILOT_ENABLED", "false"); get.mockReset(); get.mockResolvedValue([]); });
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("ML-12 contract", () => {
  it("accepts only rules-only TCH fixtures and whitelists returned data", () => {
    const rows = parsePilotResults([sample(1, { personal_name: "MUST NOT DISPLAY" })]);
    expect(rows[0].category).toBeNull(); expect(JSON.stringify(rows)).not.toContain("MUST NOT DISPLAY");
    expect(canOpenPilot(can, "user-a")).toBe(true); expect(canOpenPilot(can)).toBe(false);
    for (const missing of PILOT_PERMISSIONS) expect(canOpenPilot((p) => p !== missing && can(p), "user-a")).toBe(false);
  });
  it.each([{ source: "virtualpos1" }, { purpose: "reviewed-real" }, { recovery_probability: 0.8 }, { confidence: 1 },
    { execution_allowed: true }, { method: "simulated_p1" }, { restrictions: [] }, { as_of: "2026-11-25" },
    { category: "UNKNOWN" }, { advice: "retry_now" }, { rules_version: "new-version" }, { reasons: ["secret name"] }])("rejects incompatible data %j", (change) => {
    expect(() => parsePilotResults([sample(1, change)])).toThrow();
  });
  it("rejects duplicates, unknown structures and excessive pages", () => {
    for (const bad of [null, {}, [sample(), sample()], Array.from({ length: 11 }, (_, i) => sample(i+1))]) expect(() => parsePilotResults(bad)).toThrow();
  });
});

describe("ML-12 read-only flow", () => {
  it("shows unknown probability, explains limits and returns focus to the case", async () => {
    get.mockResolvedValue([sample()]); render(<RecoveryPilot />);
    expect(screen.getByRole("status")).toHaveTextContent("Cargando");
    const button = await screen.findByRole("button", { name: "Revisar caso de prueba 1" });
    fireEvent.click(button);
    expect(screen.getByRole("heading", { name: "Revisar los antecedentes" })).toHaveFocus();
    expect(screen.getByText("No disponible: aún no hay un modelo validado.")).toBeVisible();
    expect(screen.getByText(/no registra aprobaciones/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /cobrar|aprobar|reintentar/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Volver a los casos" })); expect(button).toHaveFocus();
    expect(get).toHaveBeenCalledWith(`${PILOT_PATH}?limit=10&offset=0`, expect.any(AbortSignal));
  });
  it("labels security as a signal, never as proof of fraud", async () => {
    get.mockResolvedValue([sample(1, { category: "FRAUD", advice: "review_security_signal", method: "rule", classification_state: "classified", rules_state: "classified", matched_rules: ["tch:phrase:security_signal"] })]);
    render(<RecoveryPilot />); fireEvent.click(await screen.findByRole("button", { name: "Revisar caso de prueba 1" }));
    expect(screen.getByText(/No demuestra fraude/)).toBeVisible();
  });
  it("distinguishes empty fixture data from absence of real rejections", async () => {
    render(<RecoveryPilot />); expect(await screen.findByRole("heading", { name: "Sin casos de prueba en esta página" })).toBeVisible();
    expect(screen.getByText(/No significa que no existan rechazos reales/)).toBeVisible();
  });
  it.each([[401, null, /Tu sesión terminó/], [403, null, /No tienes acceso/], [503, "ml_api_disabled", /no está habilitado/], [503, "ml_synthetic_only", /no está habilitado/]] as const)("handles unavailable access %s/%s", async (status, code, message) => {
    get.mockRejectedValue(new ApiError("DO NOT ECHO SERVER MESSAGE", status, { code })); render(<RecoveryPilot />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message); expect(screen.queryByText("DO NOT ECHO SERVER MESSAGE")).toBeNull();
    expect(screen.queryByRole("button", { name: "Volver a cargar casos" })).toBeNull();
  });
  it("recovers from network or invalid data without keeping stale rows", async () => {
    get.mockRejectedValueOnce(new TypeError("fetch failed")).mockResolvedValueOnce([sample()]).mockResolvedValueOnce([sample(1, { purpose: "real" })]);
    render(<RecoveryPilot />); await screen.findByRole("alert"); fireEvent.click(screen.getByRole("button", { name: "Volver a cargar casos" }));
    await screen.findByRole("button", { name: "Revisar caso de prueba 1" }); fireEvent.click(screen.getByRole("button", { name: "Actualizar casos" }));
    expect(await screen.findByRole("alert")).toBeVisible(); expect(screen.queryByRole("button", { name: "Revisar caso de prueba 1" })).toBeNull();
  });
  it("paginates bounded pages and never exposes the raw digest", async () => {
    get.mockResolvedValueOnce(Array.from({ length: 10 }, (_, i) => sample(i+1))).mockResolvedValueOnce([sample(11)]);
    render(<RecoveryPilot />); await screen.findByRole("button", { name: "Revisar caso de prueba 10" });
    expect(screen.queryByText(sample().id)).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    await screen.findByRole("button", { name: "Revisar caso de prueba 11" });
    expect(get).toHaveBeenLastCalledWith(`${PILOT_PATH}?limit=10&offset=10`, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Página siguiente" })).toBeDisabled();
  });
});

describe("ML-12 Recuperador integration", () => {
  it("is hidden and performs no ML request with flag off or any missing permission", () => {
    const { rerender } = render(<GeneralRecoveryPage can={can} owner="a" />);
    expect(screen.queryByRole("button", { name: "Ver piloto con datos de prueba" })).toBeNull();
    vi.stubEnv("VITE_ML_RECOVERY_PILOT_ENABLED", "true");
    for (const missing of PILOT_PERMISSIONS) {
      rerender(<GeneralRecoveryPage can={(p) => can(p) && p !== missing} owner="a" />);
      expect(screen.queryByRole("button", { name: "Ver piloto con datos de prueba" })).toBeNull();
    }
    expect(get).not.toHaveBeenCalled();
  });
  it("separates the operational view and aborts late data after permission loss", async () => {
    vi.stubEnv("VITE_ML_RECOVERY_PILOT_ENABLED", "true");
    let finish!: (value: unknown) => void;
    get.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { rerender } = render(<GeneralRecoveryPage can={can} owner="a" />);
    fireEvent.click(screen.getByRole("button", { name: "Ver piloto con datos de prueba" }));
    expect(screen.queryByRole("button", { name: "Buscar" })).toBeNull();
    const signal = get.mock.calls[0][1] as AbortSignal;
    rerender(<GeneralRecoveryPage can={(p) => can(p) && p !== "ml.tch.access"} owner="a" />);
    expect(signal.aborted).toBe(true); finish([sample()]);
    await waitFor(() => expect(screen.queryByText("Caso de prueba 1")).toBeNull());
  });
  it("drops the previous session's pending response when owner changes", async () => {
    vi.stubEnv("VITE_ML_RECOVERY_PILOT_ENABLED", "true");
    let finish!: (value: unknown) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; })).mockResolvedValueOnce([]);
    const { rerender } = render(<GeneralRecoveryPage can={can} owner="a" />);
    fireEvent.click(screen.getByRole("button", { name: "Ver piloto con datos de prueba" }));
    const signal = get.mock.calls[0][1] as AbortSignal;
    rerender(<GeneralRecoveryPage can={can} owner="b" />);
    expect(signal.aborted).toBe(true);
    await screen.findByRole("heading", { name: "Sin casos de prueba en esta página" });
    finish([sample()]);
    await waitFor(() => expect(screen.queryByText("Caso de prueba 1")).toBeNull());
  });
});
