import { useEffect, useState } from "react";
import { getJson, postJson, friendlyError } from "../../api";
import { getCachedOrFetch, invalidateCache, setCached } from "../../apiCache";
import { defaultYear } from "../shared/utils";
import type { AuthSession, ChannelDashboard } from "../shared/types";

/**
 * Canal activo y su dashboard (datos, modo, año, sincronización). Se llama desde AppCore para que
 * el estado sobreviva a la navegación igual que antes de la extracción.
 */
export function useChannelDashboard(session: AuthSession | null | undefined, setError: (message: string | null) => void) {
  const [channel, setChannel] = useState<string | null>(null);
  const [channelData, setChannelData] = useState<ChannelDashboard | null>(null);
  const [channelLoading, setChannelLoading] = useState(false);
  const [channelRefreshing, setChannelRefreshing] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [mode, setMode] = useState<"count" | "amount">("count");
  const [year, setYear] = useState<number | null>(null);

  useEffect(() => {
    if (!session || !channel) return;
    const cacheKey = `dashboard:${channel}`;
    let mounted = true;
    getCachedOrFetch(cacheKey, 5 * 60 * 1000, () => getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${channel}`))
      .then((data) => {
        if (!mounted) return;
        setChannelData(data);
        setYear(defaultYear(data.years));
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        const message = friendlyError(err, "No se pudo cargar el dashboard del canal.");
        setError(message);
        setChannelError(message);
      })
      .finally(() => {
        if (mounted) { setChannelLoading(false); setChannelRefreshing(false); }
      });
    return () => {
      mounted = false;
    };
  }, [session, channel, setError, reloadKey]);

  /** Reintenta la carga del dashboard tras un error (vuelve a pedirlo, sin usar la caché). */
  function reloadChannel() {
    if (channel) invalidateCache(`dashboard:${channel}`);
    setChannelError(null);
    setChannelLoading(true);
    setReloadKey((key) => key + 1);
  }

  function syncChannel(source: string) {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    postJson<{ status: string }>(`/api/v1/staging/sync/${source}`)
      .then(() => {
        invalidateCache();
        setChannelData(null);
        setChannelLoading(true);
        return getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${source}`);
      })
      .then((data) => {
        setCached(`dashboard:${source}`, data);
        setChannelData(data);
        setYear(defaultYear(data.years));
      })
      .catch((err: unknown) => {
        const message = friendlyError(err, "Error al sincronizar el canal.");
        setError(message);
        setChannelError(message);
      })
      .finally(() => {
        setSyncing(false);
        setChannelLoading(false);
      });
  }

  return {
    channel,
    setChannel,
    channelData,
    setChannelData,
    channelLoading,
    setChannelLoading,
    channelRefreshing,
    setChannelRefreshing,
    channelError,
    setChannelError,
    reloadChannel,
    syncing,
    setSyncing,
    mode,
    setMode,
    year,
    setYear,
    syncChannel,
  };
}
