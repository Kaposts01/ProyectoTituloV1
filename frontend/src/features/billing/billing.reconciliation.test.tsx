import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson,
  postJson: mocks.postJson,
  putJson: mocks.putJson,
  friendlyError: (_e: unknown, f: string) => f,
}));

import { findingCharges, findingLabel, severityTone, sortFindings } from "./billingConsistency";
import { describeBillingError } from "./billingErrors";
import { BillingInbox } from "./BillingInbox";
import type { ConsistencyFinding } from "./types";

const APPROVER = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.approve"];
const READONLY = ["virtualpos.billing_changes.view"];
const canOf = (perms: string[]) => (p: string) => perms.includes(p);

const finding = (over: Partial<ConsistencyFinding> = {}): ConsistencyFinding => ({
  scenario: "GB-CS-02", code: "amount_mismatch", severity: "P1", platform: "virtualpos1", subscription_external_id: "S1",
  month: "2026-11", blocks: false, detail: { charge_id: "c1" }, ...over,
});

const QUEUE_ITEM = {
  kind: "managed_charge", id: "mc-1", platform: "virtualpos1", subscription_external_id: "SUB-9", since: "2026-11-01T10:00:00+00:00",
  request_id: "r-1", charge_id: "cid_9", month: "2027-01", stale: true,
};
let queue: Record<string, unknown>[] = [];

beforeEach(() => {
  mocks.getJson.mockReset();
  mocks.postJson.mockReset();
  queue = [QUEUE_ITEM];
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: [] };
    if (path.startsWith("/api/v1/billing/renewal-tasks")) return { items: [], total: 0, limit: 1, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes?")) return { items: [], total: 0, limit: 25, offset: 0 };
    if (path === "/api/v1/billing/reconciliation-queue") return { items: queue, total: queue.length, stale: queue.filter((q) => q.stale).length };
    if (path === "/api/v1/billing/consistency") {
      return {
        generated_at: "2026-11-02T10:00:00+00:00", today: "2026-11-02", ok: false, subscriptions_checked: 3,
        counts: { double_pending: 1 }, by_severity: { P0: 1 },
        findings: [finding({ scenario: "GB-CS-03", code: "double_pending", severity: "P0", blocks: true, detail: { charge_ids: ["a", "b"] } })],
      };
    }
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

describe("consistencia: funciones puras", () => {
  it("etiqueta, tono y cobros", () => {
    expect(findingLabel("double_pending")).toBe("Mes con dos cobros pendientes");
    expect(findingLabel("codigo_nuevo")).toBe("codigo_nuevo");
    expect(severityTone("P0")).toBe("error");
    expect(severityTone("P1")).toBe("warning");
    expect(severityTone("P2")).toBe("neutral");
    expect(findingCharges(finding({ detail: { charge_ids: ["a", 3, "b"] } }))).toBe("a, b");
    expect(findingCharges(finding({ detail: {} }))).toBe("");
  });

  it("ordena P0 primero y luego los que bloquean", () => {
    const sorted = sortFindings([finding({ severity: "P2" }), finding({ severity: "P0" }), finding({ severity: "P0", blocks: true })]);
    expect(sorted.map((f) => `${f.severity}-${f.blocks}`)).toEqual(["P0-true", "P0-false", "P2-false"]);
  });

  it("mensaje claro para la allowlist del piloto y el doble pendiente", () => {
    expect(describeBillingError({ status: 403, detail: { code: "not_in_pilot_allowlist" } }, "x").message).toMatch(/piloto/);
  });
});

describe("pestaña Conciliación", () => {
  async function open(perms = APPROVER) {
    render(<BillingInbox can={canOf(perms)} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Conciliación" }));
    return screen.findByRole("table", { name: /Elementos en conciliación/ });
  }

  it("muestra la cola con el aviso de más de 24 h y ejecuta los controles a pedido", async () => {
    const table = await open(READONLY);
    expect(within(table).getByText("SUB-9")).toBeTruthy();
    expect(screen.getByText(/más de 24 horas/)).toBeTruthy();
    expect(within(table).queryByRole("button", { name: /Resolver/ })).toBeNull(); // solo lectura sin permiso de aprobar
    expect(mocks.getJson.mock.calls.some((c) => c[0] === "/api/v1/billing/consistency")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar controles" }));
    const findings = await screen.findByRole("table", { name: /Hallazgos/ });
    expect(within(findings).getByText("Mes con dos cobros pendientes")).toBeTruthy();
    expect(within(findings).getByText("a, b")).toBeTruthy();
  });

  it("resolver exige comentario y envía la resolución", async () => {
    const table = await open();
    fireEvent.click(within(table).getByRole("button", { name: /Resolver el cobro cid_9/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Registrar resolución" }));
    expect(within(dialog).getByRole("alert").textContent).toMatch(/obligatorio/);
    fireEvent.click(within(dialog).getByLabelText(/Cancelado/));
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "verificado en el panel" } });
    mocks.postJson.mockResolvedValue({ id: "mc-1", status: "cancelado" });
    queue = [];
    fireEvent.click(within(dialog).getByRole("button", { name: "Registrar resolución" }));
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledWith(
      "/api/v1/billing/reconciliation-queue/managed-charges/mc-1/resolve", { resolution: "cancelado", comment: "verificado en el panel" }));
    expect(await screen.findByText(/No hay nada pendiente de conciliación/)).toBeTruthy();
  });
});
