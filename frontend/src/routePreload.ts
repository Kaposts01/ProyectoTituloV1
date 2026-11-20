import { parseRoute } from "./routes";

/**
 * Cascada de arranque (PERF-03e): el chunk de la vista de la ruta actual se pide mientras /auth/me
 * está en vuelo, en vez de esperar a que la sesión llegue y se monte el Suspense. Los especificadores
 * son los mismos que usan los `lazy()` de AppCore, así que el navegador reutiliza el módulo ya pedido.
 */
type Loader = () => Promise<unknown>;

const LOADERS = {
  summary: () => import("./features/summary/SummaryView"),
  clients: () => import("./features/dashboard/GeneralDashboardView"),
  subscriptions: () => import("./features/general/UnifiedSubscriptionsView"),
  charges: () => import("./features/charges/UnifiedChargesView"),
  report: () => import("./AutomaticReport"),
  channel: () => import("./features/dashboard/ChannelDashboardView"),
  recovery: () => import("./features/recovery/GeneralRecoveryPage"),
  billing: () => import("./features/billing/BillingInbox"),
  cancellations: () => import("./features/cancellations/CancellationsInbox"),
  admin: () => import("./features/admin/AdminPanel"),
  tch: () => import("./features/tch/TchContent"),
} satisfies Record<string, Loader>;

export function loaderForPath(pathname: string): Loader | null {
  const path = pathname.split("?")[0].replace(/\/+$/, "");
  if (path === "") return LOADERS.summary; // la raíz abre el Resumen
  const route = parseRoute(path);
  if (!route) return null;
  switch (route.kind) {
    case "central": return LOADERS[route.view];
    case "channel": return LOADERS.channel;
    case "recovery": return LOADERS.recovery;
    case "billingChanges": return LOADERS.billing;
    case "cancellations": return LOADERS.cancellations;
    case "admin": return LOADERS.admin;
    case "tch": case "tchSubscription": return LOADERS.tch;
    default: return null;
  }
}

/** Dispara la descarga del chunk de la ruta; un fallo no hace nada (el lazy() lo reintenta al montar). */
export function preloadRouteChunk(pathname: string = window.location.pathname): void {
  const loader = loaderForPath(pathname);
  if (loader) void loader().catch(() => undefined);
}
