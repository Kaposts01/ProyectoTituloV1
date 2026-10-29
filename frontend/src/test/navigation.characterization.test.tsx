/**
 * Caracterización de la sesión, el tema y la navegación por URL que AppCore conserva (UX-04):
 * red de seguridad previa a UX-05 (nueva navegación). Datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { appReady, failWith, mountApp, navDetail, navTop, resetApp, type Handler } from "./appHarness";
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

describe("Menú lateral (un solo nivel, UX-05)", () => {
  const tchSummary: Handler = ["GET", "/api/v1/tch/summary", { suscripciones: { vigentes: 0, eliminadas: 0, total: 0, monto_vigentes: 0, monto_eliminadas: 0, monto_total: 0 }, transacciones: { total: 0, aceptadas: 0, rechazadas: 0, tasa_rechazo_pct: null, monto: 0 }, kpis: { mrr: 0, arpu: null, active_clients: 0, active_subscribers: 0, churn_rate: null, ltv: null }, years: [], ultimo_etl: { id: null, status: null, started_at: null, records_upserted: null } }];
  const emptyPage = { items: [], total: 0, offset: 0, limit: 50 };

  // Cambio deliberado: los rótulos pasan a Resumen / Socios / Suscripciones / Reportes (antes Dashboard / Clientes /
  // Suscripciones / Reporte automático) y TCH vive en «Detalle por canal»; las URL no cambian.
  it("los accesos del menú navegan a la URL correspondiente", async () => {
    mountApp("/central/resumen", [
      listHandler,
      tchSummary,
      ["GET", "/api/v1/staging/dashboard/general/subscriptions", page([])],
      ["GET", "/api/v1/staging/dashboard/general/clients", page([])],
      ["GET", /^\/api\/v1\/(billing|recovery)\//, emptyPage],
      ["GET", /^\/api\/v1\/(users|roles|permissions)/, []],
    ]);
    await appReady();
    fireEvent.click(navTop("Suscripciones"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/suscripciones"));
    fireEvent.click(navTop("Socios"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/clientes"));
    fireEvent.click(navTop("Reportes"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/reporte-automatico"));
    fireEvent.click(navTop("Resumen"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    fireEvent.click(navTop("Recuperador"));
    await waitFor(() => expect(window.location.pathname).toBe("/virtualpos/recuperador-socios"));
    fireEvent.click(navTop("Cambios de cobro"));
    await waitFor(() => expect(window.location.pathname).toBe("/general/cambios-de-cobro"));
    fireEvent.click(navTop("Sincronización"));
    await waitFor(() => expect(window.location.pathname).toBe("/admin/sincronizaciones"));
    fireEvent.click(navTop("Administración"));
    await waitFor(() => expect(window.location.pathname).toBe("/admin/usuarios"));
  });

  it("«Detalle por canal» arranca plegado, se abre a mano y sus accesos navegan", async () => {
    mountApp("/central/resumen", [listHandler, tchSummary, ["GET", "/api/v1/staging/dashboard/general/subscriptions", page([])]]);
    await appReady();
    const toggle = screen.getByRole("button", { name: /Detalle por canal/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(navDetail("TCH", "Resumen"));
    await waitFor(() => expect(window.location.pathname).toBe("/tch/resumen"));
    fireEvent.click(navDetail("TCH", "Transacciones"));
    await waitFor(() => expect(window.location.pathname).toBe("/tch/transacciones"));
    expect(navDetail("TCH", "Transacciones").getAttribute("aria-current")).toBe("page");
    fireEvent.click(navDetail("Toku", "Clientes"));
    await waitFor(() => expect(window.location.pathname).toBe("/toku/clientes"));
  });

  it("un enlace profundo a una pantalla de canal deja el detalle desplegado con su ítem activo", async () => {
    mountApp("/payku/planes", [listHandler]);
    await appReady();
    await waitFor(() => expect(screen.getByRole("button", { name: /Detalle por canal/ }).getAttribute("aria-expanded")).toBe("true"));
    expect(navDetail("Payku", "Planes").getAttribute("aria-current")).toBe("page");
  });

  it("el indicador de salud del encabezado es global y abre el detalle por canal", async () => {
    mountApp("/central/resumen", [
      listHandler,
      ["GET", "/api/v1/sync-runs/health", [
        { channel: "virtualpos", level: "ok", last_finished_at: "2026-10-29T00:00:00Z", age_hours: 3 },
        { channel: "toku", level: "warn", last_finished_at: "2026-10-28T00:00:00Z", age_hours: 30 },
      ]],
    ]);
    await appReady();
    const toggle = await screen.findByRole("button", { name: /Sincronización atrasada/ });
    expect(document.querySelectorAll('.health-dot[data-scope="global"]')).toHaveLength(1);
    fireEvent.click(toggle);
    const list = screen.getByRole("list", { name: "Sincronización por canal" });
    expect(within(list).getByText("Sincronizado: hace 3 h")).toBeTruthy();
    expect(within(list).getByText("Sincronización atrasada: hace 30 h")).toBeTruthy();
  });

  it("Cobros e Identidad no están en el menú (no existen sus vistas)", async () => {
    mountApp("/central/resumen", [listHandler]);
    await appReady();
    const nav = document.querySelector(".sidebar-nav") as HTMLElement;
    expect(within(nav).queryByRole("button", { name: "Cobros" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "Identidad" })).toBeNull();
  });

  it("sin permisos de canal el detalle no aparece, y el recuperador solo depende de su permiso", async () => {
    mountApp("/virtualpos/recuperador-socios", [["GET", /^\/api\/v1\/recovery\//, emptyPage]], { permissions: ["dashboard.view", "virtualpos.recovery.view"] });
    await appReady();
    expect(screen.queryByRole("button", { name: /Detalle por canal/ })).toBeNull();
    await waitFor(() => expect(navTop("Recuperador").getAttribute("aria-current")).toBe("page"));
    expect(screen.queryByRole("button", { name: "Cambios de cobro" })).toBeNull();
  });
});

describe("Resumen unificado y vista anterior (rutas del paso 3)", () => {
  const unifiedCalls = (app: ReturnType<typeof mountApp>) => app.exact("GET", "/api/v1/dashboard/general");
  const legacyCalls = (app: ReturnType<typeof mountApp>) => [...app.exact("GET", "/api/v1/staging/dashboard/general"), ...app.exact("GET", "/api/v1/staging/summary")];

  it("/central/resumen abre el Resumen unificado y no pide los datos del dashboard anterior", async () => {
    const app = mountApp("/central/resumen", [listHandler]);
    await appReady();
    await screen.findByRole("region", { name: "Indicadores del mes" });
    expect(screen.getByRole("heading", { level: 1, name: "Resumen" })).toBeTruthy();
    expect(unifiedCalls(app)).toHaveLength(1);
    expect(legacyCalls(app)).toHaveLength(0);
    expect(navTop("Resumen").getAttribute("aria-current")).toBe("page");
  });

  it("/central/resumen-clasico abre la vista anterior, que pide sus datos y no el endpoint nuevo", async () => {
    const app = mountApp("/central/resumen-clasico", [listHandler]);
    await appReady();
    expect(await screen.findByLabelText("Métricas generales")).toBeTruthy();
    expect(screen.getByText("RESUMEN OPERATIVO")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/staging/dashboard/general")).toHaveLength(1);
    expect(app.exact("GET", "/api/v1/staging/summary")).toHaveLength(1);
    expect(unifiedCalls(app)).toHaveLength(0);
    expect(window.location.pathname).toBe("/central/resumen-clasico");
    // fuera del menú: el ítem «Resumen» no queda marcado como activo en la vista anterior
    expect(navTop("Resumen").getAttribute("aria-current")).toBeNull();
  });

  it("desde la vista anterior, el menú «Resumen» lleva al Resumen unificado", async () => {
    const app = mountApp("/central/resumen-clasico", [listHandler]);
    await appReady();
    await screen.findByLabelText("Métricas generales");
    fireEvent.click(navTop("Resumen"));
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    await screen.findByRole("region", { name: "Indicadores del mes" });
    expect(unifiedCalls(app)).toHaveLength(1);
  });

  it("la vista anterior respeta el permiso dashboard.view: sin él vuelve al inicio del usuario", async () => {
    mountApp("/central/resumen-clasico", [listHandler], { permissions: ["toku.customers.view"] });
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/toku/clientes"));
  });
});
