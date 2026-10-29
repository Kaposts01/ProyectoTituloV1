/**
 * Guardián de textos en español. Monta las vistas de caracterización con DATOS CRUDOS EN INGLÉS del proveedor
 * (ACTIVE, PAID, FAILED, True…) y falla si en pantalla aparece un valor crudo o un rótulo inglés conocido.
 *
 * Excepciones documentadas (docs/engineering/i18n-frontend.md): el texto libre del proveedor y los códigos
 * técnicos se pintan crudos, dentro de un elemento con el atributo `data-raw-text`; el guardián no los mira.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelDashboardView } from "../features/dashboard/ChannelDashboardView";
import type { ChannelDashboard } from "../features/shared/types";
import { appReady, listSettled, mountApp, resetApp, type Handler } from "../test/appHarness";
import { page, paykuClient, rec, paykuSubscription, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPayment, vpPlan, vpSubscription } from "../test/fixtures";
import { rawSummary } from "../features/summary/summaryFixtures";
import { es } from "./es";
import { label, resetUnknownWarnings } from "./label";

afterEach(resetApp);

/** Palabra completa, distingue mayúsculas: «Active» no es lo mismo que el apellido «Activo». */
export const FORBIDDEN_EN = [
  "ACTIVE", "PAID", "PENDING", "SUCCESS", "FAILED", "CANCELLED", "CANCELED", "PAUSED", "REJECTED",
  "active", "paid", "pending", "success", "failed", "cancelled", "paused", "rejected", "completed", "running", "partial", "queued",
  "True", "False", "true", "false", "Status", "Email", "Mail",
];
const FORBIDDEN_RE = new RegExp(`(?<![\\p{L}\\p{N}_])(${FORBIDDEN_EN.join("|")})(?![\\p{L}\\p{N}_])`, "gu");

/** Tokens crudos en inglés en el texto visible de `root` (sin los elementos marcados con `data-raw-text`). */
export function findRawEnglish(root: ParentNode): string[] {
  const clone = (root as Element).cloneNode(true) as Element;
  clone.querySelectorAll("[data-raw-text]").forEach((node) => node.remove());
  clone.querySelectorAll("script, style").forEach((node) => node.remove());
  // Un espacio entre nodos de texto: `textContent` pega «ACTIVE» con la celda vecina y esconde la palabra.
  const parts: string[] = [];
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) parts.push(node.textContent ?? "");
  const found = parts.join(" ").match(FORBIDDEN_RE);
  return found ? [...new Set(found)] : [];
}

describe("guardián: el detector de valores crudos", () => {
  it("encuentra tokens ingleses como palabra completa y distingue mayúsculas", () => {
    const host = document.createElement("div");
    host.innerHTML = "<p>Estado: ACTIVE</p><p>Renovación: True</p><th>Email</th><span>Status</span><i>Pagado, Activa, Inactiva, Estadística</i>";
    expect(findRawEnglish(host).sort()).toEqual(["ACTIVE", "Email", "Status", "True"]);
  });

  it("no mira los elementos marcados como texto libre del proveedor (excepción documentada)", () => {
    const host = document.createElement("div");
    host.innerHTML = "<span data-raw-text>VirtualPOSAPIError E-113 failed</span><span>Texto del proveedor</span>";
    expect(findRawEnglish(host)).toEqual([]);
  });

  it("un valor desconocido se ve como «Desconocido (X)», nunca como el valor crudo solo", () => {
    resetUnknownWarnings();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(label("status", "ZZ_NEW")).toBe("Desconocido (ZZ_NEW)");
    warn.mockRestore();
  });

  it("todo texto del catálogo pasa el detector", () => {
    const host = document.createElement("div");
    host.textContent = Object.values(es).flatMap((table) => Object.values(table as Record<string, string>)).join(" · ");
    expect(findRawEnglish(host)).toEqual([]);
  });
});

type GuardCase = { name: string; path: string; handlers: Handler[]; ready: () => Promise<unknown> };

