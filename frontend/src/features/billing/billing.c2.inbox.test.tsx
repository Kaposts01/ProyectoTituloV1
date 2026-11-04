import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson, postJson: mocks.postJson, putJson: mocks.putJson, setCsrfToken: vi.fn(),
  friendlyError: (_e: unknown, f: string) => f,
}));

import { BillingInbox } from "./BillingInbox";
import { CHILE_TZ_NOTE, statusTone } from "./billingLabels";

const ADMIN = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.request", "virtualpos.billing_changes.approve", "virtualpos.billing_policy.manage"];
const canOf = (perms: string[]) => (p: string) => perms.includes(p);
const PLAN = {
  noop: false, cancel: [], create: [{ month: "2026-04", charge_date: "2026-04-10", amount: 8000, internal_code: "S1-202604" }],
  covered: [], manual_review: [], unchanged: [], kept_automatic_after_horizon: [], warnings: [], errors: [], summary: null,
};
function req(over: Record<string, unknown> = {}) {
  return {
    id: "r1", request_type: "change_amount", platform: "virtualpos1", subscription_external_id: "SUB-100", status: "aprobada",
    requested_by_user_id: "u1", requested_by: "admin", new_amount: 8000, previous_amount: 5000, new_charge_day: null, previous_charge_day: null,
    new_charge_date: null, horizon_months: 12, horizon_start_month: "2026-04", approvals_required: 1, approvals_count: 1,
    requester_comment: null, approved_by_user_id: "u1", approved_by: "admin", self_approved: true, decided_at: "2026-03-01T10:02:00+00:00",
    decision_comment: null, write_run_id: null, expires_at: null, executed_at: null,
    error_message: null, created_at: "2026-03-01T10:00:00+00:00", updated_at: null, ...over,
  };
}
const EVENTS = [
  { id: "e1", event_type: "creada", actor_user_id: "u1", actor: "admin", detail: {}, created_at: "2026-03-01T10:00:00+00:00" },
  { id: "e2", event_type: "autoaprobada", actor_user_id: "u1", actor: "admin", detail: {}, created_at: "2026-03-01T10:00:01+00:00" },
];
const items = () => [req(), req({ id: "r2", subscription_external_id: "SUB-200", status: "no_ejecutable" })];
let listItems = items();

beforeEach(() => {
  mocks.getJson.mockReset();
  listItems = items();
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: [] };
    if (path.startsWith("/api/v1/billing/renewal-tasks")) return { items: [], total: 0, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/billing/changes?")) return { items: listItems, total: listItems.length, limit: 25, offset: 0 };
    const m = /^\/api\/v1\/billing\/changes\/(r\d)$/.exec(path);
    if (m) return { ...(listItems.find((i) => i.id === m[1]) ?? req()), plan_preview: PLAN, rules_snapshot: {}, events: EVENTS };
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView; });

async function openFirst() {
  render(<BillingInbox can={canOf(ADMIN)} />);
  fireEvent.click(await screen.findByRole("button", { name: /Ver solicitud de la suscripción SUB-100/ }));
  return screen.findByRole("heading", { name: /Cambio de monto/ });
}
const media = (reduce: boolean) => (q: string) => ({ matches: reduce && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });

describe("D3 insignias", () => {
  it("«No ejecutable» es advertencia (con punto y texto), no gris neutro como Expirada/Retirada", async () => {
    expect(statusTone("no_ejecutable")).toBe("warning");
    expect(statusTone("expirada")).toBe("neutral");
    expect(statusTone("retirada")).toBe("neutral");
    render(<BillingInbox can={canOf(ADMIN)} />);
    const badge = await screen.findByText("No ejecutable");
    expect(badge.className).toContain("bx-badge-warning");
  });
});

describe("D4 un solo huso por pantalla", () => {
  it("un unico aviso junto a los filtros y sin pie duplicado bajo la tabla", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    await screen.findByRole("table");
    const hint = screen.getByText("Filtros por fecha en UTC · resultados en hora de Chile");
    expect(screen.getByRole("form", { name: "Filtros de solicitudes" }).contains(hint)).toBe(true);
    expect(screen.getByLabelText("Desde").getAttribute("aria-describedby")).toBe(hint.id);
    expect(screen.queryByText(CHILE_TZ_NOTE)).toBeNull();
    expect(screen.queryByText("Fechas en UTC")).toBeNull();
  });

  it("el detalle conserva UNA sola nota de hora de Chile", async () => {
    await openFirst();
    const notes = screen.getAllByText(CHILE_TZ_NOTE);
    expect(notes).toHaveLength(1);
    expect(notes[0].closest("section")?.className).toContain("bx-detail");
  });
});

describe("D5 detalle frente al listado", () => {
  it("la fila seleccionada se marca con aria-current y texto visible, sin depender solo del fondo", async () => {
    await openFirst();
    const btn = screen.getByRole("button", { name: /SUB-100/ });
    expect(btn.getAttribute("aria-current")).toBe("true");
    const row = btn.closest("tr")!;
    expect(row.getAttribute("data-selected")).toBe("true");
    expect(within(row).getByText("Detalle abajo")).toBeTruthy();
    const other = screen.getByRole("button", { name: /SUB-200/ });
    expect(other.getAttribute("aria-current")).toBeNull();
    expect(within(other.closest("tr")!).queryByText("Detalle abajo")).toBeNull();
  });

  it("desplaza el detalle a la vista (smooth) y mueve el foco al titulo", async () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    vi.stubGlobal("matchMedia", media(false));
    const heading = await openFirst();
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ block: "start", behavior: "smooth" }));
    expect(document.activeElement).toBe(heading);
  });

  it("con prefers-reduced-motion el desplazamiento es inmediato", async () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    vi.stubGlobal("matchMedia", media(true));
    await openFirst();
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ block: "start", behavior: "auto" }));
  });

  it("volver a pulsar la misma fila vuelve a llevar el detalle a la vista", async () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    await openFirst();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /SUB-100/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });
});

describe("D6 valores en mono", () => {
  it("plataforma, solicitante y aprobador del detalle van en mono", async () => {
    await openFirst();
    const section = screen.getByRole("heading", { name: /Cambio de monto/ }).closest("section")!;
    for (const label of ["Plataforma", "Solicitante", "Aprobada por"]) {
      const dt = within(section).getByText(label, { selector: "dt" });
      expect((dt.nextElementSibling as HTMLElement).className, label).toContain("mono");
    }
  });

  it("el actor de cada evento y su hora van en mono", async () => {
    await openFirst();
    const lis = within(screen.getByRole("list", { name: /Línea de tiempo/ })).getAllByRole("listitem");
    expect(lis).toHaveLength(2);
    for (const li of lis) {
      expect(li.querySelector(".bx-ev-actor")?.className).toContain("mono");
      expect(li.querySelector(".bx-ev-time")?.className).toContain("mono");
    }
  });

  it("el solicitante del listado va en mono", async () => {
    render(<BillingInbox can={canOf(ADMIN)} />);
    const table = await screen.findByRole("table");
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getAllByText("admin")[0].className).toContain("mono");
  });
});
