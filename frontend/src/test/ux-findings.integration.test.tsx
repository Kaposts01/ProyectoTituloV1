import { act } from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, mountApp, navTop, resetApp, type Handler } from "./appHarness";

afterEach(resetApp);
const member = { rut: "11111111-1", name: "DEMO Socia", origins: ["virtualpos1"], active_origins: ["virtualpos1"] };
const members: Handler = ["GET", "/api/v1/staging/dashboard/general/clients", { items: [member], total: 1, offset: 0, limit: 50 }];
const detail = { rut: member.rut, clients: [], subscriptions: [{ portal: "virtualpos1", external_id: "DEMO-SUB", id_subscription: "DEMO-I", status: "ACTIVA" }], charges: [], transactions: [] };
const subscription = { channel: "virtualpos1", subscription_id: "DEMO-SUB", status: "ACTIVA", name: member.name, rut: member.rut,
  amount: "12500", currency: "CLP", start_date: "2026-01-01", end_date: null, last_charge: "2026-11-05", secondary_status: null };
const subs: Handler[] = [
  ["GET", "/api/v1/general/subscriptions", { items: [subscription], total: 120, offset: 0, limit: 50, canales: ["virtualpos1"], by_channel: { virtualpos1: 120 } }],
  ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [], canales: ["virtualpos1"] }],
];

describe("Correcciones de los hallazgos UX", () => {
  it("explica la apertura de ficha, evita repetirla y devuelve el foco al resultado", async () => {
    let release!: (result: typeof detail) => void;
    const pending = new Promise<typeof detail>((resolve) => { release = resolve; });
    const app = mountApp("/central/clientes", [members, ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", () => pending]]);
    await appReady(); const open = await screen.findByRole("button", { name: "11.111.111-1" });
    fireEvent.click(open); expect(screen.getByText("Abriendo ficha de DEMO Socia…")).toHaveAttribute("role", "status");
    expect(open).toBeDisabled(); fireEvent.click(open);
    expect(app.exact("GET", "/api/v1/staging/dashboard/general/clients/11111111-1")).toHaveLength(1);
    await act(async () => release(detail)); expect(await screen.findByRole("heading", { name: "DEMO Socia", level: 2 })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Ver suscripción" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "← Volver a socios" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "11.111.111-1" })).toHaveFocus());
  });

  it("permite reintentar una ficha fallida sin borrar la búsqueda", async () => {
    let tries = 0;
    mountApp("/central/clientes", [members, ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", () => ++tries === 1 ? { __status: 503, body: { detail: "No disponible" } } : detail]]);
    await appReady(); await screen.findByRole("button", { name: "11.111.111-1" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar socios" }), { target: { value: "DEMO" } });
    await screen.findByText(/Texto: «DEMO»/); await waitFor(() => expect(screen.getByRole("button", { name: "11.111.111-1" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "11.111.111-1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar ficha" }));
    await screen.findByRole("heading", { name: "DEMO Socia", level: 2 });
    expect(screen.getByRole("searchbox", { name: "Buscar socios" })).toHaveValue("DEMO");
  });

  it("no ofrece enlaces relacionados si falta el permiso específico", async () => {
    mountApp("/central/clientes", [members, ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", detail]], { permissions: ["dashboard.view"] });
    await appReady(); fireEvent.click(await screen.findByRole("button", { name: "11.111.111-1" }));
    await screen.findByRole("heading", { name: "DEMO Socia", level: 2 });
    expect(screen.queryByRole("button", { name: "Ver suscripción" })).toBeNull();
    expect(screen.getByText("Sin acceso a la ficha del canal")).toBeTruthy();
  });

  it("conserva búsqueda, canal y página de Suscripciones al visitar otro módulo, sin persistirlos", async () => {
    mountApp("/central/suscripciones", [...subs, members]);
    await appReady(); await screen.findByRole("button", { name: "DEMO-SUB" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar" }), { target: { value: "DEMO-PRIVATE" } });
    fireEvent.change(screen.getByLabelText("Canal", { exact: true }), { target: { value: "virtualpos1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Siguiente →" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    fireEvent.click(navTop("Socios")); await screen.findByRole("heading", { name: "Socios", level: 1 });
    fireEvent.click(navTop("Suscripciones")); await screen.findByRole("button", { name: "DEMO-SUB" });
    expect(screen.getByRole("searchbox", { name: "Buscar" })).toHaveValue("DEMO-PRIVATE");
    expect(screen.getByLabelText("Canal", { exact: true })).toHaveValue("virtualpos1");
    expect(within(screen.getByRole("navigation", { name: "Paginación" })).getByText("51-51 de 120")).toBeTruthy();
    expect(window.location.href + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain("DEMO-PRIVATE");
  });

  it("explica la ausencia de acceso a fichas sin ampliar los permisos generales", async () => {
    mountApp("/central/suscripciones", subs, { permissions: ["general.subscriptions.view"] });
    await appReady(); await screen.findByText("DEMO-SUB");
    expect(screen.queryByRole("button", { name: "DEMO-SUB" })).toBeNull();
    expect(screen.getByText(/Los identificadores sin enlace/)).toBeTruthy();
  });
});