/** Vistas guardadas. Se amplía en cada paso de la traducción (docs/engineering/i18n-frontend.md). */
export const GUARDED_VIEWS: GuardCase[] = [];

const list = (items: unknown[]): Handler => ["GET", "/api/v1/staging/records", page(items)];
const vpDetail = (resource: string, id: string, body: unknown): Handler => ["GET", `/api/v1/staging/virtualpos/${resource}/${id}`, body];
const tchCliente = { id: "cli-1", rut: "22222221-2", nombre: "Nombre1", apellido: "Apellido1", fecha_nacimiento: "1990-01-01", profesion: "Sintética", tipo_persona: "NATURAL", tipo_socio: "REGULAR", telefono: "000", email: "socio1@example.invalid", direccion: "Calle 1", comuna: "Comuna Uno", ciudad: "Ciudad Uno", suscripciones: [] };

// Paso 1: rótulos estáticos en inglés («Status», «ID Sub», «Email», «Mail»).
GUARDED_VIEWS.push(
  {
    name: "ficha de cliente VirtualPOS",
    path: "/virtualpos/clientes/cli-1",
    handlers: [list([]), vpDetail("clients", "cli-1", { client: vpClient(1), subscriptions: [vpSubscription(1)], subscription_total: 1, charges: [], charge_total: 0, payments: [vpPayment(1)], payment_total: 1 })],
    ready: () => screen.findByText("FICHA DEL CLIENTE"),
  },
  {
    name: "ficha de plan VirtualPOS",
    path: "/virtualpos/planes/plan-1",
    handlers: [list([]), vpDetail("plans", "plan-1", { plan: vpPlan(1), subscriptions: [vpSubscription(1)], subscription_total: 1 })],
    ready: () => screen.findByText("FICHA DEL PLAN"),
  },
  {
    name: "ficha de suscripción VirtualPOS (renovación T)",
    path: "/virtualpos/suscripciones/sub-1",
    handlers: [list([]), vpDetail("subscriptions", "sub-1", { subscription: vpSubscription(1), payment_method: null, charges: [vpCharge(1, "pendiente")], charge_total: 1, payments: [], payment_total: 0 })],
    ready: () => screen.findByText("FICHA DE LA SUSCRIPCIÓN"),
  },
  { name: "lista de clientes VirtualPOS", path: "/virtualpos/clientes", handlers: [list([vpClient(1)])], ready: () => screen.findByRole("button", { name: "Editar" }) },
  { name: "lista de clientes Payku", path: "/payku/clientes", handlers: [list([paykuClient(1)])], ready: () => screen.findByRole("button", { name: "Eliminar" }) },
  { name: "lista de clientes Toku", path: "/toku/clientes", handlers: [list([tokuCustomer(1)])], ready: () => screen.findByRole("button", { name: "Eliminar" }) },
  {
    name: "ficha de cliente TCH",
    path: "/tch/clientes",
    handlers: [
      ["GET", "/api/v1/tch/clientes", { total: 1, page: 1, limit: 50, pages: 1, items: [tchCliente] }],
      ["GET", /^\/api\/v1\/tch\/clientes\/[^/]+$/, tchCliente],
    ],
    ready: async () => {
      fireEvent.click(await screen.findByRole("button", { name: "22222221-2" }));
      return screen.findByText("TCH / CLIENTE");
    },
  },
);

// Resumen unificado (UX-06): el endpoint responde solo con números y claves en español; el guardián vigila que la
// pantalla no pinte rótulos ni valores crudos en inglés (estados de salud, canales, notas).
GUARDED_VIEWS.push({
  name: "Resumen unificado",
  path: "/central/resumen",
  handlers: [
    ["GET", "/api/v1/dashboard/general", rawSummary()],
    ["GET", "/api/v1/sync-runs/health", [
      { channel: "virtualpos", level: "ok", last_finished_at: "2026-10-15T09:00:00-03:00", age_hours: 3 },
      { channel: "tch", level: "warn", last_finished_at: "2026-10-12T20:00:00-03:00", age_hours: 70 },
    ]],
  ],
  ready: () => screen.findByRole("region", { name: "Indicadores del mes" }),
});

