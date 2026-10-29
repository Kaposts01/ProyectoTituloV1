/**
 * Caracterización de la sesión, el tema y la navegación por URL que AppCore conserva (UX-04):
 * red de seguridad previa a UX-05 (nueva navegación). Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { appReady, failWith, mountApp, navTop, resetApp, type Handler } from "./appHarness";
import { page } from "./fixtures";

afterEach(resetApp);

const listHandler: Handler = ["GET", "/api/v1/staging/records", page([])];

describe("Sesión", () => {
  it("mientras verifica la sesión muestra «Verificando sesión...»", async () => {
    mountApp("/central/resumen", [["GET", "/api/v1/auth/me", () => new Promise(() => {})]]);
    expect(screen.getByText("Verificando sesión...")).toBeTruthy();
  });

  it("sin sesión muestra el formulario de ingreso y no pide datos", async () => {
    const app = mountApp("/central/resumen", [], { authFails: true });
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeTruthy();
    expect(screen.getByLabelText("Usuario")).toBeTruthy();
    expect(screen.getByLabelText("Contraseña")).toBeTruthy();
    expect(app.find("GET", "/api/v1/staging")).toHaveLength(0);
  });

  it("al ingresar con éxito muestra la aplicación", async () => {
    const app = mountApp("/central/resumen", [
      ["GET", "/api/v1/auth/me", failWith(401, "No autenticado")],
      ["POST", "/api/v1/auth/login", { csrf_token: "csrf-1", user: { id: "u1", username: "operador.sintetico", is_active: true, roles: [{ id: "r1", name: "admin" }], permissions: ["dashboard.view"] } }],
    ]);
    fireEvent.change(await screen.findByLabelText("Usuario"), { target: { value: "operador.sintetico" } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "clave-sintetica" } });
    fireEvent.submit(document.querySelector("form.login-form")!);
    await waitFor(() => expect(app.find("POST", "/api/v1/auth/login")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/auth/login")[0].body).toEqual({ username: "operador.sintetico", password: "clave-sintetica" });
    expect(await screen.findByRole("button", { name: "Cerrar sesión" })).toBeTruthy();
  });

  it("«Cerrar sesión» envía POST /auth/logout, vuelve al ingreso y deja la URL en /central/resumen", async () => {
    const app = mountApp("/toku/clientes", [listHandler, ["POST", "/api/v1/auth/logout", {}]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cerrar sesión" }));
    await waitFor(() => expect(app.find("POST", "/api/v1/auth/logout")).toHaveLength(1));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeTruthy();
    expect(window.location.pathname).toBe("/central/resumen");
  });
});

describe("Tema", () => {
  it("aplica el tema guardado en localStorage al <html> y el botón lo alterna y lo guarda", async () => {
    localStorage.setItem("crm-theme", "dark");
    mountApp("/toku/clientes", [listHandler]);
    await appReady();
    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).toBe("dark"));
    fireEvent.click(screen.getByRole("button", { name: "Cambiar tema" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("crm-theme")).toBe("light");
    expect(screen.getByText("Modo oscuro")).toBeTruthy();
  });

  it("sin valor guardado parte en claro", async () => {
    mountApp("/toku/clientes", [listHandler]);
    await appReady();
    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).toBe("light"));
  });
});

describe("Rutas y permisos", () => {
  it("una ruta que no existe vuelve a /central/resumen (reemplazando el historial)", async () => {
    mountApp("/ruta/que/no/existe", []);
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
  });

  it("sin permiso para la ruta pedida va a la primera sección permitida", async () => {
    mountApp("/central/resumen", [listHandler], { permissions: ["toku.customers.view"] });
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/toku/clientes"));
  });

  it("sin permiso alguno va a «Mi perfil»", async () => {
    mountApp("/central/resumen", [], { permissions: [] });
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/mi-perfil"));
    expect(await screen.findByRole("heading", { name: "Mi perfil" })).toBeTruthy();
  });

  it("la ruta antigua de cambios de cobro redirige a /general/cambios-de-cobro y abre la bandeja", async () => {
    mountApp("/virtualpos/cambios-de-cobro", [["GET", /^\/api\/v1\/billing\//, { items: [], total: 0, offset: 0, limit: 50 }]]);
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/general/cambios-de-cobro"));
    expect(await screen.findByRole("heading", { name: "Cambios de cobro" })).toBeTruthy();
  });

  it("el recuperador de VirtualPOS abre en /virtualpos/recuperador-socios", async () => {
    mountApp("/virtualpos/recuperador-socios", [["GET", /^\/api\/v1\/recovery\//, { items: [], total: 0, offset: 0, limit: 50 }]]);
    await appReady();
    expect(await screen.findByRole("heading", { name: "Recuperador de Socios" })).toBeTruthy();
  });

  it("«Mi perfil» muestra al usuario y /admin/usuarios abre el panel de administración", async () => {
    mountApp("/mi-perfil", []);
    await appReady();
    expect(await screen.findByRole("heading", { name: "Mi perfil" })).toBeTruthy();
    expect(screen.getAllByText("operador.sintetico").length).toBeGreaterThan(0);
    resetApp();
    mountApp("/admin/usuarios", [["GET", /^\/api\/v1\/(users|roles|permissions)/, []]]);
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/admin/usuarios"));
    expect(document.querySelector(".app-layout main")).toBeTruthy();
  });

  it("el botón Atrás (popstate) cambia de vista según la URL", async () => {
    mountApp("/toku/clientes", [listHandler, ["GET", "/api/v1/staging/dashboard/toku", { source: "toku", records: 0, resources: {}, resource_amounts: {}, statuses: [], activity_resource: "transaction", activity: [], years: [], last_sync: null }]]);
    await appReady();
    await screen.findByText("TOKU / STAGING");
    act(() => {
      window.history.pushState({}, "", "/toku/resumen");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(await screen.findByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    expect(screen.queryByText("TOKU / STAGING")).toBeNull();
  });
});

describe("Menú lateral", () => {
  it("los accesos del menú navegan a la URL correspondiente", async () => {
    mountApp("/central/resumen", [
      listHandler,
      ["GET", "/api/v1/tch/summary", { suscripciones: { vigentes: 0, eliminadas: 0, total: 0, monto_vigentes: 0, monto_eliminadas: 0, monto_total: 0 }, transacciones: { total: 0, aceptadas: 0, rechazadas: 0, tasa_rechazo_pct: null, monto: 0 }, kpis: { mrr: 0, arpu: null, active_clients: 0, active_subscribers: 0, churn_rate: null, ltv: null }, years: [], ultimo_etl: { id: null, status: null, started_at: null, records_upserted: null } }],
      ["GET", "/api/v1/staging/dashboard/general/subscriptions", page([])],
    ]);
    await appReady();
    fireEvent.click(navTop("Suscripciones"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/suscripciones"));
    fireEvent.click(navTop("Reporte automático"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/reporte-automatico"));
    fireEvent.click(navTop("Dashboard"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    fireEvent.click(screen.getByRole("button", { name: "TCH" }));
    await waitFor(() => expect(window.location.pathname).toBe("/tch/resumen"));
    const group = Array.from(document.querySelectorAll(".sidebar-group")).find((g) => g.querySelector(".channel-dashboard")?.textContent === "TCH") as HTMLElement;
    fireEvent.click(within(group).getByRole("button", { name: "Transacciones" }));
    await waitFor(() => expect(window.location.pathname).toBe("/tch/transacciones"));
  });
});
