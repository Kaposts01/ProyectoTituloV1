const _cache = new Map<string, { data: unknown; ts: number }>();

export function getCached<T>(key: string, ttlMs: number): T | null {
  const entry = _cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > ttlMs) return null;
  return entry.data as T;
}

export function setCached(key: string, data: unknown): void {
  _cache.set(key, { data, ts: Date.now() });
}

export function invalidateCache(prefix?: string): void {
  if (!prefix) {
    _cache.clear();
    return;
  }
  for (const key of _cache.keys()) {
    if (key.startsWith(prefix)) _cache.delete(key);
  }
}