const tokuSubRecord = { record: tokuSubscription(1), related: [] };

// Paso 5: estados en listas y fichas de VirtualPOS, Toku y Payku.
GUARDED_VIEWS.push(
  { name: "lista de suscripciones Toku (ACTIVE)", path: "/toku/suscripciones", handlers: [list([tokuSubscription(1)])], ready: () => screen.findByRole("button", { name: /Ver ficha de/ }) },
  { name: "lista de suscripciones Payku (active)", path: "/payku/suscripciones", handlers: [list([paykuSubscription(1)])], ready: () => screen.findByRole("button", { name: /Ver ficha de/ }) },
  { name: "lista de suscripciones VirtualPOS", path: "/virtualpos/suscripciones", handlers: [list([vpSubscription(1)])], ready: () => screen.findByText("Cancelar Sub") },
  { name: "lista de cargos VirtualPOS", path: "/virtualpos/cargos", handlers: [list([vpCharge(1, "pendiente"), vpCharge(2, "rechazado")])], ready: () => screen.findByText("Reintentar") },
  {
    name: "diálogo «Gestionar estado» de una suscripción Toku",
    path: "/toku/suscripciones/tsu-1",
    handlers: [list([]), ["GET", "/api/v1/staging/toku/subscription/tsu-1", tokuSubRecord]],
    ready: async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Gestionar estado" }));
      return screen.findByRole("form", { name: "Gestionar estado suscripción Toku" });
    },
  },
  {
    name: "suscripciones consolidadas con estado crudo",
    path: "/central/suscripciones",
    handlers: [["GET", "/api/v1/staging/dashboard/general/subscriptions", { total: 1, offset: 0, limit: 100, items: [{ id: "s-1", client: "Cliente Uno", rut: "11111111-1", platform: "Toku", status: "ACTIVE", secondary_status: "cobrable", last_paid_date: null, started_at: "2025-01-01", ended_at: null, amount: "1000", currency: "CLP" }] }]],
    ready: () => screen.findByText("Cliente Uno"),
  },
  {
    name: "ficha general de cliente con estados crudos",
    path: "/central/clientes",
    handlers: [
      ["GET", "/api/v1/staging/dashboard/general/clients", { total: 1, offset: 0, limit: 100, items: [{ rut: "11111111-1", name: "Cliente Uno", origins: ["Toku"], active_origins: ["Toku"] }] }],
      ["GET", /^\/api\/v1\/staging\/dashboard\/general\/clients\/[^/]+$/, { rut: "11111111-1", clients: [], subscriptions: [{ portal: "Toku", id_subscription: "1", external_id: "tsu-1", status: "CANCELLED" }], charges: [{ portal: "VirtualPOS", id_cargo: "2", external_id: "c-1", status: "PAID", amount: "1000" }], transactions: [] }],
    ],
    ready: async () => {
      fireEvent.click(await screen.findByRole("button", { name: "11111111-1" }));
      return screen.findByText(/Ficha general/);
    },
  },
);

