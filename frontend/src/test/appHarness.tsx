/**
 * Arnés de pruebas de caracterización de AppCore: monta la aplicación completa
 * sobre una ruta, con `fetch` simulado por tabla de rutas y una sesión sintética.
 * No contiene datos personales: todo es ficticio.
 */
import { cleanup, configure, render, screen, waitFor } from "@testing-library/react";
import { expect, vi } from "vitest";
import AppCore from "../AppCore";
// VIZ-10: AppCore carga estas vistas con React.lazy. Se precargan aquí para que el `import()` de la prueba resuelva
// desde la caché de módulos y no dependa del tiempo de transformación (recharts tarda varios segundos en frío).
import "../AutomaticReport";
import "../features/admin/AdminPanel";
import "../features/billing/BillingInbox";
import "../features/cancellations/CancellationsInbox";
import "../features/dashboard/ChannelDashboardView";
import "../features/dashboard/GeneralDashboardView";
import "../features/recovery/RecoveryPanel";
import "../features/summary/SummaryView";
import "../features/tch/TchContent";
import { invalidateCache } from "../apiCache";
import { setCsrfToken } from "../api";
import { rawSummary } from "../features/summary/summaryFixtures";

// Las pruebas montan la aplicación completa; con la suite en paralelo 1 s de espera por defecto se queda corto.
configure({ asyncUtilTimeout: 4000 });

export const ALL_PERMISSIONS = [
  "dashboard.view",
  "virtualpos.clients.view", "virtualpos.plans.view", "virtualpos.subscriptions.view",
  "virtualpos.charges.view", "virtualpos.payments.view", "virtualpos.charges.cancel", "virtualpos.charges.retry",
  "virtualpos.recovery.view", "virtualpos.billing_changes.view",
  "toku.customers.view", "toku.subscriptions.view", "toku.payment_methods.view", "toku.invoices.view", "toku.transactions.view",
  "payku.clients.view", "payku.plans.view", "payku.subscriptions.view", "payku.transactions.view",
  "tch.dashboard.view", "tch.clientes.view", "tch.suscripciones.view", "tch.transacciones.view",
  "users.manage", "roles.manage", "sync_runs.view", "sync.run", "etl.run",
];

export type Call = { method: string; path: string; query: URLSearchParams; url: string; body: unknown };
export type Reply = unknown | { __status: number; body: unknown };
export type Handler = [method: string, match: string | RegExp, reply: Reply | ((call: Call) => Reply | Promise<Reply>)];

export const failWith = (status: number, detail: string | Record<string, unknown>): Reply => ({ __status: status, body: { detail } });

export function session(permissions: string[] = ALL_PERMISSIONS, roles: string[] = ["admin"]) {
  return {
    csrf_token: "csrf-sintetico",
    user: {
      id: "user-1",
      username: "operador.sintetico",
      is_active: true,
      roles: roles.map((name, index) => ({ id: `role-${index}`, name })),
      permissions,
    },
  };
}

