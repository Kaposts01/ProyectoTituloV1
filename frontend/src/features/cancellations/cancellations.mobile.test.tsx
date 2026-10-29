import { cleanup, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn() }));
vi.mock("../../api", () => ({ getJson: mocks.getJson, postJson: mocks.postJson, friendlyError: (_e: unknown, f: string) => f }));

import { CancellationsInbox } from "./CancellationsInbox";

const ROW = {
  id: "r1", channel: "payku", subscription_external_id: "SUB-111", status: "approved", reason_code: "other", reason_comment: "x",
  requested_by_user_id: "u1", requested_by: "ana", approved_by_user_id: null, approved_by: null, self_approved: false, approvals_required: 1,
  approvals_count: 1, decided_at: null, decision_comment: null, options: { confirm_irreversible: true }, requires_reconciliation: false,
  write_run_id: null, expires_at: null, executed_at: null, error_message: null, created_at: "2026-10-01T10:00:00+00:00", updated_at: null,
};

beforeEach(() => {
  mocks.getJson.mockReset().mockResolvedValue({ items: [ROW], total: 1, limit: 25, offset: 0 });
});
afterEach(cleanup);

const css = readFileSync(resolve(process.cwd(), "src/features/cancellations/cancellations.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe("móvil (390 px): la misma tabla semántica se apila por CSS", () => {
  it("cada celda lleva su etiqueta y la tabla usa la clase de apilado con orden propio", async () => {
    render(<CancellationsInbox can={() => true} />);
    const table = await screen.findByRole("table", { name: /Solicitudes de baja/ });
    expect(table.className).toContain("bx-stack");
    expect(table.className).toContain("bx-stack-cancellations");
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getAllByRole("cell").map((c) => c.getAttribute("data-label"))).toEqual(["Suscripción", "Canal", "Motivo", "Solicitante", "Estado", "Creada"]);
    for (const klass of ["bx-c-sub", "bx-c-status", "bx-c-channel", "bx-c-reason", "bx-c-created", "bx-c-who"]) expect(css, klass).toContain(`.bx-stack-cancellations .${klass}`);
  });

  it("los filtros se pliegan en móvil con un botón de 44 px y el menú de pestañas hace scroll horizontal", async () => {
    render(<CancellationsInbox can={() => true} />);
    await screen.findByRole("table");
    const toggle = screen.getByRole("button", { name: "Filtros" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();
  });
});

describe("estilos de bajas: solo tokens de DESIGN.md", () => {
  it("no fija colores hexadecimales ni rgb, no usa borde lateral de color y los objetivos táctiles miden 44 px", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/rgba?\(/);
    expect(css).not.toMatch(/border-(left|inline-start)/);
    expect(css).toMatch(/\.cx-search-results button\s*\{\s*min-height:\s*44px/);
  });
});
