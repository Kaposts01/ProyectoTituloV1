/**
 * Guardián de identificadores (decisión D34): en el código del frontend, los NOMBRES (funciones, variables,
 * constantes, tipos, componentes, hooks, propiedades) van en inglés; los comentarios y los textos que ve el usuario
 * quedan en español. Este test lee los fuentes con el analizador de TypeScript, junta los identificadores (no los
 * textos, no los comentarios, no el texto de JSX) y falla si alguno contiene una palabra española de `DENYLIST`.
 *
 * Excepciones, todas documentadas:
 *  - los ADAPTADORES (`*Adapter.ts`) y los fixtures del resumen: son la única capa que conoce las claves en español
 *    del backend (D33);
 *  - `i18n/es.ts`: las claves del catálogo son los valores crudos de la API o del proveedor (`vigente`, `pagada`);
 *  - `rut` se conserva en cualquier identificador (término del dominio chileno, D37) y no está en la lista;
 *  - `ALLOWED_BY_FILE`: nombres que son el CONTRATO (valores del backend usados como clave de tabla, segmentos de URL,
 *    entidades del contrato de exportación, claves de campo que entrega la API).
 * Para sumar una palabra a la lista o una excepción, deja el motivo escrito: es la forma de que un nombre en español
 * no vuelva a colarse sin que alguien lo decida.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const ROOT = resolve(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Palabras españolas que no tienen sentido en un nombre de código. */
const DENYLIST = new Set((
  "estado monto periodo cliente clientes suscripcion suscripciones transaccion transacciones nombre apellido fecha tipo " +
  "canal canales detalle numero ficha mandato activacion activaciones baja bajas alta altas caida caidas cobrable " +
  "cobrables cobrabilidad vigente vigentes eliminada eliminadas aceptada aceptadas rechazada rechazadas rechazo pagada " +
  "pagadas pagado pagados pendiente pendientes cobro cobros cargo cargos banco cuenta origen captador entidad direccion " +
  "comuna ciudad telefono profesion socio socios ingreso ingresos mensual mensuales crecimiento usuarios razon centro " +
  "costo equivalente ultimo intentos valor datos fuente plataforma planes nota mes anio saldo cuota cuotas recaudo " +
  "recaudadora renovacion revision todas vencida suspendida pausada cancelada cancelado cerrada abierta anulada activa " +
  "activo inactiva inactivo incobrable neto impaga impago completada creada fallida fallido exitosa exitoso registrado " +
  "persona empresa unidad totales procesando esperando lejos cerca requiere nunca definicion conciliacion deudas pagos " +
  "eliminacion expirada aplicada aprobada aprobado retirada reintento reintentada ejecutable ejecutada cubierto crear " +
  "cancelar cobrar cobrada cobrado bloqueado prepago credito debito nacimiento"
).split(" "));

const ADAPTER_OR_FIXTURE = /(Adapter\.ts|summaryFixtures\.ts)$/;
const CATALOG = /^i18n[\\/]es\.ts$/;

