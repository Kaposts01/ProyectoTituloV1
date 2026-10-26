import { getJson } from "../../api";
import { getCachedOrFetch } from "../../apiCache";

export interface EnvironmentInfo {
  app_env: string;
  label: string;
  is_production: boolean;
  csrf_cookie_name?: string;
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
