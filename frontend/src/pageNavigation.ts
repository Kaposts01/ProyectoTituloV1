import { menuGroups, providerGroups } from "./navigation";
import { pageLabels } from "./pageLabels";
import { routePath, type AppRoute } from "./routes";

export type PageCrumb = { label: string; href?: string };
export type PageLocation = { title: string; crumbs: PageCrumb[] };
type LocalTchDetail = "client-detail" | "subscription-detail" | "transaction-detail";

const providerNames = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
const detailNames: Record<string, string> = {
  client: "cliente", customer: "cliente", plan: "plan", subscription: "suscripción",
  charge: "cargo", payment: "transacción", transaction: "transacción",
  payment_method: "método de pago", invoice: "deuda",
};

/** Uses existing destinations and permission guards; labels never contain record IDs or personal data. */
export function pageLocation(route: AppRoute, allowed: (route: AppRoute) => boolean, tchDetail?: string | null): PageLocation {
  const crumbs: PageCrumb[] = [];
  const dashboard: AppRoute = { kind: "central", view: "summary" };
  const addDestination = (label: string, target: AppRoute) => {
    crumbs.push({ label, ...(allowed(target) ? { href: routePath(target) } : {}) });
  };
  if (!(route.kind === "central" && route.view === "summary") && allowed(dashboard)) {
    addDestination(pageLabels.dashboard, dashboard);
  }

  if (route.kind === "profile") {
    crumbs.push({ label: "Cuenta" });
    if (route.view === "edit") addDestination(pageLabels.profile, { kind: "profile", view: "summary" });
    crumbs.push({ label: route.view === "edit" ? "Editar perfil" : pageLabels.profile });
  } else if (["channel", "resource", "record", "tch", "tchSubscription"].includes(route.kind)) {
    crumbs.push({ label: "Detalle por canal" });
    if (route.kind === "channel" || route.kind === "resource" || route.kind === "record") {
      addDestination(providerNames[route.source], { kind: "channel", source: route.source });
      if (route.kind === "channel") crumbs.push({ label: "Resumen" });
      else {
        const section = providerGroups.flatMap((group) => group.sections).find((s) => s.source === route.source && s.resource === route.resource);
        if (route.kind === "record") {
          addDestination(section?.label ?? "Registros", { kind: "resource", source: route.source, resource: route.resource });
          crumbs.push({ label: `Detalle de ${detailNames[route.resource] ?? "registro"}` });
        } else crumbs.push({ label: section?.label ?? "Registros" });
      }
    } else if (route.kind === "tch" || route.kind === "tchSubscription") {
      addDestination("TCH", { kind: "tch", view: "summary" });
      if (route.kind === "tchSubscription") {
        addDestination("Suscripciones", { kind: "tch", view: "subscriptions" });
        crumbs.push({ label: "Detalle de suscripción" });
      } else {
        const labels = { summary: "Resumen", clients: "Clientes", subscriptions: "Suscripciones", transactions: "Transacciones" };
        const localDetails: Record<LocalTchDetail, { view: "clients" | "subscriptions" | "transactions"; label: string }> = {
          "client-detail": { view: "clients", label: "Detalle de cliente" },
          "subscription-detail": { view: "subscriptions", label: "Detalle de suscripción" },
          "transaction-detail": { view: "transactions", label: "Detalle de transacción" },
        };
        const detail = tchDetail && Object.hasOwn(localDetails, tchDetail) ? localDetails[tchDetail as LocalTchDetail] : null;
        if (detail) {
          addDestination(labels[detail.view], { kind: "tch", view: detail.view });
          crumbs.push({ label: detail.label });
        } else crumbs.push({ label: labels[route.view] });
      }
    }
  } else {
    const matches = (action: (typeof menuGroups)[number]["items"][number]["action"]) => {
      if (action.kind === "central") return route.kind === "central" && route.view === action.view;
      if (action.kind === "admin") return route.kind === "admin" && route.view === action.view;
      return route.kind === ({ recovery: "recovery", billing: "billingChanges", cancellations: "cancellations" } as const)[action.kind];
    };
    const group = menuGroups.find((g) => g.items.some((item) => matches(item.action)));
    const item = group?.items.find((entry) => matches(entry.action));
    if (group?.label) crumbs.push({ label: group.label });
    crumbs.push({ label: item?.label ?? "SynkmetriX" });
  }
  const current = crumbs.at(-1)!;
  delete current.href;
  const provider = "source" in route ? providerNames[route.source] : route.kind === "tch" || route.kind === "tchSubscription" ? "TCH" : null;
  return { crumbs, title: `${current.label}${provider ? ` · ${provider}` : ""}` };
}
