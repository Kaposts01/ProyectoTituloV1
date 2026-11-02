import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJson = vi.fn();
vi.mock("../../api", () => ({
  getJson: (path: string) => getJson(path),
  postJson: vi.fn(),
  downloadFile: vi.fn(),
  friendlyError: (_e: unknown, f: string) => f,
}));

import { legacyRedirectPath, parseRoute, routePath } from "../../routes";
import { canOpenBilling, visibleMenu } from "../../navigation";
import { channelListPath, CHANNEL_RECOVERY, EMPTY_CHANNEL_FILTERS } from "./channelRecoveryViews";
import { GeneralRecoveryPage } from "./GeneralRecoveryPage";
import { canOpenRecovery, visibleRecoveryTabs } from "./recoveryChannels";

const only = (...perms: string[]) => (p: string) => perms.includes(p);
const tabNames = () => screen.queryAllByRole("tab").filter((tab) => tab.closest('[aria-label="Canal"]')).map((tab) => tab.textContent);

afterEach(cleanup);

beforeEach(() => {
  getJson.mockReset();
  getJson.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/recovery/toku/recoverable")) return { items: [], total: 0, offset: 0, limit: 50, empty_reason: "signals_disabled" };
    return { items: [], total: 0, offset: 0, limit: 50, empty_reason: null };
  });
});

describe("rutas y menú (UX-12)", () => {
  it("/general/recuperador es la ruta canónica y la antigua redirige", () => {
    expect(parseRoute("/general/recuperador")).toEqual({ kind: "recovery" });
    expect(routePath({ kind: "recovery" })).toBe("/general/recuperador");
    expect(legacyRedirectPath("/virtualpos/recuperador-socios")).toBe("/general/recuperador");
    expect(legacyRedirectPath("/general/recuperador")).toBeNull();
  });

  it("el Recuperador aparece en Operación con el permiso general o el de cualquier pestaña", () => {
    const labels = (can: (p: string) => boolean) => visibleMenu(can).flatMap((g) => g.items.map((i) => i.label));
    expect(labels(only("general.recovery.view"))).toEqual(["Recuperador"]);
    expect(labels(only("general.recovery.toku.view"))).toEqual(["Recuperador"]);
    expect(labels(only("general.recovery.tch.view"))).toEqual(["Recuperador"]);
    expect(labels(only("virtualpos.recovery.view"))).toEqual(["Recuperador"]);
    // Cambio deliberado (UX-08): con un permiso de vista de suscripciones aparece Suscripciones (Cartera), no el Recuperador.
    expect(labels(only("toku.subscriptions.view"))).toEqual(["Suscripciones"]);
    expect(canOpenRecovery(only())).toBe(false);
  });

  it("Cambios de cobro acepta el permiso general o el de VirtualPOS", () => {
    expect(canOpenBilling(only("general.billing_changes.view"))).toBe(true);
    expect(canOpenBilling(only("virtualpos.billing_changes.view"))).toBe(true);
    expect(canOpenBilling(only("general.recovery.view"))).toBe(false);
    expect(visibleMenu(only("general.billing_changes.view")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Cambios de cobro"]);
  });

  it("cada pestaña depende solo de su permiso", () => {
    expect(visibleRecoveryTabs(only("general.recovery.toku.view")).map((t) => t.id)).toEqual(["toku"]);
    expect(visibleRecoveryTabs(only("general.recovery.view")).map((t) => t.id)).toEqual([]);
    expect(visibleRecoveryTabs(only("virtualpos.recovery.view", "general.recovery.tch.view")).map((t) => t.id)).toEqual(["virtualpos", "tch"]);
  });
});

describe("GeneralRecoveryPage (RBAC por pestaña)", () => {
  it("un usuario sin permiso de Toku no ve la pestaña ni llama a su API", async () => {
    render(<GeneralRecoveryPage can={only("general.recovery.view", "general.recovery.tch.view")} />);
    expect(tabNames()).toEqual(["TCH"]);
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await screen.findByText("Sin registros para los filtros seleccionados.");
    expect(getJson.mock.calls.map(([path]) => path).every((path: string) => path.startsWith("/api/v1/recovery/tch/"))).toBe(true);
    expect(screen.getByText(/TCH se carga desde el Excel/)).toBeTruthy();
  });

  it("sin ninguna pestaña permitida muestra un aviso explícito", () => {
    render(<GeneralRecoveryPage can={only("general.recovery.view")} />);
    expect(tabNames()).toEqual([]);
    expect(screen.getByText(/No tienes permiso para ver ninguna pestaña/)).toBeTruthy();
  });

  it("Toku: Recuperables con la bandera de señales apagada muestra el estado vacío explícito", async () => {
    render(<GeneralRecoveryPage can={only("general.recovery.view", "general.recovery.toku.view")} />);
    expect(tabNames()).toEqual(["Toku"]);
    fireEvent.click(screen.getByRole("tab", { name: "Recuperables" }));
    expect(screen.getByText(/pulsa «Buscar»/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByText(/señales de Toku están desactivadas/)).toBeTruthy();
    expect(getJson).toHaveBeenLastCalledWith("/api/v1/recovery/toku/recoverable?offset=0&limit=50");
  });

  it("Toku: filas de cobros rechazados con estado traducido y montos en mono", async () => {
    getJson.mockResolvedValueOnce({
      items: [{ charge_id: "in_1", subscription_id: "sub_1", period: "2026-09", amount: 5000, currency: "CLP", status: "UNPAID", rejection_code: "1001", rejection_reason: "Fondos insuficientes", rejection_at: "2026-09-05" }],
      total: 1, offset: 0, limit: 50, empty_reason: null,
    });
    render(<GeneralRecoveryPage can={only("general.recovery.toku.view")} />);
    fireEvent.click(screen.getByRole("tab", { name: "Cobros rechazados" }));
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    const row = (await screen.findByText("in_1")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Impago")).toBeTruthy();
    expect(within(row).getByText("$5.000").className).toContain("mono");
    expect(within(row).getByText("Fondos insuficientes")).toBeTruthy();
  });
});

describe("channelListPath", () => {
  it("solo envía los filtros que acepta la vista", () => {
    const [cancelled, , recoverable] = CHANNEL_RECOVERY.toku.views;
    const filters = { ...EMPTY_CHANNEL_FILTERS, dateFrom: "2026-01-01", reason: "streak" };
    expect(channelListPath(cancelled, filters, 0, 50)).toBe("/api/v1/recovery/toku/cancelled?date_from=2026-01-01&offset=0&limit=50");
    expect(channelListPath(recoverable, filters, 50, 50)).toBe("/api/v1/recovery/toku/recoverable?reason=streak&offset=50&limit=50");
  });
});
