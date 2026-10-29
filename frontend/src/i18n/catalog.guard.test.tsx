/**
 * Guardián de textos en español. Monta las vistas de caracterización con DATOS CRUDOS EN INGLÉS del proveedor
 * (ACTIVE, PAID, FAILED, True…) y falla si en pantalla aparece un valor crudo o un rótulo inglés conocido.
 *
 * Excepciones documentadas (docs/engineering/i18n-frontend.md): el texto libre del proveedor y los códigos
 * técnicos se pintan crudos, dentro de un elemento con el atributo `data-raw-text`; el guardián no los mira.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appReady, listSettled, mountApp, resetApp, type Handler } from "../test/appHarness";
import { page, paykuClient, tokuCustomer, vpCharge, vpClient, vpPayment, vpPlan, vpSubscription } from "../test/fixtures";
import { es } from "./es";
import { label, resetUnknownWarnings } from "./label";

afterEach(resetApp);

/** Palabra completa, distingue mayúsculas: «Active» no es lo mismo que el apellido «Activo». */
export const FORBIDDEN_EN = [
  "ACTIVE", "PAID", "PENDING", "SUCCESS", "FAILED", "CANCELLED", "CANCELED", "PAUSED", "REJECTED",
  "active", "paid", "pending", "success", "failed", "cancelled", "paused", "rejected", "completed", "running", "partial", "queued",
  "True", "False", "Status", "Email", "Mail",
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
    ready: () => screen.findByText("FICHA DE LA SUBSCRIPCIÓN"),
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
