import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJson = vi.fn();
vi.mock("../../api", () => ({
  getJson: (path: string) => getJson(path),
  postJson: vi.fn(),
  downloadFile: vi.fn(),
  friendlyError: (_e: unknown, f: string) => f,
}));

import { visibleMenu } from "../../navigation";
import { CHANNEL_RECOVERY, PAYKU_COVERAGE_WARNING, channelListPath, EMPTY_CHANNEL_FILTERS } from "./channelRecoveryViews";
import { GeneralRecoveryPage } from "./GeneralRecoveryPage";
import { PERM_RECOVERY_PAYKU, visibleRecoveryTabs } from "./recoveryChannels";

const only = (...perms: string[]) => (p: string) => perms.includes(p);
const tabNames = () => screen.queryAllByRole("tab").filter((tab) => tab.closest('[aria-label="Canal"]')).map((tab) => tab.textContent);

afterEach(cleanup);

beforeEach(() => {
  getJson.mockReset();
  getJson.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, empty_reason: null });
});

describe("Recuperador general: pestaña Payku (REC-05)", () => {
  it("la pestaña depende solo de su permiso y abre el menú", () => {
    expect(PERM_RECOVERY_PAYKU).toBe("general.recovery.payku.view");
    expect(visibleRecoveryTabs(only(PERM_RECOVERY_PAYKU)).map((t) => t.id)).toEqual(["payku"]);
    expect(visibleRecoveryTabs(only("payku.subscriptions.view", "general.recovery.view")).map((t) => t.id)).toEqual([]);
    expect(visibleMenu(only(PERM_RECOVERY_PAYKU)).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Recuperador"]);
  });

  it("sin el permiso de Payku no aparece la pestaña", () => {
    render(<GeneralRecoveryPage can={only("general.recovery.view", "general.recovery.toku.view", "general.recovery.tch.view")} />);
    expect(tabNames()).toEqual(["Toku", "TCH"]);
  });

  it("muestra el aviso de cobertura limitada y solo llama a la API de Payku", async () => {
    render(<GeneralRecoveryPage can={only("general.recovery.view", PERM_RECOVERY_PAYKU)} />);
    expect(tabNames()).toEqual(["Payku"]);
    expect(screen.getByRole("note").textContent).toBe(PAYKU_COVERAGE_WARNING);
    expect(PAYKU_COVERAGE_WARNING).toContain("Payku sin sandbox; validar después (DEC-10)");
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await screen.findByText("Sin registros para los filtros seleccionados.");
    expect(getJson).toHaveBeenLastCalledWith("/api/v1/recovery/payku/cancelled?offset=0&limit=50");
    expect(getJson.mock.calls.every(([path]) => String(path).startsWith("/api/v1/recovery/payku/"))).toBe(true);
  });

  it("cobros rechazados: estado crudo traducido, período y monto en mono", async () => {
    getJson.mockResolvedValueOnce({
      items: [{ charge_id: "rej-1", subscription_id: "su-1", period: "2095-02", charge_date: "2095-02-10", amount: 5000, currency: "CLP", status: "rejected", rejection_reason: "Se agotaron los reintentos de cobro" }],
      total: 1, offset: 0, limit: 50, empty_reason: null,
    });
    render(<GeneralRecoveryPage can={only(PERM_RECOVERY_PAYKU)} />);
    fireEvent.click(screen.getByRole("tab", { name: "Cobros rechazados" }));
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    const row = (await screen.findByText("rej-1")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Rechazado")).toBeTruthy();
    expect(within(row).getByText("2095-02")).toBeTruthy();
    expect(within(row).getByText("$5.000").className).toContain("mono");
    expect(within(row).getByText("Se agotaron los reintentos de cobro")).toBeTruthy();
  });

  it("suspendidas: estados crudos de Payku con etiqueta en español", async () => {
    getJson.mockResolvedValueOnce({
      items: [{ subscription_id: "su-2", status: "suspended", started_at: "2095-01-01", cancelled_at: "2095-04-01", antiquity_days: 90, amount: 5000, currency: "CLP", last_payment_status: "maximum attempt limit" }],
      total: 1, offset: 0, limit: 50, empty_reason: null,
    });
    render(<GeneralRecoveryPage can={only(PERM_RECOVERY_PAYKU)} />);
    fireEvent.click(screen.getByRole("tab", { name: "Suspendidas" }));
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    const row = (await screen.findByText("su-2")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Suspendida")).toBeTruthy();
    expect(within(row).getByText("Reintentos agotados")).toBeTruthy();
  });

  it("las vistas filtran por fecha y no envían el motivo", () => {
    const filters = { ...EMPTY_CHANNEL_FILTERS, dateFrom: "2095-01-01", dateTo: "2095-12-31", reason: "streak" };
    expect(CHANNEL_RECOVERY.payku.views.map((v) => v.id)).toEqual(["cancelled", "suspended", "rejected"]);
    expect(channelListPath(CHANNEL_RECOVERY.payku.views[1], filters, 0, 50))
      .toBe("/api/v1/recovery/payku/suspended?date_from=2095-01-01&date_to=2095-12-31&offset=0&limit=50");
  });
});
