/** Grupos de proveedor, secciones y helpers de permisos de navegación. */

import { PERM_VIEW as PERM_BILLING_VIEW } from "./features/billing/types";
import { PERM_CANCELLATION_VIEW } from "./features/cancellations/types";
import { canOpenRecovery } from "./features/recovery/recoveryChannels";
import type { ProviderSection, ProviderSource, TchRouteView } from "./routes";

export type { ProviderSection, ProviderSource };

export const providerGroups: { name: string; sections: ProviderSection[] }[] = [
  {
    name: "VirtualPOS",
    sections: [
      { source: "virtualpos", resource: "client", label: "Clientes" },
      { source: "virtualpos", resource: "plan", label: "Planes" },
      { source: "virtualpos", resource: "subscription", label: "Suscripciones" },
      { source: "virtualpos", resource: "charge", label: "Cargos" },
      { source: "virtualpos", resource: "payment", label: "Transacciones" },
    ],
  },
  {
    name: "Toku",
    sections: [
      { source: "toku", resource: "customer", label: "Clientes" },
      { source: "toku", resource: "subscription", label: "Suscripciones" },
      { source: "toku", resource: "payment_method", label: "Métodos de pago" },
      { source: "toku", resource: "invoice", label: "Deudas" },
      { source: "toku", resource: "transaction", label: "Transacciones" },
    ],
  },
  {
    name: "Payku",
    sections: [
      { source: "payku", resource: "client", label: "Clientes" },
      { source: "payku", resource: "subscription", label: "Suscripciones" },
      { source: "payku", resource: "transaction", label: "Transacciones" },
      { source: "payku", resource: "plan", label: "Planes" },
    ],
  },
];

export function resourcePermission(source: string, resource: string): string {
  const names: Record<string, Record<string, string>> = {
    virtualpos: { client: "clients", plan: "plans", subscription: "subscriptions", charge: "charges", payment: "payments" },
    toku: { customer: "customers", subscription: "subscriptions", payment_method: "payment_methods", invoice: "invoices", transaction: "transactions" },
    payku: { client: "clients", plan: "plans", subscription: "subscriptions", transaction: "transactions" },
  };
  return `${source}.${names[source]?.[resource] ?? resource}.view`;
}

/* ── Menú de un solo nivel (UX-05, D29) ─────────────────────────────────────────────
   Grupos: Resumen · Cartera · Operación · Sistema, más el grupo transitorio «Detalle por canal».
   Solo contiene vistas que existen hoy. Fuera del menú, a propósito:
   - Cobros (Cartera): aún no hay vista unificada; entra con UX-09.
   - Identidad (Operación): no existe pantalla (cola de candidatos, UX-11).
   Las rutas no cambian: el menú solo reagrupa y renombra. */

export type Can = (permission: string) => boolean;

export type MenuAction =
  | { kind: "central"; view: "summary" | "clients" | "subscriptions" | "report" }
  | { kind: "recovery" }
  | { kind: "billing" }
  | { kind: "cancellations" }
  | { kind: "admin"; view: "users" | "sync" };

export type MenuItem = { id: string; label: string; action: MenuAction; allowed: (can: Can) => boolean };
/** `label: null` = grupo sin encabezado (Resumen). */
export type MenuGroup = { id: string; label: string | null; items: MenuItem[] };

const canDashboard: MenuItem["allowed"] = (can) => can("dashboard.view");

/** Permiso general de Cambios de cobro (UX-12). El permiso VirtualPOS sigue valiendo (la API acepta ambos). */
export const PERM_GENERAL_BILLING_VIEW = "general.billing_changes.view";
export const canOpenBilling = (can: Can): boolean => can(PERM_GENERAL_BILLING_VIEW) || can(PERM_BILLING_VIEW);
export { canOpenRecovery };

