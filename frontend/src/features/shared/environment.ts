import { useEffect, useState } from "react";
import { getJson } from "../../api";
import { getCachedOrFetch } from "../../apiCache";

export interface EnvironmentInfo {
  app_env: string;
  label: string;
  is_production: boolean;
  csrf_cookie_name?: string;
  enabled_channels?: string[];
}

export interface EnvironmentSwitch {
  target_env: string;
  target_label: string;
  url: string | null;
}

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

export function fetchEnvironment(): Promise<EnvironmentInfo> {
  return getCachedOrFetch("system:environment", ONE_DAY_MS, () => getJson<EnvironmentInfo>("/api/v1/system/environment"));
}

export function fetchEnvironmentSwitch(): Promise<EnvironmentSwitch> {
  return getJson<EnvironmentSwitch>("/api/v1/system/environment/switch");
}

export const ALL_CHANNELS = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"] as const;
export const CHANNEL_UNAVAILABLE_TITLE = "No disponible en este ambiente";

/** Canales habilitados; si el dato falta (carga, error, backend antiguo) se asumen todos habilitados. */
export function resolveEnabledChannels(env: Pick<EnvironmentInfo, "enabled_channels"> | null | undefined): string[] {
  const list = env?.enabled_channels;
  return Array.isArray(list) ? list : [...ALL_CHANNELS];
}

/** Hook: lista de canales habilitados y helper `isEnabled`. Mientras carga o ante error: todos habilitados. */
export function useEnabledChannels(): { enabled: string[]; isEnabled: (channel: string) => boolean } {
  const [enabled, setEnabled] = useState<string[]>([...ALL_CHANNELS]);
  useEffect(() => {
    let alive = true;
    fetchEnvironment()
      .then((env) => { if (alive) setEnabled(resolveEnabledChannels(env)); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return { enabled, isEnabled: (channel: string) => enabled.includes(channel) };
}
