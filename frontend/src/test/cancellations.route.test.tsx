/** Integración de la ruta /general/bajas con AppCore: permiso de lectura, redirección sin permiso y petición de la bandeja. */
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, mountApp, resetApp, type Handler } from "./appHarness";

afterEach(resetApp);

const listHandler: Handler = ["GET", "/api/v1/cancellations", { items: [], total: 0, limit: 25, offset: 0 }];

describe("ruta /general/bajas", () => {
  it("con el permiso de lectura abre la bandeja y consulta los pendientes", async () => {
    const app = mountApp("/general/bajas", [listHandler], { permissions: ["dashboard.view", "subscriptions.cancellation.view"] });
    await appReady();
    expect(await screen.findByRole("heading", { name: "Bajas" })).toBeTruthy();
    await waitFor(() => expect(app.exact("GET", "/api/v1/cancellations")).toHaveLength(1));
    expect(app.exact("GET", "/api/v1/cancellations")[0].query.getAll("status")).toEqual(["pending", "approved"]);
    expect(window.location.pathname).toBe("/general/bajas");
  });

  it("sin el permiso de lectura redirige a la primera vista disponible y no consulta las bajas", async () => {
    const app = mountApp("/general/bajas", [listHandler], { permissions: ["dashboard.view"] });
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    expect(screen.queryByRole("heading", { name: "Bajas" })).toBeNull();
    expect(app.exact("GET", "/api/v1/cancellations")).toHaveLength(0);
  });
});
