import { useEffect, useState } from "react";
import { getCachedOrFetch } from "../apiCache";
import { getJson } from "../api";

export type HealthChannel = "virtualpos" | "toku" | "payku" | "tch";
export type HealthLevel = "ok" | "warn" | "error" | "unknown";
export type ChannelHealthEntry = {
  channel: HealthChannel;
  level: HealthLevel;
  last_finished_at: string | null;
  age_hours: number | null;
};
export type ChannelHealthMap = Partial<Record<HealthChannel, ChannelHealthEntry>>;

export const HEALTH_CACHE_KEY = "sync-health";
export const HEALTH_TTL_MS = 300000;

/** Consulta la salud de sincronización; cualquier fallo devuelve un mapa vacío. */
export async function fetchChannelHealth(): Promise<ChannelHealthMap> {
  try {
    const rows = await getCachedOrFetch<ChannelHealthEntry[]>(HEALTH_CACHE_KEY, HEALTH_TTL_MS, () =>
      getJson<ChannelHealthEntry[]>("/api/v1/sync-runs/health"),
    );
    const map: ChannelHealthMap = {};
    if (Array.isArray(rows)) for (const row of rows) map[row.channel] = row;
    return map;
  } catch {
    return {};
  }
}

export function useChannelHealth(enabled = true): ChannelHealthMap {
  const [health, setHealth] = useState<ChannelHealthMap>({});
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void fetchChannelHealth().then((map) => { if (!cancelled) setHealth(map); });
    return () => { cancelled = true; };
  }, [enabled]);
  return health;
}
