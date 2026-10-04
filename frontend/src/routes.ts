export type ProviderSource = "virtualpos" | "toku" | "payku";

export type AppRoute =
  | { kind: "central"; view: "summary" | "clients" | "subscriptions" }
  | { kind: "channel"; source: ProviderSource }
  | { kind: "resource"; source: ProviderSource; resource: string }
  | { kind: "record"; source: ProviderSource; resource: string; externalId: string }
  | { kind: "recovery" }
  | { kind: "tch"; view: "summary" | "clientes" | "suscripciones" | "transacciones" }
  | { kind: "tchSubscription"; numeroFicha: number }
  | { kind: "admin"; view: "usuarios" | "sincronizacion" }
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
    return null;
  }

  if (parts[0] === "mi-perfil") {
    if (parts.length === 1) return { kind: "profile", view: "summary" };
    if (parts.length === 2 && parts[1] === "editar") return { kind: "profile", view: "edit" };
    return null;
  }

  if (parts[0] === "admin") {
    if (parts[1] === "usuarios") return { kind: "admin", view: "usuarios" };
    if (parts[1] === "sincronizaciones") return { kind: "admin", view: "sincronizacion" };
    return null;
  }

  if (parts[0] === "tch") {
    if (parts[1] === "suscripciones" && parts.length === 3) {
      const numeroFicha = Number(parts[2]);
      if (Number.isSafeInteger(numeroFicha) && numeroFicha > 0) return { kind: "tchSubscription", numeroFicha };
      return null;
    }
    if (parts.length === 2 && (parts[1] === "clientes" || parts[1] === "suscripciones" || parts[1] === "transacciones")) {
      return { kind: "tch", view: parts[1] };
    }
    if (parts.length === 2 && parts[1] === "resumen") return { kind: "tch", view: "summary" };
    return null;
  }

  if (parts[0] === "virtualpos" && parts[1] === "recuperador-socios") return { kind: "recovery" };

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

export function routePath(route: AppRoute): string {
  if (route.kind === "central") return route.view === "summary" ? "/central/resumen" : `/central/${route.view === "clients" ? "clientes" : "suscripciones"}`;
  if (route.kind === "channel") return `/${route.source}/resumen`;
  if (route.kind === "recovery") return "/virtualpos/recuperador-socios";
  if (route.kind === "tch") return `/tch/${route.view === "summary" ? "resumen" : route.view}`;
  if (route.kind === "tchSubscription") return `/tch/suscripciones/${route.numeroFicha}`;
  if (route.kind === "admin") return `/admin/${route.view === "usuarios" ? "usuarios" : "sincronizaciones"}`;
  if (route.kind === "profile") return route.view === "edit" ? "/mi-perfil/editar" : "/mi-perfil";

  const paths: Record<string, Record<string, string>> = {
    virtualpos: { client: "clientes", plan: "planes", subscription: "suscripciones", charge: "cargos", payment: "transacciones" },
    toku: { customer: "clientes", subscription: "suscripciones", payment_method: "metodos-pago", invoice: "deudas", transaction: "transacciones" },
    payku: { client: "clientes", plan: "planes", subscription: "suscripciones", transaction: "transacciones" },
  };
  const resourcePath = `/${route.source}/${paths[route.source][route.resource]}`;
  return route.kind === "record" ? `${resourcePath}/${encodeURIComponent(route.externalId)}` : resourcePath;
}
