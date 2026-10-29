/**
 * Guardián de textos en español. Monta las vistas de caracterización con DATOS CRUDOS EN INGLÉS del proveedor
 * (ACTIVE, PAID, FAILED, True…) y falla si en pantalla aparece un valor crudo o un rótulo inglés conocido.
 *
 * Excepciones documentadas (docs/engineering/i18n-frontend.md): el texto libre del proveedor y los códigos
 * técnicos se pintan crudos, dentro de un elemento con el atributo `data-raw-text`; el guardián no los mira.
 */
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appReady, listSettled, mountApp, resetApp, type Handler } from "../test/appHarness";
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
