export type ProviderSource = "virtualpos" | "toku" | "payku";

export type ProviderSection = { source: ProviderSource; resource: string; label: string };

/** Vistas de TCH. Las URLs siguen en español (`/tch/clientes`…) y los permisos también (`tch.clientes.view`): solo el nombre interno es inglés. */
export type TchRouteView = "summary" | "clients" | "subscriptions" | "transactions";
const TCH_URL_SEGMENT: Record<Exclude<TchRouteView, "summary">, string> = { clients: "clientes", subscriptions: "suscripciones", transactions: "transacciones" };

/** Segmento español de la vista de TCH, para armar el permiso `tch.<segmento>.view` (contrato con el backend). */
export const tchPermissionSegment = (view: Exclude<TchRouteView, "summary">): string => TCH_URL_SEGMENT[view];

export type AppRoute =
  | { kind: "central"; view: "summary" | "classic" | "clients" | "subscriptions" | "report" }
  | { kind: "channel"; source: ProviderSource }
  | { kind: "resource"; source: ProviderSource; resource: string }
  | { kind: "record"; source: ProviderSource; resource: string; externalId: string }
  | { kind: "recovery" }
  | { kind: "billingChanges" }
  | { kind: "cancellations" }
  | { kind: "tch"; view: TchRouteView }
  | { kind: "tchSubscription"; fileNumber: number }
  | { kind: "admin"; view: "users" | "sync" }
  | { kind: "profile"; view: "summary" | "edit" };

const resourceRoutes: Record<string, Record<string, string>> = {
  virtualpos: {
    clientes: "client",
    planes: "plan",
    suscripciones: "subscription",
    cargos: "charge",
    transacciones: "payment",
  },
  toku: {
    clientes: "customer",
    suscripciones: "subscription",
    "metodos-pago": "payment_method",
    deudas: "invoice",
    transacciones: "transaction",
  },
  payku: {
    clientes: "client",
    planes: "plan",
    suscripciones: "subscription",
    transacciones: "transaction",
  },
};

function decodeSegment(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

export function parseRoute(pathname: string): AppRoute | null {
  const parts = pathname.replace(/\/+$/, "").split("/").filter(Boolean);

  if (parts[0] === "central") {
    if (parts[1] === "clientes") return { kind: "central", view: "clients" };
    if (parts[1] === "suscripciones") return { kind: "central", view: "subscriptions" };
    if (parts[1] === "resumen") return { kind: "central", view: "summary" };
    // Vista anterior del resumen (TRANSITORIA, fuera del menú; se retira con UX-15).
    if (parts[1] === "resumen-clasico") return { kind: "central", view: "classic" };
    if (parts[1] === "reporte-automatico") return { kind: "central", view: "report" };
    return null;
  }

  if (parts[0] === "mi-perfil") {
    if (parts.length === 1) return { kind: "profile", view: "summary" };
    if (parts.length === 2 && parts[1] === "editar") return { kind: "profile", view: "edit" };
    return null;
  }

  if (parts[0] === "admin") {
    if (parts[1] === "usuarios") return { kind: "admin", view: "users" };
    if (parts[1] === "sincronizaciones") return { kind: "admin", view: "sync" };
    return null;
  }

  if (parts[0] === "tch") {
    if (parts[1] === "suscripciones" && parts.length === 3) {
      const fileNumber = Number(parts[2]);
      if (Number.isSafeInteger(fileNumber) && fileNumber > 0) return { kind: "tchSubscription", fileNumber };
      return null;
    }
    if (parts.length === 2) {
      const view = (Object.keys(TCH_URL_SEGMENT) as Array<Exclude<TchRouteView, "summary">>).find((key) => TCH_URL_SEGMENT[key] === parts[1]);
      if (view) return { kind: "tch", view };
    }
    if (parts.length === 2 && parts[1] === "resumen") return { kind: "tch", view: "summary" };
    return null;
  }

  if (parts[0] === "virtualpos" && parts[1] === "recuperador-socios") return { kind: "recovery" };
  if (parts[0] === "general" && parts[1] === "cambios-de-cobro" && parts.length === 2) return { kind: "billingChanges" };
  if (parts[0] === "general" && parts[1] === "bajas" && parts.length === 2) return { kind: "cancellations" };
  // Ruta anterior (grupo VirtualPOS): sigue resolviendo; AppCore la redirige a la ruta canónica.
  if (parts[0] === "virtualpos" && parts[1] === "cambios-de-cobro" && parts.length === 2) return { kind: "billingChanges" };

  const source = parts[0];
  if (source === "virtualpos" || source === "toku" || source === "payku") {
    if (parts.length === 2 && parts[1] === "resumen") return { kind: "channel", source };
    const resource = resourceRoutes[source][parts[1] ?? ""];
    if (resource && parts.length === 2) return { kind: "resource", source, resource };
    if (resource && parts.length === 3) {
      const externalId = decodeSegment(parts[2]);
      if (externalId) return { kind: "record", source, resource, externalId };
    }
  }

  return null;
}

/** Ruta canónica si `pathname` es una ruta antigua que debe redirigirse (reemplazando el historial); null si no. */
export function legacyRedirectPath(pathname: string): string | null {
  const route = parseRoute(pathname);
  if (!route) return null;
  const canonical = routePath(route);
  return pathname.replace(/\/+$/, "") === canonical ? null : canonical;
}

export function routePath(route: AppRoute): string {
  if (route.kind === "central") {
    if (route.view === "summary") return "/central/resumen";
    if (route.view === "classic") return "/central/resumen-clasico";
    if (route.view === "clients") return "/central/clientes";
    if (route.view === "subscriptions") return "/central/suscripciones";
    return "/central/reporte-automatico";
  }
  if (route.kind === "channel") return `/${route.source}/resumen`;
  if (route.kind === "recovery") return "/virtualpos/recuperador-socios";
  if (route.kind === "billingChanges") return "/general/cambios-de-cobro";
  if (route.kind === "cancellations") return "/general/bajas";
  if (route.kind === "tch") return `/tch/${route.view === "summary" ? "resumen" : TCH_URL_SEGMENT[route.view]}`;
  if (route.kind === "tchSubscription") return `/tch/suscripciones/${route.fileNumber}`;
  if (route.kind === "admin") return `/admin/${route.view === "users" ? "usuarios" : "sincronizaciones"}`;
  if (route.kind === "profile") return route.view === "edit" ? "/mi-perfil/editar" : "/mi-perfil";

  const paths: Record<string, Record<string, string>> = {
    virtualpos: { client: "clientes", plan: "planes", subscription: "suscripciones", charge: "cargos", payment: "transacciones" },
    toku: { customer: "clientes", subscription: "suscripciones", payment_method: "metodos-pago", invoice: "deudas", transaction: "transacciones" },
    payku: { client: "clientes", plan: "planes", subscription: "suscripciones", transaction: "transacciones" },
  };
  const resourcePath = `/${route.source}/${paths[route.source][route.resource]}`;
  return route.kind === "record" ? `${resourcePath}/${encodeURIComponent(route.externalId)}` : resourcePath;
}
