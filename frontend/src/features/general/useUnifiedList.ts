import { useEffect, useState } from "react";
import { ApiError, friendlyError, getJson } from "../../api";

export type UnifiedLoad<T> = { data: T | null; loading: boolean; error: string | null; forbidden: boolean };

/** Quita los parámetros vacíos para que la URL (y la exportación) lleve solo los filtros activos. */
export function cleanParams(params: Record<string, string | number | null | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text !== "") out[key] = text;
  }
  return out;
}

/**
 * GET a una ruta de la API con parámetros; cancela la petición anterior al cambiar los parámetros.
 * Si cambia la RUTA (p. ej. de cobros a pagos), los datos anteriores se descartan de inmediato: son de otra forma
 * y pintarlos bajo las columnas nuevas mezclaba filas (QA-01). Al cambiar solo los parámetros se conservan
 * mientras llega la página nueva, para que la tabla no parpadee.
 */
export function useUnifiedGet<T>(path: string, params: Record<string, string>, enabled = true): UnifiedLoad<T> {
  const query = new URLSearchParams(params).toString();
  const [state, setState] = useState<UnifiedLoad<T> & { path: string }>({ data: null, loading: enabled, error: null, forbidden: false, path });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState((prev) => (prev.path === path
      ? { ...prev, loading: true, error: null }
      : { data: null, loading: true, error: null, forbidden: false, path }));
    getJson<T>(`${path}${query ? `?${query}` : ""}`, controller.signal)
      .then((data) => setState({ data, loading: false, error: null, forbidden: false, path }))
      .catch((err: unknown) => {
        if (controller.signal.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
        const forbidden = err instanceof ApiError && err.status === 403;
        setState({ data: null, loading: false, forbidden, error: forbidden ? null : friendlyError(err, "No se pudo cargar la lista."), path });
      });
    return () => controller.abort();
  }, [path, query, enabled]);
  if (state.path !== path) return { data: null, loading: enabled, error: null, forbidden: false };
  const { data, loading, error, forbidden } = state;
  return { data, loading, error, forbidden };
}
