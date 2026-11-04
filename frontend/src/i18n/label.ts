import { es, IDENTIFIER_DOMAINS, type Domain } from "./es";

export type { Domain };

/** Texto de un valor ausente (null, undefined, cadena vacía). Coincide con `text()` de features/shared/utils. */
export const NO_DATA = "Sin dato";

/**
 * Clave de búsqueda: sin tildes, en minúsculas, «_» y «-» como espacio y sin espacios repetidos.
 * Misma normalización que `statusColors.normalizeStatus`, para que color y texto coincidan.
 */
export function normalizeKey(raw: unknown): string {
  return String(raw ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Texto para un valor que el catálogo no conoce. Conserva el valor para que soporte lo identifique. */
export function unknownLabel(raw: unknown): string {
  return `Desconocido (${String(raw).trim()})`;
}

const warned = new Set<string>();
/** Solo para tests: olvida los avisos ya emitidos. */
export function resetUnknownWarnings(): void {
  warned.clear();
}

function warnUnknown(domain: Domain, raw: unknown): void {
  // Solo en desarrollo y pruebas; sin datos personales (los valores de estos dominios son estados y códigos).
  if (!import.meta.env.DEV) return;
  const id = `${domain}\u0000${String(raw)}`;
  if (warned.has(id)) return;
  warned.add(id);
  console.warn(`[i18n] valor sin traducir en «${domain}»: ${JSON.stringify(String(raw))}`);
}

function lookup(domain: Domain, raw: unknown): string | undefined {
  const table = es[domain] as Readonly<Record<string, string>>;
  const key = IDENTIFIER_DOMAINS.includes(domain) ? String(raw).trim().toLowerCase() : normalizeKey(raw);
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
}

/** Traducción de un valor, o `undefined` si es ausente o el catálogo no lo conoce (no avisa; útil en tests y cascadas). */
export function tryLabel(domain: Domain, raw: unknown): string | undefined {
  if (raw === null || raw === undefined || raw === "") return undefined;
  return lookup(domain, raw);
}

/**
 * Texto en español de un valor de la API o del proveedor.
 *  - Valor ausente (null, undefined, «») -> «Sin dato».
 *  - Valor conocido -> su traducción.
 *  - Valor desconocido -> «Desconocido (valor)» y, solo en desarrollo, un `console.warn`.
 */
export function label(domain: Domain, raw: unknown): string {
  if (raw === null || raw === undefined || raw === "") return NO_DATA;
  const found = lookup(domain, raw);
  if (found !== undefined) return found;
  warnUnknown(domain, raw);
  return unknownLabel(raw);
}

/** Igual que `label`, pero con otro texto para el valor ausente (p. ej. «—»). */
export function labelOr(domain: Domain, raw: unknown, empty: string): string {
  return raw === null || raw === undefined || raw === "" ? empty : label(domain, raw);
}
