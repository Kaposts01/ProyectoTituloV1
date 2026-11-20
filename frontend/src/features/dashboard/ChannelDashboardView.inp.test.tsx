/** PERF-03 (INP): el control cambia de inmediato; los gráficos se redibujan después y solo los que dependen del modo. */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChannelDashboard } from "../shared/types";

const log = vi.hoisted(() => ({ renders: [] as { aria: string; mode: string; activeButton: string | null }[] }));
vi.mock("../../components/ChannelChart", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/ChannelChart")>();
  const { memo } = await import("react");
  return {
    ...actual,
    ChannelChart: memo(function ChannelChart(props: { ariaLabel: string; mode: string }) {
      log.renders.push({
        aria: props.ariaLabel,
        mode: props.mode,
        activeButton: document.querySelector(".channel-hero-controls .mode-switch button.active")?.textContent ?? null,
      });
      return null;
    }),
  };
});

import { ChannelDashboardView } from "./ChannelDashboardView";

afterEach(() => { cleanup(); log.renders.length = 0; });

const data: ChannelDashboard = {
  source: "virtualpos", records: 0, resources: {}, resource_amounts: {}, statuses: [], activity_resource: "charge", activity: [], years: [2026],
  last_sync: null,
  charges_monthly: [{ year: 2026, month: 1, status: "PAGADO", count: 3, amount: 3000 }],
  active_subs_monthly: [{ year: 2026, month: 1, count: 5 }],
} as unknown as ChannelDashboard;

const noop = vi.fn();
const view = (mode: "count" | "amount") => (
  <ChannelDashboardView data={data} mode={mode} year={2026} syncing={false} onMode={noop} onYear={noop} onOpenResource={noop} onReport={noop} onSync={noop} />
);

describe("ChannelDashboardView: respuesta del control (INP)", () => {
  it("el botón de modo ya está activo cuando los gráficos se redibujan con el modo nuevo", () => {
    const { rerender } = render(view("count"));
    log.renders.length = 0;
    act(() => { rerender(view("amount")); });
    const amount = log.renders.filter((r) => r.mode === "amount");
    expect(amount.length).toBeGreaterThan(0);
    expect(amount.every((r) => r.activeButton === "Monto")).toBe(true);
  });

  it("solo se redibujan los gráficos que dependen del modo", () => {
    const { rerender } = render(view("count"));
    expect(log.renders.some((r) => r.aria.includes("suscripciones activas"))).toBe(true);
    log.renders.length = 0;
    act(() => { rerender(view("amount")); });
    expect(log.renders.some((r) => r.aria.includes("cargos mensuales"))).toBe(true);
    expect(log.renders.some((r) => r.aria.includes("suscripciones activas"))).toBe(false);
  });

  it("no deja aria-busy una vez aplicado el cambio", () => {
    const { rerender, container } = render(view("count"));
    act(() => { rerender(view("amount")); });
    expect(container.querySelector(".extended-charts")?.getAttribute("aria-busy")).toBeNull();
  });
});
