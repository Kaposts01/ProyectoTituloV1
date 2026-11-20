const _cache = new Map<string, { data: unknown; ts: number }>();
const _inFlight = new Map<string, Promise<unknown>>();

export function getCached<T>(key: string, ttlMs: number): T | null {
  const entry = _cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > ttlMs) return null;
  return entry.data as T;
}

export function setCached(key: string, data: unknown): void {
  _cache.set(key, { data, ts: Date.now() });
}

export async function getCachedOrFetch<T>(
  key: string,
  ttlMs: number,
  fetcher: () => Promise<T>,
): Promise<T> {
  const cached = getCached<T>(key, ttlMs);
  if (cached !== null) return cached;

  const pending = _inFlight.get(key) as Promise<T> | undefined;
  if (pending) return pending;

  const request: Promise<T> = fetcher()
    .then((data) => {
      // Si la clave se invalidó mientras la petición estaba en vuelo (cierre de sesión, cambio de usuario), la respuesta
      // vieja no vuelve a la caché: llega a quien la esperaba, pero no queda guardada.
      if (_inFlight.get(key) === request) setCached(key, data);
      return data;
    })
    .finally(() => {
      if (_inFlight.get(key) === request) _inFlight.delete(key);
    });
  _inFlight.set(key, request);
  return request;
}

/** ¿Hay una respuesta vigente en la caché o una petición en vuelo para esta clave? (sin pedir nada). */
export function isCachedOrPending(key: string, ttlMs: number): boolean {
  return getCached(key, ttlMs) !== null || _inFlight.has(key);
}

/** Borra exactamente una clave (a diferencia de `invalidateCache`, que borra por prefijo). */
export function deleteCached(key: string): void {
  _cache.delete(key);
  _inFlight.delete(key);
}

export function invalidateCache(prefix?: string): void {
  if (!prefix) {
    _cache.clear();
    _inFlight.clear();
    return;
  }
  for (const key of _cache.keys()) {
    if (key.startsWith(prefix)) _cache.delete(key);
  }
  for (const key of _inFlight.keys()) {
    if (key.startsWith(prefix)) _inFlight.delete(key);
  }
}
