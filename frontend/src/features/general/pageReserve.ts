import type { CSSProperties } from "react";

/** Filas que se reservan antes de conocer cuántas traerá la respuesta (una página completa). */
export const DEFAULT_PAGE_ROWS = 50;
/** Piso de la reserva: una respuesta vacía o con 1 o 2 filas no deja un hueco de varias pantallas. */
const MIN_RESERVED_ROWS = 3;

const lastRows = new Map<string, number>();

/**
 * PERF-03 (H4): alto reservado para un listado paginado mientras llega la primera página.
 * Reserva las filas de la última respuesta de ese mismo listado (si ya hubo una en la sesión) o una página completa
 * (50) la primera vez. Se suelta apenas llega cualquier respuesta (con filas, vacía o con error): el `aria-busy`
 * baja y la regla `min-height` deja de aplicar, de modo que un error no deja un hueco de ~2.500 px.
 */
export function pageReserve(key: string, data: { items: unknown[] } | null): { className: string; style?: CSSProperties } {
  if (data) {
    lastRows.set(key, Math.min(DEFAULT_PAGE_ROWS, Math.max(MIN_RESERVED_ROWS, data.items.length)));
    return { className: "table-wrap" };
  }
  const rows = lastRows.get(key) ?? DEFAULT_PAGE_ROWS;
  return { className: "table-wrap table-wrap-page", style: { "--page-rows": rows } as CSSProperties };
}

/** Solo para pruebas. */
export function resetPageReserve(): void {
  lastRows.clear();
}