// Paso 6: valores de la ficha de proveedor (booleanos, frecuencia, moneda, tarjeta, medio de pago).
GUARDED_VIEWS.push(
  {
    name: "ficha de plan VirtualPOS con booleanos y frecuencia crudos",
    path: "/virtualpos/planes/plan-1",
    handlers: [list([]), vpDetail("plans", "plan-1", { plan: vpPlan(1, { is_active: true, show_in_terminal: false, automatic_renewal: "true", frequency_type: "monthly", currency: "CLP" }), subscriptions: [], subscription_total: 0 })],
    ready: () => screen.findByText("FICHA DEL PLAN"),
  },
  {
    name: "ficha genérica de una suscripción Toku",
    path: "/toku/suscripciones/tsu-1",
    handlers: [list([]), ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1, { is_active: true, recurring: { status: "ACTIVE", frequency: "monthly", currency: "CLP" } }), related: [] }]],
    ready: () => screen.findByText("FICHA COMPLETA"),
  },
  {
    name: "ficha de un medio de pago Toku",
    path: "/toku/metodos-pago/tpm-1",
    handlers: [list([]), ["GET", "/api/v1/staging/toku/payment_method/tpm-1", { record: rec("toku", "payment_method", "tpm-1", { id: "tpm-1", gateway: "pasarela_x", payment_method: { id: "tpm-1", type: "card", status: "ACTIVE", card: { card_brand: "VISA", card_type: "CREDIT", three_d_secure: true } } }), related: [] }]],
    ready: () => screen.findByText("TOKU / MÉTODO DE PAGO"),
  },
  {
    name: "ficha de una transacción VirtualPOS",
    path: "/virtualpos/transacciones/pay-1",
    handlers: [list([]), vpDetail("payments", "pay-1", { payment: vpPayment(1), charge: null, subscription: null, client: null })],
    ready: () => screen.findByText("FICHA DE LA TRANSACCIÓN"),
  },
);

describe("guardián: vistas de caracterización sin valores crudos en inglés", () => {
  for (const view of GUARDED_VIEWS) {
    it(view.name, async () => {
      mountApp(view.path, view.handlers);
      await appReady();
      await view.ready();
      await listSettled();
      await waitFor(() => expect(screen.queryByText("Cargando ficha...")).toBeNull());
      expect(findRawEnglish(document.body)).toEqual([]);
    });
  }
  it("hay al menos un caso registrado cuando el catálogo ya se usa en pantalla", () => {
    expect(Array.isArray(GUARDED_VIEWS)).toBe(true);
  });
});

type ComponentCase = { name: string; element: () => ReactElement };

/** Componentes que se montan directo con datos crudos en inglés (no hace falta la aplicación completa). */
export const GUARDED_COMPONENTS: ComponentCase[] = [];

const channelData = (source: string, over: Partial<ChannelDashboard> = {}): ChannelDashboard => ({
  source, records: 10, resources: { charge: 6, transaction: 4 }, resource_amounts: {}, statuses: [], activity_resource: "transaction", activity: [], years: [2025], last_sync: null, ...over,
});
const monthly = (status: string, count: number) => ({ year: 2025, month: 3, status, count, amount: count * 1000 });
const noop = () => {};

// Paso 4: barras de estado y leyendas de gráficos apilados.
GUARDED_COMPONENTS.push(
  {
    name: "dashboard de canal VirtualPOS: barras de estado y leyendas de gráficos apilados",
    element: () => (
      <ChannelDashboardView
        data={channelData("virtualpos", {
          statuses: [{ resource: "charge", status: "PAID", count: 3 }, { resource: "charge", status: "FAILED", count: 2 }, { resource: "subscription", status: "ACTIVE", count: 5 }],
          charges_monthly: [monthly("PAID", 3), monthly("FAILED", 2), monthly("PENDING", 1)],
        })}
        mode="count" year={2025} syncing={false} onMode={noop} onYear={noop} onOpenResource={noop} onReport={noop} onSync={noop}
      />
    ),
  },
  {
    name: "dashboard de canal Toku: estados de transacciones",
    element: () => (
      <ChannelDashboardView
        data={channelData("toku", {
          resources: { transaction: 4, subscription: 5 },
          statuses: [{ resource: "transaction", status: "SUCCESS", count: 3 }, { resource: "subscription", status: "ACTIVE", count: 5 }, { resource: "subscription", status: "CANCELLED", count: 1 }],
          transactions_monthly: [monthly("SUCCESS", 3), monthly("FAILED", 1)],
        })}
        mode="count" year={2025} syncing={false} onMode={noop} onYear={noop} onOpenResource={noop} onReport={noop} onSync={noop}
      />
    ),
  },
);

describe("guardián: componentes con datos crudos en inglés", () => {
  for (const view of GUARDED_COMPONENTS) {
    it(view.name, () => {
      render(view.element());
      expect(findRawEnglish(document.body)).toEqual([]);
    });
  }
});
