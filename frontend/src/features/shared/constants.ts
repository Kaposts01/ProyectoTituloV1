import { CHART_PRIMARY } from "../../chartColors";

export const virtualPosMetrics = [
  { resource: "client", label: "Clientes", tone: "blue" },
  { resource: "plan", label: "Planes", tone: "violet" },
  { resource: "subscription", label: "Subscripciones Activas", tone: "gold", amount: true },
  { resource: "subscription_cobrable", label: "Subscripciones Cobrables", tone: "teal", amount: true },
  { resource: "charge", label: "Cargos Pagados", tone: "orange", amount: true },
  { resource: "payment", label: "Transacciones Pagadas", tone: "green", amount: true },
];
export const tokuMetrics = [
  { resource: "customer", label: "Clientes", tone: "blue" },
  { resource: "subscription", label: "Subscripciones activas", tone: "violet", amount: true },
  { resource: "payment_method", label: "Metodos de pago cobrables", tone: "gold" },
  { resource: "invoice", label: "Deudas pagadas", tone: "orange", amount: true },
  { resource: "transaction", label: "Transacciones pagadas", tone: "green", amount: true },
];
export const paykuMetrics = [
  { resource: "client", label: "Clientes", tone: "blue" },
  { resource: "plan", label: "Planes", tone: "violet" },
  { resource: "subscription", label: "Suscripciones", tone: "gold", amount: true },
  { resource: "transaction", label: "Transacciones", tone: "green", amount: true },
];
export const statusResourceOrder: Record<string, string[]> = {
  virtualpos: ["client", "subscription", "charge", "payment", "plan"],
  toku: ["customer", "subscription", "payment_method", "invoice", "transaction"],
  payku: ["client", "subscription", "plan", "transaction"],
};
export const statusResourceLabels: Record<string, string> = {
  client: "Clientes",
  customer: "Clientes",
  subscription: "Subscripciones",
  charge: "Cargos",
  payment: "Transacciones",
  transaction: "Transacciones",
  plan: "Planes",
  payment_method: "Metodos de pago",
  invoice: "Deudas",
};
export const months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
export const METRIC_COLORS: Record<string, string> = {
  blue: "#4a90c4",
  violet: "#7b6cc7",
  gold: "#c49d30",
  orange: "#d46a2a",
  green: "#3ba675",
  teal: "#2ab8a8",
};
export const CHANNEL_COLORS: Record<string, string> = {
  virtualpos: CHART_PRIMARY,
  toku: CHART_PRIMARY,
  payku: CHART_PRIMARY,
};
