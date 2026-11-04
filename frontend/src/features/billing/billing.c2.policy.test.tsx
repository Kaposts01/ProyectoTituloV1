import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson, postJson: mocks.postJson, putJson: mocks.putJson, friendlyError: (_e: unknown, f: string) => f,
}));

import { PolicyPanel } from "./PolicyPanel";

const base = {
  approver_roles: ["admin"], approver_user_ids: [], self_approval_enabled: true, dual_approval_enabled: false,
  dual_threshold_subscriptions: 10, dual_threshold_variation_pct: 25, renewal_threshold_days: 30, request_expiry_days: 7,
  horizon_months: 12, window_days: 30,
};
const roles = [{ id: "1", name: "admin" }, { id: "2", name: "ejecutivo" }];
let policy = { ...base };

beforeEach(() => {
  mocks.getJson.mockReset(); mocks.putJson.mockReset();
  policy = { ...base };
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path === "/api/v1/billing/policy") return policy;
    if (path.startsWith("/api/v1/billing/policy/audit")) return { items: [], total: 0, limit: 20, offset: 0 };
    if (path === "/api/v1/admin/users") return [{ id: "u1", username: "root", is_active: true }];
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(cleanup);

async function open() {
  render(<PolicyPanel roles={roles} canListUsers />);
  await screen.findByLabelText(/Expiración de solicitudes/);
}
const save = () => screen.getByRole("button", { name: "Guardar política" }) as HTMLButtonElement;
const discard = () => screen.getByRole("button", { name: "Descartar cambios" }) as HTMLButtonElement;

describe("D7d guardar y descartar", () => {
  it("están deshabilitados sin cambios y no se muestra «Cambios sin guardar»", async () => {
    await open();
    expect(save().disabled).toBe(true);
    expect(discard().disabled).toBe(true);
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
  });

  it("al editar se habilitan y avisan; descartar vuelve al estado limpio", async () => {
    await open();
    fireEvent.change(screen.getByLabelText(/Expiración de solicitudes/), { target: { value: "14" } });
    expect(save().disabled).toBe(false);
    expect(discard().disabled).toBe(false);
    expect(screen.getByText("Cambios sin guardar")).toBeTruthy();
    fireEvent.click(discard());
    expect((screen.getByLabelText(/Expiración de solicitudes/) as HTMLInputElement).value).toBe("7");
    expect(save().disabled).toBe(true);
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
  });

  it("volver al valor original deja de contar como cambio", async () => {
    await open();
    const f = screen.getByLabelText(/Expiración de solicitudes/);
    fireEvent.change(f, { target: { value: "14" } });
    fireEvent.change(f, { target: { value: "7" } });
    expect(save().disabled).toBe(true);
  });

  it("tras guardar vuelve a quedar deshabilitado", async () => {
    mocks.putJson.mockImplementation(async (_p: string, body: Record<string, unknown>) => ({ ...policy, ...body }));
    await open();
    fireEvent.change(screen.getByLabelText(/Expiración de solicitudes/), { target: { value: "14" } });
    fireEvent.click(save());
    await screen.findByText(/Política actualizada/);
    expect(save().disabled).toBe(true);
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
  });
});

describe("D7c umbrales de doble aprobación", () => {
  const thresholds = () => [screen.getByLabelText(/Umbral de suscripciones/), screen.getByLabelText(/Umbral de variación/)] as HTMLInputElement[];

  it("se atenúan (disabled) con el texto de por qué mientras la doble aprobación está desmarcada", async () => {
    await open();
    for (const input of thresholds()) expect(input.disabled).toBe(true);
    expect(screen.getAllByText("Solo aplica si se exige doble aprobación")).toHaveLength(2);
    fireEvent.click(screen.getByRole("checkbox", { name: /Exigir doble aprobación/ }));
    for (const input of thresholds()) expect(input.disabled).toBe(false);
    expect(screen.queryByText("Solo aplica si se exige doble aprobación")).toBeNull();
  });

  it("con la política ya en doble aprobación los umbrales están activos", async () => {
    policy = { ...base, dual_approval_enabled: true };
    await open();
    for (const input of thresholds()) expect(input.disabled).toBe(false);
  });

  it("el valor editado no se pierde al desmarcar y el parche conserva solo lo modificado", async () => {
    mocks.putJson.mockImplementation(async (_p: string, body: Record<string, unknown>) => ({ ...policy, ...body }));
    await open();
    const dual = screen.getByRole("checkbox", { name: /Exigir doble aprobación/ });
    fireEvent.click(dual);
    fireEvent.change(screen.getByLabelText(/Umbral de suscripciones/), { target: { value: "20" } });
    fireEvent.click(dual);
    expect((screen.getByLabelText(/Umbral de suscripciones/) as HTMLInputElement).value).toBe("20");
    fireEvent.click(save());
    await waitFor(() => expect(mocks.putJson).toHaveBeenCalledWith("/api/v1/billing/policy", { dual_threshold_subscriptions: 20 }));
  });
});

describe("D7 parche sin cambios de comportamiento", () => {
  it("editar un campo normal envía exactamente el mismo parche de siempre", async () => {
    mocks.putJson.mockResolvedValue({ ...policy, request_expiry_days: 14 });
    await open();
    fireEvent.change(screen.getByLabelText(/Expiración de solicitudes/), { target: { value: "14" } });
    fireEvent.change(screen.getByLabelText(/Motivo del cambio/), { target: { value: "Más plazo" } });
    fireEvent.click(save());
    await waitFor(() => expect(mocks.putJson).toHaveBeenCalledTimes(1));
    expect(mocks.putJson).toHaveBeenCalledWith("/api/v1/billing/policy", { request_expiry_days: 14, reason: "Más plazo" });
  });
});

describe("D7b y D7e textos de ayuda", () => {
  it("todos los campos numéricos llevan ayuda (rejilla alineada) y horizonte/ventana dicen qué hacen", async () => {
    await open();
    expect(screen.getByText("Meses hacia adelante que cubre un cambio de cobro")).toBeTruthy();
    expect(screen.getByText("Días hacia atrás en los que un mes atrasado se reemplaza con fecha de mañana; más antiguo va a revisión manual")).toBeTruthy();
    for (const re of [/Umbral de suscripciones/, /Umbral de variación/, /N de renovación/, /Expiración de solicitudes/, /Horizonte \(meses\)/, /Ventana \(días\)/]) {
      const input = screen.getByLabelText(re);
      expect(input.closest("label")?.querySelector(".bx-hint"), String(re)).toBeTruthy();
    }
  });

  it("explica la relación entre roles y usuarios aprobadores", async () => {
    await open();
    expect(screen.getByText("Aprueba quien tenga un rol marcado o esté marcado como usuario")).toBeTruthy();
  });
});

describe("D7f grupos sin tarjeta anidada", () => {
  it("roles y usuarios son grupos sin borde con legend, no fieldsets con borde", async () => {
    await open();
    const form = screen.getByRole("form", { name: "Política de aprobaciones" });
    expect(form.querySelector(".bx-fieldset")).toBeNull();
    const groups = within(form).getAllByRole("group");
    const named = ["Roles aprobadores", "Usuarios aprobadores"].map((n) => groups.find((g) => g.querySelector("legend")?.textContent === n));
    for (const g of named) {
      expect(g, "grupo").toBeTruthy();
      expect(g!.className).toContain("bx-group");
    }
    expect(form.querySelectorAll("hr.bx-sep").length).toBeGreaterThan(0);
  });
});
