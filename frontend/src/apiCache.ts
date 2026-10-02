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

  const request = fetcher()
    .then((data) => {
      setCached(key, data);
      return data;
    })
    .finally(() => {
      _inFlight.delete(key);
    });
  _inFlight.set(key, request);
  return request;
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
