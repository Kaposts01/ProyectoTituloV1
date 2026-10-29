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
        if (mounted) setError(friendlyError(err, "No se pudo cargar el dashboard del canal."));
      })
      .finally(() => {
        if (mounted) { setChannelLoading(false); setChannelRefreshing(false); }
      });
    return () => {
      mounted = false;
    };
  }, [session, channel, setError]);

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
      .catch((err: unknown) => setError(friendlyError(err, "Error al sincronizar el canal.")))
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
    syncing,
    setSyncing,
    mode,
    setMode,
    year,
    setYear,
    syncChannel,
  };
}
