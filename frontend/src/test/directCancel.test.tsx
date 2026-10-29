/**
 * Botones directos de baja (D12-7): el backend exige el rol admin para DELETE de suscripciones y para Toku «CANCELLED».
 * Quien no es admin no ve esos botones: ve un texto que lo dirige a «Solicitar baja» en Bajas. Los demás botones
 * (+ Cargo, Editar, Pausar o activar en Toku, Eliminar de otros recursos) no cambian. Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ALL_PERMISSIONS, appReady, listSettled, mountApp, resetApp, type Handler } from "./appHarness";
import { page, paykuSubscription, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPayment, vpSubscription } from "./fixtures";

afterEach(resetApp);

const records = (items: unknown[]): Handler => ["GET", "/api/v1/staging/records", page(items, items.length)];
const listHandler: Handler = ["GET", "/api/v1/staging/records", page([])];
const NON_ADMIN = { roles: ["jefatura"], permissions: [...ALL_PERMISSIONS, "subscriptions.cancellation.view", "subscriptions.cancellation.request"] };
const NO_VIEW = { roles: ["ejecutivo"], permissions: ALL_PERMISSIONS };
const ADMIN = { roles: ["admin"], permissions: ALL_PERMISSIONS };

const clientDetail = {
  client: vpClient(1), subscriptions: [vpSubscription(1)], subscription_total: 1,
  charges: [vpCharge(1, "pendiente")], charge_total: 1, payments: [vpPayment(1)], payment_total: 1,
};
const subscriptionDetail = {
  subscription: vpSubscription(1, { plan_id: "plan-1" }), payment_method: null, charges: [vpCharge(1, "pendiente")], charge_total: 1, payments: [], payment_total: 0,
};

describe("VirtualPOS: «Cancelar» solo para admin", () => {
  it("lista de suscripciones: el no admin no ve «Cancelar Sub», conserva «+ Cargo» y ve el texto hacia «Solicitar baja»", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)])], NON_ADMIN);
    await appReady();
    expect(await screen.findByRole("button", { name: "+ Cargo" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancelar Sub" })).toBeNull();
    const note = screen.getByTestId("direct-cancel-note");
    expect(note.textContent).toContain("«Solicitar baja»");
    expect(within(note).getByRole("link", { name: "Bajas" }).getAttribute("href")).toBe("/general/bajas");
  });

  it("ficha del cliente y ficha de la suscripción: sin botón de cancelar, con el texto", async () => {
    mountApp("/virtualpos/clientes/cli-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/clients/cli-1", clientDetail]], NON_ADMIN);
    await appReady();
    await screen.findByText("FICHA DEL CLIENTE");
    expect(screen.queryByRole("button", { name: "Cancelar" })).toBeNull();
    expect(screen.getByTestId("direct-cancel-note").textContent).toContain("«Solicitar baja»");
    resetApp();
    mountApp("/virtualpos/suscripciones/sub-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", subscriptionDetail]], NON_ADMIN);
    await appReady();
    await screen.findByText("FICHA DE LA SUSCRIPCIÓN");
    expect(screen.queryByRole("button", { name: "Cancelar Sub" })).toBeNull();
    expect(screen.getByRole("button", { name: "+ Nuevo cargo" })).toBeTruthy();
    expect(screen.getByTestId("direct-cancel-note").textContent).toContain("«Solicitar baja»");
  });

  it("sin permiso para abrir Bajas el texto pide a una jefatura que use «Solicitar baja» y no hay enlace", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)])], NO_VIEW);
    await appReady();
    await screen.findByRole("button", { name: "+ Cargo" });
    const note = screen.getByTestId("direct-cancel-note");
    expect(note.textContent).toContain("pida a una jefatura que use «Solicitar baja»");
    expect(within(note).queryByRole("link")).toBeNull();
  });

  it("el admin conserva todos los botones directos y no ve el texto", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)])], ADMIN);
    await appReady();
    expect(await screen.findByRole("button", { name: "Cancelar Sub" })).toBeTruthy();
    expect(screen.queryByTestId("direct-cancel-note")).toBeNull();
  });

  it("el enlace del texto lleva a la pantalla Bajas sin recargar", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)]), ["GET", "/api/v1/cancellations", { items: [], total: 0, limit: 25, offset: 0 }]], NON_ADMIN);
    await appReady();
    await screen.findByRole("button", { name: "+ Cargo" });
    fireEvent.click(within(screen.getByTestId("direct-cancel-note")).getByRole("link", { name: "Bajas" }));
    expect(await screen.findByRole("heading", { name: "Bajas" })).toBeTruthy();
    expect(window.location.pathname).toBe("/general/bajas");
    expect(screen.getAllByRole("button", { name: "Solicitar baja" }).length).toBeGreaterThan(0);
  });
});

describe("Toku y Payku: «Eliminar» una suscripción y «Cancelada» solo para admin", () => {
  it("Toku lista de suscripciones: el no admin no ve «Eliminar»; en la lista de clientes sí", async () => {
    mountApp("/toku/suscripciones", [records([tokuSubscription(1)])], NON_ADMIN);
    await appReady();
    await screen.findByText(/Solicitar baja/);
    expect(screen.queryByRole("button", { name: "Eliminar" })).toBeNull();
    resetApp();
    mountApp("/toku/clientes", [records([tokuCustomer(1)])], NON_ADMIN);
    await appReady();
    expect(await screen.findByRole("button", { name: "Eliminar" })).toBeTruthy();
    expect(screen.queryByTestId("direct-cancel-note")).toBeNull();
  });

  it("Payku lista de suscripciones: el no admin no ve «Eliminar»", async () => {
    mountApp("/payku/suscripciones", [records([paykuSubscription(1)])], NON_ADMIN);
    await appReady();
    await screen.findByText(/Solicitar baja/);
    expect(screen.queryByRole("button", { name: "Eliminar" })).toBeNull();
  });

  it("ficha de una suscripción Toku: sigue «Gestionar estado» pero sin «Eliminar» y sin la opción «Cancelada»", async () => {
    mountApp("/toku/suscripciones/tsu-1", [listHandler, ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1), related: [] }]], NON_ADMIN);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Gestionar estado" }));
    const form = screen.getByRole("form", { name: "Gestionar estado suscripción Toku" });
    await listSettled();
    expect(Array.from(form.querySelectorAll('[name="status"] option')).map((o) => o.getAttribute("value"))).toEqual(["", "ACTIVE", "PAUSED"]);
    expect(within(form).getByText(/«Solicitar baja»/)).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "Volver" }));
    expect(screen.queryByRole("button", { name: "Eliminar" })).toBeNull();
  });

  it("ficha de un cliente Toku: la suscripción relacionada no ofrece «Eliminar» al no admin", async () => {
    const detail = { record: tokuCustomer(1), related: [{ label: "Suscripciones", resource_type: "subscription", items: [tokuSubscription(1)] }] };
    mountApp("/toku/clientes/tcu-1", [listHandler, ["GET", "/api/v1/staging/toku/customer/tcu-1", detail]], NON_ADMIN);
    await appReady();
    await screen.findByText("FICHA COMPLETA");
    // Solo queda el «Eliminar» del propio cliente; el de la suscripción relacionada se reemplaza por el texto.
    expect(screen.getAllByRole("button", { name: "Eliminar" })).toHaveLength(1);
    expect(screen.getByTestId("direct-cancel-note")).toBeTruthy();
  });

  it("el admin sigue viendo «Eliminar» en suscripciones y la opción «Cancelada» de Toku", async () => {
    mountApp("/toku/suscripciones/tsu-1", [listHandler, ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1), related: [] }]], ADMIN);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Gestionar estado" }));
    const form = screen.getByRole("form", { name: "Gestionar estado suscripción Toku" });
    await waitFor(() => expect(Array.from(form.querySelectorAll('[name="status"] option')).map((o) => o.getAttribute("value"))).toEqual(["", "ACTIVE", "PAUSED", "CANCELLED"]));
    expect(screen.queryByTestId("direct-cancel-note")).toBeNull();
  });
});
