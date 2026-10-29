import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson,
  postJson: mocks.postJson,
  putJson: mocks.putJson,
  friendlyError: (_e: unknown, f: string) => f,
}));

import { BillingInbox } from "./BillingInbox";
import { PlanPreviewView } from "./PlanPreviewView";
import type { PlanPreview } from "./types";

const PERMS = ["virtualpos.billing_changes.view", "virtualpos.billing_changes.request"];
const can = (p: string) => PERMS.includes(p);

const REQUEST = {
  id: "r1", request_type: "change_amount", platform: "virtualpos1", subscription_external_id: "SUB-111", status: "pendiente",
  requested_by_user_id: "u1", requested_by: "ana", new_amount: 8000, previous_amount: 5000, new_charge_day: null, previous_charge_day: null,
  new_charge_date: null, horizon_months: 12, horizon_start_month: "2026-04", approvals_required: 1, approvals_count: 0,
  requester_comment: null, approved_by_user_id: null, approved_by: null, self_approved: false, decided_at: null, decision_comment: null,
  write_run_id: null, expires_at: null, executed_at: null, error_message: null, created_at: "2026-03-01T10:00:00+00:00", updated_at: null,
};
const TASK = {
  id: "t1", platform: "virtualpos1", subscription_external_id: "SUB-777", status: "abierta", priority: "alta",
  last_scheduled_date: "2026-12-01", scheduled_amount: 12000, due_date: "2026-12-01", days_remaining: 20, data_stale: false,
  request_id: null, close_reason: null,
};
let alertTotal = 0;

beforeEach(() => {
  mocks.getJson.mockReset();
  alertTotal = 0;
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/requesters") return { items: [] };
    if (path.startsWith("/api/v1/billing/renewal-tasks")) {
      if (path.includes("limit=1&")) return { items: [], total: alertTotal, limit: 1, offset: 0 };
      return { items: [TASK], total: 1, limit: 25, offset: 0 };
    }
    if (path.startsWith("/api/v1/billing/changes?")) return { items: [REQUEST], total: 1, limit: 25, offset: 0 };
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

const cellLabels = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.getAttribute("data-label"));

describe("filas apiladas en movil (CSS sobre la misma tabla semantica)", () => {
  it("Pendientes: cada fila conserva rol de tabla y expone estado, cambio y enlace con etiqueta", async () => {
    render(<BillingInbox can={can} />);
    const table = await screen.findByRole("table", { name: /Solicitudes de cambio de cobro/ });
    expect(table.className).toContain("bx-stack");
    const row = within(table).getAllByRole("row")[1];
    expect(cellLabels(row)).toEqual(["Suscripción", "Tipo", "Cambio", "Estado", "Solicitante", "Creada", "Vencimiento"]);
    expect(within(row).getByRole("button", { name: /Ver solicitud de la suscripción SUB-111/ })).toBeTruthy();
    expect(within(row).getByText("Pendiente")).toBeTruthy();
    expect(row.querySelector(".bx-c-status")).not.toBeNull();
    expect(row.querySelector(".bx-c-change")?.textContent).not.toBe("");
  });

  it("Renovaciones: fecha limite, ultimo monto y accion estan en la fila", async () => {
    render(<BillingInbox can={can} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
    const table = await screen.findByRole("table", { name: /Tareas de renovación/ });
    expect(table.className).toContain("bx-stack");
    const row = within(table).getAllByRole("row")[1];
    expect(cellLabels(row)).toEqual(["Suscripción", "Plataforma", "Prioridad", "Estado", "Fecha límite", "Último monto programado", "Acción"]);
    expect(within(row).getByRole("button", { name: /Solicitar renovación de la suscripción SUB-777/ })).toBeTruthy();
    expect(row.querySelector(".bx-c-amount")?.textContent).toContain("12");
    expect(row.querySelector(".bx-c-deadline")).not.toBeNull();
  });

  it("escritorio no cambia: sigue habiendo una tabla con sus 7 encabezados", async () => {
    render(<BillingInbox can={can} />);
    const table = await screen.findByRole("table", { name: /Solicitudes de cambio de cobro/ });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Suscripción", "Tipo", "Cambio", "Estado", "Solicitante", "Creada", "Vencimiento",
    ]);
    expect(table.className).toContain("bx-table");
  });
});

