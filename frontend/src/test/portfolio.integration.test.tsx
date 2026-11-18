import { act } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, mountApp, resetApp, type Call } from "./appHarness";

afterEach(resetApp);
const row = { channel: "toku", subscription_id: "DEMO-SUB", status: "ACTIVE", secondary_status: null,
  start_date: null, end_date: null, last_charge: null, amount: "5000", currency: "CLP", rut: "11111111-1", name: "DEMO Socio" };
const page = { items: [row], total: 1, offset: 0, limit: 50, by_channel: { toku: 1 }, canales: ["toku"] };
const facets = { statuses: [{ status: "ACTIVE", count: 1 }], canales: ["toku"] };

describe("Cartera: búsqueda y resultados", () => {
  it("la búsqueda pendiente oculta filas anteriores, bloquea exportar y no entra en URL ni almacenamiento", async () => {
    let release!: (reply: typeof page) => void;
    const waiting = new Promise<typeof page>((r) => { release = r; });
    const app = mountApp("/central/suscripciones", [
      ["GET", "/api/v1/general/subscriptions", (call: Call) => call.query.has("query") ? waiting : page],
      ["GET", "/api/v1/general/subscriptions/statuses", facets],
    ]);
    await appReady();
    await screen.findByRole("button", { name: "DEMO-SUB" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar" }), { target: { value: "PRIVATE-SEARCH" } });
    expect(screen.queryByRole("button", { name: "DEMO-SUB" })).toBeNull();
    expect(screen.getByRole("button", { name: /Exportar/ })).toBeDisabled();
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/subscriptions").at(-1)?.query.get("query")).toBe("PRIVATE-SEARCH"));
    expect(window.location.href).not.toContain("PRIVATE-SEARCH");
    expect(JSON.stringify(localStorage)).not.toContain("PRIVATE-SEARCH");
    await act(async () => release({ ...page, items: [{ ...row, subscription_id: "DEMO-NEW" }] }));
    await screen.findByRole("button", { name: "DEMO-NEW" });
    expect(screen.getByRole("button", { name: /Exportar/ })).toBeEnabled();
  });
  it("desde un resultado vacío filtrado puede quitar los criterios y recuperar el listado", async () => {
    const app = mountApp("/central/suscripciones", [
      ["GET", "/api/v1/general/subscriptions", (call: Call) => call.query.has("query") ? { ...page, items: [], total: 0 } : page],
      ["GET", "/api/v1/general/subscriptions/statuses", facets],
    ]);
    await appReady(); await screen.findByRole("button", { name: "DEMO-SUB" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar" }), { target: { value: "missing" } });
    fireEvent.click(await screen.findByRole("button", { name: "Quitar todos los filtros" }));
    await screen.findByRole("button", { name: "DEMO-SUB" });
    expect(app.exact("GET", "/api/v1/general/subscriptions").at(-1)?.query.has("query")).toBe(false);
    expect(screen.getByRole("searchbox", { name: "Buscar" })).toHaveValue("");
  });
  it("una ficha de Socios pendiente no reaparece después de cambiar la búsqueda", async () => {
    const detail = { rut: "11111111-1", clients: [], subscriptions: [], charges: [], transactions: [] };
    let release!: (reply: typeof detail) => void;
    const waiting = new Promise<typeof detail>((r) => { release = r; });
    mountApp("/central/clientes", [
      ["GET", "/api/v1/staging/dashboard/general/clients", { items: [{ rut: "11111111-1", name: "DEMO Socio", origins: ["TCH"], active_origins: [] }], total: 1, offset: 0, limit: 50 }],
      ["GET", "/api/v1/staging/dashboard/general/clients/11111111-1", () => waiting],
    ]);
    await appReady(); fireEvent.click(await screen.findByRole("button", { name: "11.111.111-1" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar socios" }), { target: { value: "Otro" } });
    await act(async () => release(detail));
    expect(document.querySelector(".record-detail")).toBeNull();
    expect(screen.getByRole("searchbox", { name: "Buscar socios" })).toHaveValue("Otro");
  });
});
