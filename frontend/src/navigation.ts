/** Grupos de proveedor, secciones y helpers de permisos de navegación. */

import type { ProviderSection, ProviderSource } from "./routes";

export type { ProviderSection, ProviderSource };

export const providerGroups: { name: string; sections: ProviderSection[] }[] = [
  {
    name: "VirtualPOS",
    sections: [
      { source: "virtualpos", resource: "client", label: "Clientes" },
      { source: "virtualpos", resource: "plan", label: "Planes" },
      { source: "virtualpos", resource: "subscription", label: "Subscripciones" },
      { source: "virtualpos", resource: "charge", label: "Cargos" },
      { source: "virtualpos", resource: "payment", label: "Transacciones" },
    ],
  },
  {
    name: "Toku",
    sections: [
      { source: "toku", resource: "customer", label: "Clientes" },
      { source: "toku", resource: "subscription", label: "Subscripciones" },
      { source: "toku", resource: "payment_method", label: "Metodos de pago" },
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
