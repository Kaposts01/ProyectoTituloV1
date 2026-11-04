import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findRawEnglish } from "../../i18n/catalog.guard.test";
import { WebhookHealthPanel, type WebhookHealth } from "./WebhookHealthPanel";

const health: WebhookHealth = {
  generated_at: "2026-11-02T12:00:00+00:00",
  processor_enabled: false,
  sources: [
    { source: "toku", counts: { pending: 2, processing: 0, done: 5, failed: 1, ignored: 0 }, last_received_at: "2026-11-02T11:00:00+00:00", pending_lag_minutes: 42.5, done_last_24h: 5, avg_processing_seconds_24h: 3 },
    { source: "payku", counts: { pending: 0, processing: 0, done: 0, failed: 0, ignored: 0 }, last_received_at: null, pending_lag_minutes: null, done_last_24h: 0, avg_processing_seconds_24h: null },
  ],
  error_codes_24h: [{ code: "PROVIDER_READ_FAILED", count: 1 }],
};
const failed = { items: [{ id: "ev-1", source: "toku", event_type: "subscription.updated", status: "failed", attempts: 5, last_error_code: "UNEXPECTED", received_at: "2026-11-02T10:00:00+00:00" }] };

function mockFetch() {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    const body = url.includes("/health") ? health : url.includes("/requeue") ? { requeued: 1 } : failed;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("WebhookHealthPanel", () => {
  it("muestra conteos, demora y motivos en español", async () => {
    mockFetch();
    const { container } = render(<WebhookHealthPanel />);
    expect(await screen.findByText("42.5 min")).toBeTruthy();
    expect(screen.getAllByText("Toku")).toHaveLength(2);
    expect(screen.getByText("Payku")).toBeTruthy();
    expect(screen.getByText(/procesador de la cola está apagado/)).toBeTruthy();
    expect(screen.getByText(/No se pudo leer al proveedor/)).toBeTruthy();
    expect(screen.getByText("Error inesperado")).toBeTruthy();
    expect(findRawEnglish(container)).toEqual([]);
  });

  it("reprocesa un evento por id y todos los fallidos", async () => {
    const calls = mockFetch();
    render(<WebhookHealthPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Reprocesar" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("1 evento"));
    fireEvent.click(screen.getByRole("button", { name: "Reprocesar todos los fallidos" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    const posts = calls.filter((c) => c.method === "POST").map((c) => JSON.parse(c.body ?? "{}"));
    expect(posts).toEqual([{ ids: ["ev-1"] }, { all_failed: true }]);
  });
});
