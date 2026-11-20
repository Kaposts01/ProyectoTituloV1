import { ApiError, getJson } from "./api";
import { deleteCached, getCachedOrFetch, invalidateCache, isCachedOrPending } from "./apiCache";
import { fetchSummary } from "./features/summary/summaryApi";
import { parseRoute } from "./routes";

/**
 * PERF-03 (d264 = b, opción C): datos de la vista de entrada adelantados, en paralelo con /auth/me.
 *
 * Mientras /auth/me está en vuelo se pide ya la primera respuesta de la vista que indica la URL y se guarda en la
 * caché (`getCachedOrFetch`); cuando la sesión llega y la vista se monta con sus permisos de siempre, su hook
 * encuentra la respuesta (o la petición en vuelo) en lugar de pedirla desde cero. Nada se muestra antes: las vistas
 * solo se montan con la sesión confirmada y la ruta autorizada (AppCore).
 *
 * Seguridad:
 * - una respuesta 401 o 403 (o cualquier error) no se guarda: `getCachedOrFetch` solo cachea los éxitos;
 * - AppCore llama a `discardEarlyData()` si /auth/me falla, al cerrar sesión y al iniciar otra (cambio de usuario);
 * - las entradas `early:` son de un solo uso: el hook que las toma las borra, así volver a la vista más tarde
 *   pide datos frescos como antes.
 */
const EARLY_PREFIX = "early:";
const EARLY_TTL_MS = 60_000;
const PAGE_QUERY = "offset=0&limit=50"; // el orden de claves es el de `cleanParams({ offset, limit })` en los hooks

const earlyKey = (id: string) => `${EARLY_PREFIX}${id}`;

/** Clave de la caché de un listado unificado o paginado: su URL completa. */
export const listUrl = (path: string, query: string) => `${path}${query ? `?${query}` : ""}`;

/** Primera página de Suscripciones, Cobros y Clientes: la URL exacta que pide el hook al montar. */
export const FIRST_PAGE_URLS = {
  subscriptions: listUrl("/api/v1/general/subscriptions", PAGE_QUERY),
  charges: listUrl("/api/v1/general/charges", PAGE_QUERY),
  clients: `/api/v1/staging/dashboard/general/clients?${new URLSearchParams({ limit: "50", offset: "0", filter_field: "all" })}`,
};

const SUMMARY_ID = "summary";

function warm<T>(id: string, fetcher: () => Promise<T>): void {
  // Los errores se tragan aquí: el hook que monte la vista volverá a pedir y mostrará su propio error.
  void getCachedOrFetch<T>(earlyKey(id), EARLY_TTL_MS, fetcher).catch(() => undefined);
}

/** Dispara la petición de datos de la vista de la ruta (sin filtros en la URL). No hace nada para otras rutas. */
export function startEarlyData(pathname: string = window.location.pathname, search: string = window.location.search): void {
  const path = pathname.split("?")[0].replace(/\/+$/, "");
  const hasSearch = search.replace(/^\?/, "") !== "";
  if (path === "") { warm(SUMMARY_ID, () => fetchSummary({})); return; }
  const route = parseRoute(path);
  if (!route) return;
  if (route.kind === "channel") {
    // Misma clave y misma petición que `useChannelDashboard`: el hook la encuentra al montar.
    void getCachedOrFetch(`dashboard:${route.source}`, 5 * 60 * 1000, () => getJson(`/api/v1/staging/dashboard/${route.source}`)).catch(() => undefined);
    return;
  }
  if (route.kind !== "central") return;
  if (route.view === "summary") {
    if (!hasSearch) warm(SUMMARY_ID, () => fetchSummary({}));
    return;
  }
  // Los enlaces con filtros u offset en la URL piden otra cosa: no se adelanta nada.
  if (hasSearch) return;
  if (route.view === "subscriptions") warm(FIRST_PAGE_URLS.subscriptions, () => getJson(FIRST_PAGE_URLS.subscriptions));
  // d267 = b: en Cobros no se adelanta (medido el 2026-11-20: con el adelantado el LCP móvil empeoraba ~140 ms).
  else if (route.view === "clients") warm(FIRST_PAGE_URLS.clients, () => getJson(FIRST_PAGE_URLS.clients));
}

/**
 * Toma, una sola vez, la respuesta adelantada con esa clave (o la petición en vuelo). Devuelve `null` si no hay
 * ninguna, y el hook sigue con su petición normal.
 */
export function takeEarly<T>(id: string): Promise<T> | null {
  const key = earlyKey(id);
  if (!isCachedOrPending(key, EARLY_TTL_MS)) return null;
  const promise = getCachedOrFetch<T>(key, EARLY_TTL_MS, () => Promise.reject(new Error("sin dato adelantado")));
  const clear = () => deleteCached(key);
  promise.then(clear, clear);
  return promise;
}

/**
 * QA PERF-03b F2: usa la respuesta adelantada si la hay; si falló por algo que no sea 401/403 (red caída, 5xx),
 * reintenta con la petición normal del hook en vez de mostrar el error del adelantado.
 */
export function earlyOr<T>(early: Promise<T> | null, fetcher: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!early) return fetcher();
  return early.catch((err: unknown) => {
    if (signal?.aborted) throw err; // la consulta ya se canceló (p. ej. cierre de sesión): no reintentar
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) throw err;
    return fetcher();
  });
}

export const takeEarlySummary = () => takeEarly<Awaited<ReturnType<typeof fetchSummary>>>(SUMMARY_ID);

/** Descarta todo lo adelantado y la caché de datos: /auth/me falló, se cerró la sesión o entra otro usuario. */
export function discardEarlyData(): void {
  invalidateCache();
}