describe("plan de 12 meses en movil", () => {
  const plan = {
    noop: false,
    cancel: [{ month: "2026-09", charge_date: "2026-09-05", amount: 10000, charge_id: "C-1", internal_code: "S-202609" }],
    create: [{ month: "2026-09", charge_date: "2026-09-10", amount: 12000, internal_code: "S-202609" }],
    covered: [], manual_review: [], unchanged: [],
    kept_automatic_after_horizon: [{ month: "2027-05", charge_id: "AUTO-9", charge_date: "2027-05-10", amount: 9000 }],
    warnings: [], errors: [],
    summary: { creates: 1, cancels: 1, covered_months: 0, manual_review_months: 0, unchanged_months: 0, affected_charges: 2, previous_amount: 10000, new_amount: 12000, amount_delta: 2000, total_delta: 2000, variation_pct: 20, horizon_start: "2026-09", horizon_end: "2027-08" },
  } as unknown as PlanPreview;

  it("cada movimiento tiene mes, accion, fecha y monto como celdas etiquetadas", () => {
    render(<PlanPreviewView plan={plan} />);
    const table = screen.getByRole("table", { name: "Plan por mes" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(cellLabels(row)).toEqual(["Mes", "Acción", "Fecha de cobro", "Monto", "Detalle"]);
      expect(row.querySelector(".bx-c-month")?.className).toContain("mono");
      expect(row.querySelector(".bx-c-kind .bx-badge")).not.toBeNull();
      expect(row.querySelector(".bx-c-date")?.textContent).toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(row.querySelector(".bx-c-amount")?.textContent).toContain("$");
    }
  });

  it("los cobros conservados fuera del horizonte tambien se apilan con sus 4 datos", () => {
    render(<PlanPreviewView plan={plan} />);
    const table = screen.getByRole("table", { name: /conservados fuera del horizonte/ });
    const row = within(table).getAllByRole("row")[1];
    expect(cellLabels(row)).toEqual(["Mes", "Cobro", "Fecha", "Monto"]);
    expect(row.textContent).toContain("AUTO-9");
  });
});

describe("filtros colapsables", () => {
  it("Pendientes: colapsado por defecto, aria-expanded, contador de activos y Buscar/Limpiar dentro", async () => {
    render(<BillingInbox can={can} />);
    const form = await screen.findByRole("form", { name: "Filtros de solicitudes" });
    const toggle = within(form).getByRole("button", { name: "Filtros" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const body = document.getElementById(toggle.getAttribute("aria-controls") as string) as HTMLElement;
    expect(body.className).toContain("is-collapsed");
    expect(body.contains(within(form).getByRole("button", { name: "Buscar" }))).toBe(true);
    expect(body.contains(within(form).getByRole("button", { name: "Limpiar" }))).toBe(true);

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(body.className).not.toContain("is-collapsed");

    fireEvent.change(within(form).getByLabelText("Plataforma"), { target: { value: "virtualpos1" } });
    fireEvent.change(within(form).getByLabelText("Suscripción"), { target: { value: "SUB-1" } });
    fireEvent.click(within(form).getByRole("button", { name: "Buscar" }));
    expect(await within(form).findByRole("button", { name: "Filtros (2)" })).toBeTruthy();
  });

  it("Renovaciones: mismo patron; el estado por defecto no cuenta como filtro", async () => {
    render(<BillingInbox can={can} />);
    fireEvent.click(await screen.findByRole("tab", { name: /Renovaciones/ }));
    const form = await screen.findByRole("form", { name: "Filtros de renovaciones" });
    const toggle = within(form).getByRole("button", { name: "Filtros" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    fireEvent.change(within(form).getByLabelText("Prioridad"), { target: { value: "alta" } });
    fireEvent.click(within(form).getByRole("button", { name: "Buscar" }));
    expect(await within(form).findByRole("button", { name: "Filtros (1)" })).toBeTruthy();
  });
});

describe("contador de la pestana Renovaciones", () => {
  it("texto accesible dice lo que cuenta y el contador es de una linea (clase nowrap)", async () => {
    alertTotal = 2;
    render(<BillingInbox can={can} />);
    const tab = await screen.findByRole("tab", { name: /Renovaciones.*2 tareas abiertas o vencidas con prioridad alta/ });
    expect(tab.querySelector(".bx-count")?.textContent).toBe("2");
    await waitFor(() => expect(tab.querySelector(".bx-sr")?.textContent).toContain("prioridad alta"));
  });
});

describe("CSS movil de billing.css", () => {
  const css = readFileSync(resolve(__dirname, "billing.css"), "utf8");
  const mobileBlocks = [...css.matchAll(/@media \(max-width: 720px\) \{/g)].map((m) => {
    let depth = 1;
    let i = (m.index as number) + m[0].length;
    const start = i;
    while (depth > 0 && i < css.length) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    return css.slice(start, i - 1);
  });

  it("hay bloque movil con filas apiladas y la tabla deja de forzar ancho", () => {
    expect(mobileBlocks.length).toBeGreaterThan(0);
    const mobile = mobileBlocks.join("\n");
    expect(mobile).toMatch(/\.bx-stack[^{]*\{[^}]*display:\s*block/);
    expect(mobile).toMatch(/\.bx-table\s*\{[^}]*min-width:\s*0/);
    expect(mobile).toMatch(/\.bx-filters-body\.is-collapsed\s*\{\s*display:\s*none/);
  });

  it("ningun min-width > 390px queda dentro de los bloques moviles", () => {
    for (const block of mobileBlocks) {
      for (const m of block.matchAll(/min-width:\s*(\d+(?:\.\d+)?)px/g)) expect(Number(m[1])).toBeLessThanOrEqual(390);
    }
  });

  it("fuera del bloque movil el ancho minimo de 760px (escritorio) sigue en .bx-table", () => {
    expect(css).toMatch(/\.bx-table\s*\{[^}]*min-width:\s*760px/);
  });

  it("controles tactiles de 44px en movil y filtros ocultos en escritorio", () => {
    expect(mobileBlocks.join("\n")).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(/\.bx-filters-toggle\s*\{\s*display:\s*none/);
  });
});