function response(status: number, data: unknown) {
  return {
    ok: status < 400,
    status,
    headers: { get: (key: string) => (key.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => data,
  };
}

export interface Mounted {
  calls: Call[];
  /** Peticiones hechas con el método y el prefijo de ruta indicados. */
  find: (method: string, pathPrefix: string) => Call[];
  /** Peticiones a exactamente esa ruta (sin contar rutas que la tienen como prefijo). */
  exact: (method: string, path: string) => Call[];
}

/**
 * Instala `fetch` y monta `AppCore` en `path`. Los `handlers` propios se evalúan
 * antes que los valores por defecto (sesión, ambiente, salud de sincronización).
 */
export function mountApp(path: string, handlers: Handler[] = [], options: { permissions?: string[]; roles?: string[]; authFails?: boolean } = {}): Mounted {
  const calls: Call[] = [];
  const defaults: Handler[] = [
    ["GET", "/api/v1/auth/me", options.authFails ? failWith(401, "No autenticado") : session(options.permissions, options.roles)],
    ["GET", "/api/v1/system/environment", { app_env: "test", label: "Test", is_production: false }],
    ["GET", "/api/v1/sync-runs/health", []],
    // Resumen unificado (/central/resumen): respuesta sintética por defecto para no ensuciar las pruebas ajenas.
    ["GET", "/api/v1/dashboard/general", () => rawSummary()],
  ];
  const table = [...handlers, ...defaults];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    const parsed = new URL(url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown;
    if (typeof init?.body === "string") {
      try { body = JSON.parse(init.body); } catch { body = init.body; }
    }
    const call: Call = { method, path: parsed.pathname, query: parsed.searchParams, url, body };
    calls.push(call);
    const entry = table.find(([m, match]) => m === method && (typeof match === "string" ? match === parsed.pathname : match.test(parsed.pathname)));
    if (!entry) return response(404, { detail: `sin simular: ${method} ${parsed.pathname}` });
    const reply = await (typeof entry[2] === "function" ? (entry[2] as (c: Call) => Reply | Promise<Reply>)(call) : entry[2]);
    if (reply && typeof reply === "object" && "__file" in reply) {
      // Descarga (CSV): cuerpo de texto y, si se indica, el header Content-Disposition.
      const file = (reply as { __file: { text: string; disposition?: string } }).__file;
      return {
        ok: true,
        status: 200,
        headers: { get: (key: string) => (key.toLowerCase() === "content-disposition" ? file.disposition ?? null : key.toLowerCase() === "content-type" ? "text/csv; charset=utf-8" : null) },
        blob: async () => new Blob([file.text], { type: "text/csv" }),
      };
    }
    if (reply && typeof reply === "object" && "__status" in reply) {
      const failure = reply as { __status: number; body: unknown };
      return response(failure.__status, failure.body);
    }
    return response(200, reply);
  }));
  window.history.replaceState({}, "", path);
  render(<AppCore />);
  return { calls, find: (method, prefix) => calls.filter((c) => c.method === method && c.path.startsWith(prefix)), exact: (method, path) => calls.filter((c) => c.method === method && c.path === path) };
}

export function resetApp() {
  cleanup();
  vi.unstubAllGlobals();
  invalidateCache();
  setCsrfToken("");
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  window.history.replaceState({}, "", "/");
}

/** Espera a que la sesión cargue (la barra lateral ya está montada). */
export async function appReady() {
  await waitFor(() => expect(screen.queryByText("Verificando sesión...")).toBeNull());
}

export const synthetic = {
  rut1: "11111111-1",
  rut2: "22222222-2",
};

/** Normaliza lo que cambia entre corridas (ids de recharts, fecha de hoy en `min`). */
function normalizeHtml(html: string): string {
  return html
    .replace(/recharts\d+/g, "recharts#")
    .replace(/min="\d{4}-\d{2}-\d{2}"/g, 'min="HOY"')
    .replace(/\d{1,2}-\d{1,2}-\d{4}, \d{1,2}:\d{2}:\d{2}( [ap]\. ?m\.)?/g, "FECHA-HORA");
}

/** HTML del área de contenido (sin barra lateral), para comparar el marcado antes y después de mover código. */
export function contentHtml(): string {
  const layout = document.querySelector(".app-layout");
  const parts: string[] = [];
  layout?.childNodes.forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    if (node.matches(".burger-btn, .sidebar-overlay, aside.sidebar")) return;
    parts.push(node.outerHTML);
  });
  return normalizeHtml(parts.join("\n"));
}

/**
 * Ítem del menú lateral de un solo nivel (UX-05). Excluye el grupo transitorio «Detalle por canal»,
 * donde los rótulos se repiten por canal («Clientes», «Resumen»…); para esos usar `navDetail`.
 */
export function navTop(label: string): HTMLElement {
  const nav = document.querySelector(".sidebar-nav") as HTMLElement;
  const found = Array.from(nav.querySelectorAll(".sidebar-group:not(.sidebar-detail) .sidebar-item")).find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`Sin botón de menú «${label}»`);
  return found as HTMLElement;
}

/** Ítem de «Detalle por canal» (transitorio) de un canal: `navDetail("TCH", "Transacciones")`. Debe estar desplegado. */
export function navDetail(channel: string, label: string): HTMLElement {
  const group = Array.from(document.querySelectorAll('.sidebar-detail [role="group"]')).find((g) => g.getAttribute("aria-label") === channel);
  const found = group && Array.from(group.querySelectorAll(".sidebar-item")).find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`Sin botón de detalle «${channel} / ${label}»`);
  return found as HTMLElement;
}

/** Espera a que la lista de registros termine de cargar (el contador deja de decir «Cargando»). */
export async function listSettled() {
  await waitFor(() => expect(Array.from(document.querySelectorAll('[aria-live="polite"]')).some((el) => el.textContent === "Cargando")).toBe(false));
}
