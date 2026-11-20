/** PERF-03f: el dashboard de canal no se repinta (ni recalcula gráficos) cuando el padre cambia por otra causa. */
import { act, cleanup, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChannelDashboard } from "../shared/types";

const chartRenders = vi.hoisted(() => ({ count: 0 }));
vi.mock("../../components/ChannelChart", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/ChannelChart")>();
  const { memo } = await import("react");
  return { ...actual, ChannelChart: memo(function ChannelChart() { chartRenders.count += 1; return null; }) };
});

import { ChannelDashboardView } from "./ChannelDashboardView";

afterEach(cleanup);

const data: ChannelDashboard = {
  source: "virtualpos", records: 0, resources: {}, resource_amounts: {}, statuses: [], activity_resource: "charge", activity: [], years: [2026], last_sync: null,
  charges_monthly: [{ year: 2026, month: 1, status: "PAGADO", count: 3, amount: 3000 }],
};

describe("ChannelDashboardView con memo", () => {
  it("un re-render del padre con las mismas props no repinta los gráficos", () => {
    const noop = vi.fn();
    let bump: () => void = () => undefined;
    function Parent() {
      const [, setN] = useState(0);
      bump = () => setN((n) => n + 1);
      return <ChannelDashboardView data={data} mode="count" year={2026} syncing={false} onMode={noop} onYear={noop} onOpenResource={noop} onReport={noop} onSync={noop} />;
    }
    render(<Parent />);
    const first = chartRenders.count;
    expect(first).toBeGreaterThan(0);
    act(() => bump());
    act(() => bump());
    expect(chartRenders.count).toBe(first);
  });
});
