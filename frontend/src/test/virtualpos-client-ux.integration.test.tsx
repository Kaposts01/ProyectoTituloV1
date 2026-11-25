import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, failWith, mountApp, resetApp, type Handler } from "./appHarness";
import { page, vpClient, vpSubscription, vpCharge, vpPayment } from "./fixtures";

afterEach(resetApp);
const client = vpClient(1);
const body = { client, subscriptions: [vpSubscription(1)], subscription_total: 1, charges: [vpCharge(1, "pendiente")], charge_total: 1, payments: [vpPayment(1)], payment_total: 1 };
const detail: Handler = ["GET", "/api/v1/staging/virtualpos/clients/cli-1", body];
const readOnly = { permissions: ["virtualpos.clients.view"], roles: ["ejecutivo"] };

describe("Clientes VirtualPOS: consulta ejecutiva", () => {
  it("abre por nombre, enfoca la ficha y respeta permisos de edición y recursos relacionados", async () => {
    const app = mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", page([client])], detail], readOnly);
    await appReady();
    expect(screen.queryByRole("button", { name: /Editar|Nuevo cliente/ })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cliente Persona1 Sintética" }));
    const heading = await screen.findByRole("heading", { name: "Persona1 Sintética" });
    expect(heading).toHaveFocus();
    expect(screen.queryByRole("button", { name: /Editar cliente|Cancelar|sub-1|chg-1|pay-1|Plan Sintético/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Volver a clientes VirtualPOS" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cliente Persona1 Sintética" })).toHaveFocus());
    expect(app.calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("combina nombre y RUT, conserva filtros plegados y los quita sin publicar búsquedas personales", async () => {
    const app = mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", page([client])]], readOnly);
    await appReady();
    await screen.findByRole("button", { name: "Ver cliente Persona1 Sintética" });
    fireEvent.change(await screen.findByLabelText("Nombre del cliente"), { target: { value: "Persona" } });
    fireEvent.change(screen.getByLabelText("RUT o documento"), { target: { value: "11111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Más filtros" }));
    fireEvent.change(screen.getByLabelText("Correo electrónico"), { target: { value: "example.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Más filtros (1)" }));
    await waitFor(() => expect(app.exact("GET", "/api/v1/staging/records").at(-1)!.query.getAll("filters")).toEqual(["name:Persona", "social_id:11111111", "email:example.invalid"]));
    expect(screen.getByRole("button", { name: "Quitar filtro Correo electrónico" })).toBeVisible();
    expect(window.location.search).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Quitar filtro Correo electrónico" }));
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    await waitFor(() => expect(app.exact("GET", "/api/v1/staging/records").at(-1)!.query.has("filters")).toBe(false));
  });

  it("bloquea filas anteriores, exportación y paginación durante debounce y error; reintenta conservando criterios", async () => {
    let failing = false;
    const app = mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", () => failing ? failWith(503, "Consulta temporalmente no disponible") : page([client], 120)]], readOnly);
    await appReady();
    const open = await screen.findByRole("button", { name: "Ver cliente Persona1 Sintética" });
    await waitFor(() => expect(open).not.toBeDisabled());
    failing = true;
    fireEvent.change(await screen.findByLabelText("Nombre del cliente"), { target: { value: "Persona" } });
    expect(open).toBeDisabled();
    expect(screen.getByRole("button", { name: /Exportar/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Cargando/ })).toBeDisabled();
    await screen.findByRole("alert");
    expect(open).toBeDisabled();
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
    await waitFor(() => expect(open).not.toBeDisabled());
    expect(screen.getByLabelText("Nombre del cliente")).toHaveValue("Persona");
    expect(app.calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("conserva búsqueda, cuenta, orden y posición al volver y espera una respuesta nueva", async () => {
    let returning = false;
    let resolve: ((value: unknown) => void) | undefined;
    const app = mountApp("/virtualpos/clientes?cuenta=virtualpos1&orden=Nombre&direccion=desc", [["GET", "/api/v1/staging/records", () => returning ? new Promise((done) => { resolve = done; }) : page([client])], detail], readOnly);
    await appReady();
    fireEvent.change(await screen.findByLabelText("Nombre del cliente"), { target: { value: "Persona" } });
    await waitFor(() => expect(app.exact("GET", "/api/v1/staging/records").at(-1)!.query.getAll("filters")).toEqual(["name:Persona"]));
    const scroll = document.querySelector(".channel-table-scroll")!;
    scroll.scrollTop = 60; scroll.scrollLeft = 100;
    fireEvent.click(screen.getByRole("button", { name: "Ver cliente Persona1 Sintética" }));
    await screen.findByRole("heading", { name: "Persona1 Sintética" });
    returning = true;
    fireEvent.click(screen.getByRole("button", { name: "Volver a clientes VirtualPOS" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    expect(screen.getByRole("button", { name: "Ver cliente Persona1 Sintética" })).toBeDisabled();
    resolve!(page([client]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cliente Persona1 Sintética" })).toHaveFocus());
    expect(screen.getByLabelText("Nombre del cliente")).toHaveValue("Persona");
    expect(document.querySelector(".channel-table-scroll")!.scrollTop).toBe(60);
    expect(document.querySelector(".channel-table-scroll")!.scrollLeft).toBe(100);
    const query = app.exact("GET", "/api/v1/staging/records").at(-1)!.query;
    expect([query.get("source"), query.get("sort_field"), query.get("sort_direction")]).toEqual(["virtualpos1", "name", "desc"]);
  });

  it("distingue filtros sin coincidencias y deja limpiar aunque no haya tabla", async () => {
    mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", page([])]], readOnly);
    await appReady();
    await screen.findByText("No hay clientes registrados en esta cuenta o canal.");
    fireEvent.change(screen.getByLabelText("Nombre del cliente"), { target: { value: "NO-EXISTE" } });
    await screen.findByText("No hay clientes que coincidan con estos filtros.");
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    await screen.findByText("No hay clientes registrados en esta cuenta o canal.");
  });

  it("recupera un error de ficha sin confundirlo con el listado", async () => {
    let failing = true;
    mountApp("/virtualpos/clientes/cli-1", [["GET", "/api/v1/staging/records", page([client])], ["GET", "/api/v1/staging/virtualpos/clients/cli-1", () => failing ? failWith(503, "Ficha no disponible temporalmente") : body]], readOnly);
    await appReady();
    await screen.findByRole("heading", { name: "Ficha de cliente no disponible" });
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar ficha" }));
    await screen.findByRole("heading", { name: "Persona1 Sintética" });
  });

  it("permite salir durante la carga y descarta la respuesta tardía", async () => {
    let resolve: ((value: unknown) => void) | undefined;
    mountApp("/virtualpos/clientes", [["GET", "/api/v1/staging/records", page([client])], ["GET", "/api/v1/staging/virtualpos/clients/cli-1", () => new Promise((done) => { resolve = done; })]], readOnly);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cliente Persona1 Sintética" }));
    await screen.findByText("Cargando ficha...");
    fireEvent.click(screen.getByRole("button", { name: "Volver a clientes VirtualPOS" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    resolve!(body);
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cliente Persona1 Sintética" })).toHaveFocus());
    expect(screen.queryByText("FICHA DEL CLIENTE")).toBeNull();
    expect(window.location.pathname).toBe("/virtualpos/clientes");
  });
});
