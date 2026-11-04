export interface DevServerSettings {
  port: number;
  proxyTarget: string;
}

/** Resuelve puerto y destino del proxy a partir de variables VITE_* (no secretas). */
export function resolveDevServerSettings(env: Record<string, string | undefined>): DevServerSettings {
  const port = Number.parseInt(env.VITE_DEV_PORT ?? "", 10);
  return {
    port: Number.isInteger(port) && port > 0 && port < 65536 ? port : 5173,
    proxyTarget: env.VITE_API_PROXY_TARGET?.trim() || "http://127.0.0.1:8000",
  };
}
