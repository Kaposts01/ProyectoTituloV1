import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, failWith, mountApp, resetApp, type Handler } from "./appHarness";
import { page, vpCharge, vpClient, vpSubscription } from "./fixtures";

afterEach(resetApp);
const charge = vpCharge(1, "pendiente");
const detail: Handler = ["GET", "/api/v1/staging/virtualpos/charges/chg-1", { charge, client: vpClient(1), subscription: vpSubscription(1), payment: null }];
const readOnly = { permissions: ["virtualpos.charges.view"], roles: ["ejecutivo"] };

describe("Cargos VirtualPOS: consulta ejecutiva", () => {
  it("ofrece la ficha del cargo y no ofrece cancelación ni accesos a recursos sin permiso", async () => {
    mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", page([charge])], detail], readOnly);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cargo chg-1" }));
    const heading = await screen.findByRole("heading", { name: "chg-1" });
    expect(heading).toHaveFocus();
    expect(screen.queryByRole("button", { name: /Cancelar|Reintentar en VP/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Persona1 Sintética" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Plan Sintético 1" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Volver a cargos VirtualPOS" }));
    expect(await screen.findByRole("button", { name: "Ver cargo chg-1" })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Cancelar" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Ver ficha de suscripción/ })).toBeNull();
    expect(screen.getByText("05-04-2025")).toBeTruthy();
  });

  it("bloquea exportación, paginación y ficha desde el primer cambio de filtro y permite reintentar un error", async () => {
    let mode = "normal";
    let resolve: ((value: unknown) => void) | undefined;
    const app = mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", () => mode === "pending" ? new Promise((done) => { resolve = done; }) : page([charge], 120)]], readOnly);
    await appReady();
    const open = await screen.findByRole("button", { name: "Ver cargo chg-1" });
    await waitFor(() => expect(open).not.toBeDisabled());
    mode = "pending";
    fireEvent.change(screen.getByLabelText("Buscar por ID de suscripción"), { target: { value: "NO-EXISTE" } });
    expect(open).toBeDisabled();
    expect(screen.getByRole("button", { name: /Exportar/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Cargando/ })).toBeDisabled();
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    resolve!(failWith(503, "Servicio temporalmente no disponible"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(open).toBeDisabled();
    mode = "normal";
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
    await waitFor(() => expect(open).not.toBeDisabled());
    expect(screen.getByLabelText("Buscar por ID de suscripción")).toHaveValue("NO-EXISTE");
    expect(app.exact("GET", "/api/v1/staging/records").at(-1)!.query.getAll("filters")).toEqual(["subscription_id:NO-EXISTE"]);
    expect(window.location.search).not.toContain("NO-EXISTE");
    expect(app.calls.filter((call) => call.method !== "GET")).toHaveLength(0);
  });

  it("conserva criterios al plegar filtros y al volver de la ficha, junto con orden y cuenta", async () => {
    const app = mountApp("/virtualpos/cargos?cuenta=virtualpos1&orden=Monto&direccion=desc", [["GET", "/api/v1/staging/records", page([charge])], detail], readOnly);
    await appReady();
    await screen.findByRole("button", { name: "Ver cargo chg-1" });
    fireEvent.click(screen.getByRole("button", { name: "Más filtros" }));
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "pendiente" } });
    fireEvent.change(screen.getByLabelText("Fecha de cargo desde"), { target: { value: "2025-04-01" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Más filtros (2)" }));
    expect(screen.getByRole("button", { name: "Quitar filtro Estado" })).toHaveTextContent("pendiente");
    fireEvent.click(screen.getByRole("button", { name: "Ver cargo chg-1" }));
    await screen.findByRole("heading", { name: "chg-1" });
    fireEvent.click(screen.getByRole("button", { name: "Volver a cargos VirtualPOS" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).toHaveFocus());
    const query = app.exact("GET", "/api/v1/staging/records").at(-1)!.query;
    expect(query.getAll("filters")).toEqual(["status:pendiente"]);
    expect(query.get("date_from")).toBe("2025-04-01");
    expect(query.get("source")).toBe("virtualpos1");
    expect(query.get("sort_field")).toBe("amount");
    expect(query.get("sort_direction")).toBe("desc");
  });

  it("distingue una consulta sin coincidencias de un canal sin cargos", async () => {
    mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", page([])]], readOnly);
    await appReady();
    expect(await screen.findByText("No hay cargos registrados en esta cuenta o canal.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Buscar por ID de suscripción"), { target: { value: "NO-EXISTE" } });
    expect(await screen.findByText("No hay cargos que coincidan con estos filtros.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    expect(await screen.findByText("No hay cargos registrados en esta cuenta o canal.")).toBeTruthy();
  });

  it("un error de ficha conserva salida y reintento, sin mostrar el listado bajo la URL de ficha", async () => {
    let failed = true;
    mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", page([charge])],
      ["GET", "/api/v1/staging/virtualpos/charges/chg-1", () => failed ? failWith(503, "Ficha temporalmente no disponible") : detail[2]]], readOnly);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cargo chg-1" }));
    expect(await screen.findByRole("heading", { name: "Ficha de cargo no disponible" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ver cargo chg-1" })).toBeNull();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar ficha" }));
    expect(await screen.findByRole("heading", { name: "chg-1" })).toHaveFocus();
  });

  it("permite volver durante la carga y descarta una respuesta de ficha tardía", async () => {
    let resolve: ((value: unknown) => void) | undefined;
    mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", page([charge])],
      ["GET", "/api/v1/staging/virtualpos/charges/chg-1", () => new Promise((done) => { resolve = done; })]], readOnly);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cargo chg-1" }));
    await screen.findByText("Cargando ficha...");
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    fireEvent.click(screen.getByRole("button", { name: "Volver a cargos VirtualPOS" }));
    await screen.findByRole("button", { name: "Ver cargo chg-1" });
    resolve!(detail[2]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).toHaveFocus());
    expect(screen.queryByText("FICHA DEL CARGO")).toBeNull();
    expect(window.location.pathname).toBe("/virtualpos/cargos");
  });

  it("espera la nueva respuesta al volver aunque los criterios coincidan con una consulta previa", async () => {
    let returning = false;
    let resolve: ((value: unknown) => void) | undefined;
    mountApp("/virtualpos/cargos", [["GET", "/api/v1/staging/records", () => returning ? new Promise((done) => { resolve = done; }) : page([charge])], detail], readOnly);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Ver cargo chg-1" }));
    await screen.findByRole("heading", { name: "chg-1" });
    returning = true;
    fireEvent.click(screen.getByRole("button", { name: "Volver a cargos VirtualPOS" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).toBeDisabled();
    resolve!(page([charge]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ver cargo chg-1" })).toHaveFocus());
  });
});
