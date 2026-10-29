/**
 * Paso 7 de la traducción: estado de la última carga y recursos de cada canal en el dashboard general.
 * Datos sintéticos.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appReady, mountApp, resetApp } from "./appHarness";
import { resetUnknownWarnings } from "../i18n/label";

afterEach(resetApp);
beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

const general = {
  clients: 10,
  subscriptions: { active: 9, amount: 9000 },
  transactions: { total: 5, accepted: 4, rejected: 1, amount: 4500, rejection_rate_pct: 20, basis_label: null },
  channels: [{ source: "VirtualPOS", clients: 8, active_subscriptions: 6, accepted: 3, amount: 3000 }],
  years: [2025], transactions_monthly: [], activations_monthly: [], cancellations_monthly: [], debts_monthly: [], transactions_effective_monthly: [],
  alerts: [], pending_payments: 0, sync_success_rate_pct: 100, churn_rate_pct: 0,
};
const staging = (status: string, resources: Record<string, number>) => ({
  sources: [{ source: "virtualpos", records: 1000, resources, last_sync: { status, records_processed: 1000, finished_at: "2025-03-31T10:00:00" } }],
});
const handlers = (status: string, resources: Record<string, number>) => [
  ["GET", "/api/v1/staging/summary", staging(status, resources)],
  ["GET", "/api/v1/staging/dashboard/general", general],
] as never;

describe("Dashboard general: tarjetas por canal en español", () => {
  it("estado de la última carga y recursos traducidos", async () => {
    mountApp("/central/resumen-clasico", handlers("completed", { client: 500, subscription: 300, payment_method: 2 }));
    await appReady();
    const card = (await screen.findByText("6 suscripciones vigentes")).closest("article")!;
    expect(within(card).getByText("VIRTUALPOS")).toBeTruthy();
    expect(within(card).getByText("Completada")).toBeTruthy();
    expect(within(card).getByText("Clientes: 500 · Suscripciones: 300 · Métodos de pago: 2")).toBeTruthy();
    expect(within(card).queryByText("completed")).toBeNull();
  });

  it("estado fallido y estado o recurso desconocido", async () => {
    mountApp("/central/resumen-clasico", handlers("failed", { client: 1, recurso_nuevo: 2 }));
    await appReady();
    const card = (await screen.findByText("6 suscripciones vigentes")).closest("article")!;
    expect(within(card).getByText("Fallida")).toBeTruthy();
    expect(within(card).getByText("Clientes: 1 · Desconocido (recurso_nuevo): 2")).toBeTruthy();
  });
});
