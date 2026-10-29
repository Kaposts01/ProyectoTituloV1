/**
 * Caracterización de las fichas de detalle de AppCore (VirtualPOS: cliente, plan, suscripción,
 * cargo y transacción; Toku/Payku: ficha genérica). UX-04. Datos sintéticos.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, failWith, mountApp, resetApp, type Handler } from "./appHarness";
import { page, rec, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPayment, vpPlan, vpSubscription } from "./fixtures";

afterEach(resetApp);

const listHandler: Handler = ["GET", "/api/v1/staging/records", page([])];

const clientDetail = {
  client: vpClient(1), subscriptions: [vpSubscription(1), vpSubscription(2, { status: "CANCELADA" })], subscription_total: 2,
  charges: [vpCharge(1, "pendiente")], charge_total: 1, payments: [vpPayment(1)], payment_total: 1,
};
const planDetail = { plan: vpPlan(1), subscriptions: [vpSubscription(1, { client: { first_name: "Persona", last_name: "Uno" } })], subscription_total: 1 };
const subscriptionDetail = {
  subscription: vpSubscription(1, { plan_id: "plan-1" }),
  payment_method: { card_type: "CREDITO", brand: "VISA", last4: "0000", bin: "000000" },
  charges: [vpCharge(1, "pendiente"), vpCharge(2, "rechazado"), vpCharge(3, "pagado")], charge_total: 3,
  payments: [vpPayment(1)], payment_total: 1,
};
const chargeDetail = { charge: vpCharge(1, "pendiente"), subscription: vpSubscription(1), client: vpClient(1), payment: vpPayment(1) };
const paymentDetail = { payment: vpPayment(1), charge: vpCharge(1, "pagado"), subscription: vpSubscription(1), client: vpClient(1) };

describe("Ficha de cliente VirtualPOS (/virtualpos/clientes/{id})", () => {
  it("pide la ficha y muestra datos, suscripciones, cargos y transacciones con sus acciones", async () => {
    const app = mountApp("/virtualpos/clientes/cli-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/clients/cli-1", clientDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA DEL CLIENTE")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/clients/cli-1")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS / CLIENTE")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Persona1 Sintética" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Editar" })).toBeTruthy();
    expect(screen.getByText("Relacionadas por RUT")).toBeTruthy();
    expect(screen.getByText("2 total")).toBeTruthy();
    expect(screen.getByText("Cobros generados por suscripción")).toBeTruthy();
    expect(screen.getByText("Pagos procesados")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Cancelar" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Plan Sintético 1" })).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("el enlace de una suscripción navega a su ficha y «Volver» regresa a la lista de clientes", async () => {
    const app = mountApp("/virtualpos/clientes/cli-1", [
      listHandler,
      ["GET", "/api/v1/staging/virtualpos/clients/cli-1", clientDetail],
      ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", subscriptionDetail],
    ]);
    await appReady();
    await screen.findByText("FICHA DEL CLIENTE");
    fireEvent.click(screen.getByRole("button", { name: "sub-1" }));
    await waitFor(() => expect(window.location.pathname).toBe("/virtualpos/suscripciones/sub-1"));
    expect(await screen.findByText("FICHA DE LA SUBSCRIPCIÓN")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/subscriptions/sub-1")).toHaveLength(1);
    fireEvent.click(screen.getByText("Volver al listado VirtualPOS"));
    await waitFor(() => expect(window.location.pathname).toBe("/virtualpos/suscripciones"));
  });

  it("si falla la ficha muestra el error en la lista", async () => {
    mountApp("/virtualpos/clientes/cli-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/clients/cli-1", failWith(404, "no existe")]]);
    await appReady();
    expect(await screen.findByText("no existe")).toBeTruthy();
  });

  it("mientras llega la ficha muestra «Cargando ficha...»", async () => {
    mountApp("/virtualpos/clientes/cli-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/clients/cli-1", () => new Promise(() => {})]]);
    await appReady();
    expect(await screen.findByText("Cargando ficha...")).toBeTruthy();
  });
});

describe("Ficha de plan VirtualPOS (/virtualpos/planes/{id})", () => {
  it("pide la ficha y muestra el plan y sus suscripciones", async () => {
    const app = mountApp("/virtualpos/planes/plan-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/plans/plan-1", planDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA DEL PLAN")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/plans/plan-1")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS / PLAN")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Plan Sintético 1" })).toBeTruthy();
    expect(screen.getByText("Asociadas al plan")).toBeTruthy();
    expect(screen.getAllByText("Abrir enlace").length).toBe(1);
    expect(screen.getByRole("button", { name: "sub-1" })).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });
});

describe("Ficha de suscripción VirtualPOS (/virtualpos/suscripciones/{id})", () => {
  it("muestra ficha, método de pago sin datos de tarjeta, cargos con acciones por estado y transacciones", async () => {
    const app = mountApp("/virtualpos/suscripciones/sub-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", subscriptionDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA DE LA SUBSCRIPCIÓN")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/subscriptions/sub-1")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS / SUBSCRIPCIÓN")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancelar Sub" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Nuevo cargo" })).toBeTruthy();
    expect(screen.getByText("MÉTODO DE PAGO")).toBeTruthy();
    expect(screen.queryByText("0000")).toBeNull();
    expect(screen.getByRole("button", { name: "Plan Sintético 1" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Cancelar" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Reintentar" })).toHaveLength(1);
    expect(screen.getByText(/VirtualPOS no entrega un identificador de subscripción/)).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("una suscripción cancelada no ofrece «Cancelar Sub» ni «+ Nuevo cargo»", async () => {
    mountApp("/virtualpos/suscripciones/sub-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", { ...subscriptionDetail, subscription: vpSubscription(1, { status: "CANCELADA" }) }]]);
    await appReady();
    await screen.findByText("FICHA DE LA SUBSCRIPCIÓN");
    expect(screen.queryByRole("button", { name: "Cancelar Sub" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Nuevo cargo" })).toBeNull();
  });

  it("sin método de pago muestra «Sin método de pago disponible en staging.»", async () => {
    mountApp("/virtualpos/suscripciones/sub-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", { ...subscriptionDetail, payment_method: null }]]);
    await appReady();
    expect(await screen.findByText("Sin método de pago disponible en staging.")).toBeTruthy();
  });
});

describe("Ficha de cargo y de transacción VirtualPOS", () => {
  it("cargo pendiente: ficha, acción «Cancelar en VP» y relaciones", async () => {
    const app = mountApp("/virtualpos/cargos/chg-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/charges/chg-1", chargeDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA DEL CARGO")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/charges/chg-1")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS / CARGO")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancelar en VP" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reintentar en VP" })).toBeNull();
    expect(screen.getByText("RELACIONES")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Persona1 Sintética" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "pay-1" })).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("cargo rechazado: «Reintentar en VP» solo con permiso", async () => {
    const rejected = { ...chargeDetail, charge: vpCharge(2, "rechazado") };
    mountApp("/virtualpos/cargos/chg-2", [listHandler, ["GET", "/api/v1/staging/virtualpos/charges/chg-2", rejected]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Reintentar en VP" })).toBeTruthy();
    resetApp();
    mountApp("/virtualpos/cargos/chg-2", [listHandler, ["GET", "/api/v1/staging/virtualpos/charges/chg-2", rejected]], { permissions: ["dashboard.view", "virtualpos.charges.view"] });
    await appReady();
    await screen.findByText("FICHA DEL CARGO");
    expect(screen.queryByRole("button", { name: "Reintentar en VP" })).toBeNull();
  });

  it("transacción: ficha con campos anidados, botón Eliminar y relaciones", async () => {
    const app = mountApp("/virtualpos/transacciones/pay-1", [listHandler, ["GET", "/api/v1/staging/virtualpos/payments/pay-1", paymentDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA DE LA TRANSACCIÓN")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/virtualpos/payments/pay-1")).toHaveLength(1);
    expect(screen.getByText("VIRTUALPOS / TRANSACCIÓN")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "ord-1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Eliminar" })).toBeTruthy();
    expect(screen.getByText("RELACIONES")).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });
});

describe("Ficha de registro Toku/Payku (/toku/clientes/{id})", () => {
  const customerDetail = {
    record: tokuCustomer(1),
    related: [
      { label: "Suscripciones", resource_type: "subscription", items: [tokuSubscription(1)] },
      { label: "Facturas", resource_type: "invoice", items: [] },
    ],
  };

  it("pide /staging/{canal}/{recurso}/{id} y muestra ficha completa, grupos relacionados y acciones", async () => {
    const app = mountApp("/toku/clientes/tcu-1", [listHandler, ["GET", "/api/v1/staging/toku/customer/tcu-1", customerDetail]]);
    await appReady();
    expect(await screen.findByText("FICHA COMPLETA")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/toku/customer/tcu-1")).toHaveLength(1);
    expect(screen.getByText("Volver al listado Toku")).toBeTruthy();
    expect(screen.getByText("TOKU / CLIENTE")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Editar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Eliminar" })).toBeTruthy();
    expect(screen.getByText("SUSCRIPCIONES")).toBeTruthy();
    expect(screen.getByText("Sin registros relacionados.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Gestionar estado" })).toBeTruthy();
    expect(contentHtml()).toMatchSnapshot();
  });

  it("la ficha de una suscripción Toku ofrece «Gestionar estado» y la de un método de pago muestra su perfil", async () => {
    mountApp("/toku/suscripciones/tsu-1", [listHandler, ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1), related: [] }]]);
    await appReady();
    expect(await screen.findByRole("button", { name: "Gestionar estado" })).toBeTruthy();
    resetApp();
    const method = rec("toku", "payment_method", "tpm-1", { id: "tpm-1", status: "active", payment_method: { id: "tpm-1", status: "active", card: { card_brand: "visa", last_digits: "0000", bank_name: "Banco Sintético", card_type: "credit" } } });
    mountApp("/toku/metodos-pago/tpm-1", [listHandler, ["GET", "/api/v1/staging/toku/payment_method/tpm-1", { record: method, related: [] }]]);
    await appReady();
    expect(await screen.findByText("TOKU / MÉTODO DE PAGO")).toBeTruthy();
    expect(screen.queryByText("FICHA COMPLETA")).toBeNull();
  });
});
