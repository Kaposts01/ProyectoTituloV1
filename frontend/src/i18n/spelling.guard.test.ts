/**
 * Guardián de ortografía: ningún texto de la interfaz puede usar una palabra española sin su tilde («Telefono»,
 * «Renovacion») ni el anglicismo «Subscripción». Lee el código fuente (no las pantallas) para cubrir también lo que
 * ningún test renderiza.
 *
 * Quedan fuera, a propósito:
 *  - las CLAVES estables de columna (`key: "Telefono"`, `vpColumnFields`, `columnFields`): `?orden=` de la URL
 *    las guarda y cambiarlas rompería enlaces guardados (paso 2);
 *  - los comentarios y los identificadores/claves de la API (`suscription_url` es un typo del proveedor).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Palabras que en español llevan tilde (o ñ) y no pueden aparecer sin ella en un texto visible. */
const NO_TILDE = [
  "Telefono", "Descripcion", "Genero", "Direccion", "Region", "Pais", "Codigo", "Renovacion", "Metodo", "Dias",
  "Cancelacion", "Creacion", "Actualizacion", "Terminacion", "Transaccion", "Maximo", "anticipacion", "activacion",
  "electronico", "Credito", "Debito", "limite", "envio", "Ultimo", "Fecha transaccion", "Navegacion", "Sincronizacion", "Configuracion", "Informacion", "Busqueda", "Operacion", "Conciliacion",
];
const FORBIDDEN = new RegExp(`(?<![\\p{L}\\p{N}_])(${NO_TILDE.join("|")}|[Ss]ubscripci\\p{L}*|SUBSCRIPCI\\p{L}*)(?![\\p{L}\\p{N}_])`, "u");

/** Quita lo que no es texto visible: comentarios, claves estables de columna y las tablas de claves de filtro. */
function visibleText(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\bkey:\s*"[^"]*"/g, "key:")
    .replace(/const (vpColumnFields|columnFields)[^=]*=\s*\{[\s\S]*?\n\};/g, "")
    .replace(/column\.key === "[^"]*"/g, "column.key === ")
    .replace(/^import .*$/gm, "");
}

describe("ortografía: sin tildes faltantes ni «Subscripción»", () => {
  it("el código de la interfaz no contiene palabras sin tilde ni el anglicismo", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(ROOT)) {
      visibleText(readFileSync(file, "utf8")).split("\n").forEach((line, index) => {
        // Solo cadenas entre comillas o texto JSX: una palabra suelta de código (p. ej. un identificador) no cuenta.
        const strings = line.match(/"[^"\n]*"|`[^`\n]*`|'[^'\n]*'|>[^<>{}\n]+</g) ?? [];
        for (const text of strings) {
          const match = FORBIDDEN.exec(text);
          if (match) offenders.push(`${relative(ROOT, file)}:${index + 1} «${match[0]}» en ${text.slice(0, 70)}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it("el detector reconoce lo prohibido y deja pasar lo correcto", () => {
    expect(FORBIDDEN.test("Telefono")).toBe(true);
    expect(FORBIDDEN.test("Subscripciones activas")).toBe(true);
    expect(FORBIDDEN.test("FICHA DE LA SUBSCRIPCIÓN")).toBe(true);
    expect(FORBIDDEN.test("Teléfono")).toBe(false);
    expect(FORBIDDEN.test("Suscripción")).toBe(false);
    expect(FORBIDDEN.test("suscription_url")).toBe(false);
  });
});
