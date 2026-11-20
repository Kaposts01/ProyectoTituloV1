/** PERF-03 (H3 y H4): el alto reservado de un listado se ajusta al tamaño esperado y se suelta con cualquier respuesta. Datos sintéticos. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import "./UnifiedSubscriptionsView";
import { appReady, failWith, mountApp, resetApp, type Handler } from "../../test/appHarness";
import { DEFAULT_PAGE_ROWS, pageReserve, resetPageReserve } from "./pageReserve";

beforeEach(resetPageReserve);
afterEach(resetApp);

const one = { channel: "virtualpos1", subscription_id: "DEMO-VP-1", status: "ACTIVA", secondary_status: "cobrable", start_date: "2026-01-10", end_date: null, amount: "5000", currency: "CLP", last_charge: null, rut: "11111111-1", name: "DEMO Uno" };
const statuses: Handler = ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [], canales: [] }];
const rowsVar = (el: HTMLElement) => el.style.getPropertyValue("--page-rows");

describe("pageReserve", () => {
  it("reserva una página completa la primera vez y las filas de la última respuesta después", () => {
    expect(pageReserve("a", null).style).toMatchObject({ "--page-rows": DEFAULT_PAGE_ROWS });
    expect(pageReserve("a", { items: new Array(12).fill(0) }).className).toBe("table-wrap");
    expect(pageReserve("a", null).style).toMatchObject({ "--page-rows": 12 });
    pageReserve("a", { items: [] });
    expect(pageReserve("a", null).style).toMatchObject({ "--page-rows": 3 });
    expect(pageReserve("b", null).style).toMatchObject({ "--page-rows": DEFAULT_PAGE_ROWS });
  });
});

describe("Suscripciones: alto reservado según la respuesta anterior y suelta ante error", () => {
  it("una segunda visita reserva solo las filas que trajo la primera", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", { items: [one], total: 1, offset: 0, limit: 50, by_channel: {}, canales: [] }], statuses]);
    await appReady();
    await screen.findByText("DEMO Uno");
    resetApp();
    mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", () => new Promise(() => undefined)], statuses]);
    await appReady();
    const table = await screen.findByTestId("subscriptions-table");
    expect(table.getAttribute("aria-busy")).toBe("true");
    expect(rowsVar(table)).toBe("3");
  });

  it("con error de la API suelta el aria-busy y la clase de reserva queda sin efecto", async () => {
    mountApp("/central/suscripciones", [["GET", "/api/v1/general/subscriptions", failWith(500, "falla sintética")], statuses]);
    await appReady();
    await screen.findByRole("alert");
    const table = screen.getByTestId("subscriptions-table");
    expect(table.getAttribute("aria-busy")).toBe("false");
  });
});

describe("Clientes: aria-busy no queda pegado si falla la petición", () => {
  it("baja el aria-busy y avisa el error", async () => {
    mountApp("/central/clientes", [["GET", "/api/v1/staging/dashboard/general/clients", failWith(500, "falla sintética")]]);
    await appReady();
    await waitFor(() => expect(document.querySelector(".table-wrap-page")).toBeTruthy());
    const wrap = document.querySelector(".table-wrap-page") as HTMLElement;
    await waitFor(() => expect(wrap.getAttribute("aria-busy")).toBe("false"));
  });
});

describe("H3: el alto mínimo de 360 px ya no es global", () => {
  it("App.css lo limita a .table-wrap-tall", () => {
    const css = readFileSync(resolve(__dirname, "../../App.css"), "utf8");
    expect(css).not.toMatch(/\.table-wrap\[aria-busy="true"\]\s*\{\s*min-height:\s*360px/);
    expect(css).toMatch(/\.table-wrap-tall\[aria-busy="true"\]\s*\{\s*min-height:\s*360px/);
  });
});
