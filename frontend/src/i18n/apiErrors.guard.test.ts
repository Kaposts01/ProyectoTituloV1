/**
 * Guardián del catálogo de errores de la API: `docs/data/error-codes.md` (generado desde el backend) y el dominio
 * `apiError` de `i18n/es.ts` deben tener exactamente los mismos códigos. Si el backend suma un código y nadie lo
 * traduce (o se traduce uno que ya no existe), este test falla.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { es } from "./es";
import { normalizeKey, tryLabel } from "./label";

const CATALOG_DOC = resolve(process.cwd(), "..", "docs", "data", "error-codes.md");

/** Códigos de la primera columna de la tabla del documento. */
function documentedCodes(): string[] {
  const text = readFileSync(CATALOG_DOC, "utf8");
  return [...text.matchAll(/^\| `([a-z0-9_]+)` \|/gm)].map((match) => match[1]);
}

describe("catálogo de errores de la API frente a docs/data/error-codes.md", () => {
  const codes = documentedCodes();
  const catalogKeys = Object.keys(es.apiError);

  it("el documento declara 96 códigos distintos (el parser lee toda la tabla)", () => {
    expect(codes).toHaveLength(96);
    expect(new Set(codes).size).toBe(96);
  });

  it("todo código del documento está traducido en el dominio apiError", () => {
    const missing = codes.filter((code) => tryLabel("apiError", code) === undefined);
    expect(missing, "códigos sin traducir: agrégalos a es.apiError").toEqual([]);
  });

  it("todo código del dominio apiError existe en el documento", () => {
    const documented = new Set(codes.map(normalizeKey));
    const extra = catalogKeys.filter((key) => !documented.has(key));
    expect(extra, "códigos traducidos que el documento ya no tiene").toEqual([]);
  });

  it("los textos son fijos: sin marcadores de datos variables ni identificadores técnicos", () => {
    for (const [key, text] of Object.entries(es.apiError as Record<string, string>)) {
      expect(text, key).not.toMatch(/[{}<>]|run_id|_/);
      expect(text.endsWith("."), `${key} debe terminar en punto`).toBe(true);
    }
  });
});