/** Nombres permitidos por archivo, con el motivo. */
const ALLOWED_BY_FILE: Record<string, { words: string[]; reason: string }> = {
  "routes.ts": { words: ["clientes", "suscripciones", "transacciones", "cargos", "planes", "deudas"], reason: "segmentos de URL (claves de tabla): las URLs no se renombran" },
  "features/shared/exportMapping.ts": { words: ["clientes", "suscripciones", "cobros", "pagos", "canal"], reason: "contrato de exportación (entidades y parámetro `canal`)" },
  "features/shared/ExportButton.tsx": { words: ["clientes", "suscripciones", "cobros", "pagos", "canal", "canales"], reason: "contrato de exportación (entidades y parámetro `canal`)" },
  "features/provider/StagingRecordsList.tsx": { words: ["canal"], reason: "propiedad `canal` del contrato de exportación" },
  "features/tch/TchContent.tsx": { words: ["canal"], reason: "propiedad `canal` del contrato de exportación" },
  "features/billing/billingLabels.ts": { words: ["rechazada", "pendiente", "creada", "fallida", "requiere", "conciliacion", "expirada", "aplicada", "aprobada", "retirada", "reintentada", "ejecutable", "ejecutada"], reason: "estados del backend usados como clave de tabla" },
  "features/billing/billingPlan.ts": { words: ["pagado", "revision", "procesando", "cubierto", "crear", "cancelar"], reason: "valores del plan de cobro usados como clave de tabla" },
  "features/billing/billingRenewal.ts": { words: ["alta", "vencida", "cerrada", "abierta"], reason: "estados de renovación del backend usados como clave de tabla" },
  "features/dashboard/alertGroups.ts": { words: ["alta", "baja"], reason: "valores de severidad del backend usados como clave de tabla" },
  "features/recovery/RecoveryPanel.tsx": { words: ["inactiva", "incobrable", "nunca", "cobrado", "cobrable"], reason: "estados secundarios del backend usados como clave de tabla" },
  "features/shared/kpis.ts": { words: ["recaudo", "mensual"], reason: "clave `recaudo_mensual` que entrega la API de KPIs" },
  "features/shared/types.ts": { words: ["cobrable"], reason: "claves del dashboard de canal que entrega la API (`cobrable_subs_monthly`)" },
  "features/virtualpos/columns.ts": { words: ["cobrable"], reason: "clave `cobrable_subscription_count` que entrega la API" },
};

function words(identifier: string): string[] {
  return identifier.replace(/([a-z0-9])([A-Z])/g, "$1_$2").split(/[_$]+/).map((w) => w.toLowerCase()).filter(Boolean);
}

function violations(): string[] {
  const out: string[] = [];
  for (const file of sourceFiles(ROOT)) {
    const rel = relative(ROOT, file).replace(/\\/g, "/");
    if (ADAPTER_OR_FIXTURE.test(rel) || CATALOG.test(rel)) continue;
    const allowed = new Set(ALLOWED_BY_FILE[rel]?.words ?? []);
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const seen = new Set<string>();
    const visit = (node: ts.Node) => {
      if (ts.isIdentifier(node)) {
        for (const word of words(node.text)) {
          if (DENYLIST.has(word) && !allowed.has(word) && !seen.has(`${node.text}`)) {
            seen.add(node.text);
            out.push(`${rel}: «${node.text}» contiene «${word}»`);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return out;
}

describe("guardián de identificadores: nombres en inglés (D34)", () => {
  it("ningún identificador usa una palabra española fuera de los adaptadores y las excepciones documentadas", () => {
    expect(violations()).toEqual([]);
  });

  it("cada excepción por archivo todavía se usa y tiene motivo (la lista no acumula residuos)", () => {
    for (const [rel, { words: allowedWords, reason }] of Object.entries(ALLOWED_BY_FILE)) {
      expect(reason.length, rel).toBeGreaterThan(10);
      const source = ts.createSourceFile(rel, readFileSync(join(ROOT, rel), "utf8"), ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      const used = new Set<string>();
      const visit = (node: ts.Node) => {
        if (ts.isIdentifier(node)) for (const word of words(node.text)) used.add(word);
        ts.forEachChild(node, visit);
      };
      visit(source);
      expect(allowedWords.filter((word) => !used.has(word)), `${rel}: palabras que ya no se usan; quítalas de la excepción`).toEqual([]);
    }
  });

  it("detecta de verdad un nombre en español (el guardián no es decorativo)", () => {
    const sample = ts.createSourceFile("x.ts", "const montoTotal = 1; function showCliente() {} const ok = 2;", ts.ScriptTarget.Latest, true);
    const found: string[] = [];
    const visit = (node: ts.Node) => {
      if (ts.isIdentifier(node)) for (const word of words(node.text)) if (DENYLIST.has(word)) found.push(node.text);
      ts.forEachChild(node, visit);
    };
    visit(sample);
    expect(found).toEqual(["montoTotal", "showCliente"]);
  });

  it("`rut` no está en la lista (se conserva a propósito) ni las siglas de canal", () => {
    for (const keep of ["rut", "tch", "toku", "payku", "virtualpos", "etl", "clp"]) expect(DENYLIST.has(keep), keep).toBe(false);
  });
});