export const menuGroups: MenuGroup[] = [
  { id: "resumen", label: null, items: [{ id: "summary", label: "Resumen", action: { kind: "central", view: "summary" }, allowed: canDashboard }] },
  {
    id: "cartera",
    label: "Cartera",
    items: [
      { id: "clients", label: "Socios", action: { kind: "central", view: "clients" }, allowed: canDashboard },
      { id: "subscriptions", label: "Suscripciones", action: { kind: "central", view: "subscriptions" }, allowed: canDashboard },
    ],
  },
  {
    id: "operacion",
    label: "Operación",
    items: [
      { id: "recovery", label: "Recuperador", action: { kind: "recovery" }, allowed: canOpenRecovery },
      { id: "billing", label: "Cambios de cobro", action: { kind: "billing" }, allowed: canOpenBilling },
      { id: "cancellations", label: "Bajas", action: { kind: "cancellations" }, allowed: (can) => can(PERM_CANCELLATION_VIEW) },
    ],
  },
  {
    id: "sistema",
    label: "Sistema",
    items: [
      { id: "sync", label: "Sincronización", action: { kind: "admin", view: "sync" }, allowed: (can) => can("sync_runs.view") || can("sync.run") },
      { id: "admin", label: "Administración", action: { kind: "admin", view: "users" }, allowed: (can) => can("users.manage") || can("roles.manage") },
      { id: "report", label: "Reportes", action: { kind: "central", view: "report" }, allowed: canDashboard },
    ],
  },
];

/** Grupos con solo los ítems permitidos; un grupo sin ítems visibles desaparece. */
export function visibleMenu(can: Can): MenuGroup[] {
  return menuGroups
    .map((group) => ({ ...group, items: group.items.filter((item) => item.allowed(can)) }))
    .filter((group) => group.items.length > 0);
}

export type TchView = TchRouteView;
export type DetailAction =
  | { kind: "channel"; source: ProviderSource }
  | { kind: "section"; section: ProviderSection }
  | { kind: "tch"; view: TchView };
export type DetailItem = { id: string; label: string; action: DetailAction };
export type DetailChannel = { id: string; name: string; items: DetailItem[] };

/**
 * «Detalle por canal» (TRANSITORIO): las pantallas por canal que siguen vivas hasta que existan las vistas
 * unificadas de Cobros, Socios y Suscripciones (UX-09 a UX-11). Mismos permisos por canal que antes.
 */
export function detailChannels(can: Can): DetailChannel[] {
  const out: DetailChannel[] = [];
  for (const group of providerGroups) {
    const sections = group.sections.filter((section) => can(resourcePermission(section.source, section.resource)));
    if (sections.length === 0) continue;
    const source = sections[0].source;
    out.push({
      id: source,
      name: group.name,
      items: [
        { id: `${source}:resumen`, label: "Resumen", action: { kind: "channel", source } },
        ...sections.map((section) => ({ id: `${source}:${section.resource}`, label: section.label, action: { kind: "section", section } as DetailAction })),
      ],
    });
  }
  if (can("tch.dashboard.view")) {
    const items: DetailItem[] = [{ id: "tch:resumen", label: "Resumen", action: { kind: "tch", view: "summary" } }];
    if (can("tch.clientes.view")) items.push({ id: "tch:clientes", label: "Clientes", action: { kind: "tch", view: "clients" } });
    if (can("tch.suscripciones.view")) items.push({ id: "tch:suscripciones", label: "Suscripciones", action: { kind: "tch", view: "subscriptions" } });
    if (can("tch.transacciones.view")) items.push({ id: "tch:transacciones", label: "Transacciones", action: { kind: "tch", view: "transactions" } });
    out.push({ id: "tch", name: "TCH", items });
  }
  return out;
}

const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

/** Filtra el menú por texto (sin tildes ni mayúsculas): coincide con el rótulo del ítem o del grupo. */
export function filterMenu(groups: MenuGroup[], channels: DetailChannel[], query: string): { groups: MenuGroup[]; channels: DetailChannel[] } {
  const q = fold(query);
  if (!q) return { groups, channels };
  return {
    groups: groups
      .map((group) => ({ ...group, items: group.items.filter((item) => fold(item.label).includes(q) || fold(group.label ?? "").includes(q)) }))
      .filter((group) => group.items.length > 0),
    channels: channels
      .map((channel) => ({ ...channel, items: channel.items.filter((item) => fold(`${channel.name} ${item.label}`).includes(q)) }))
      .filter((channel) => channel.items.length > 0),
  };
}
