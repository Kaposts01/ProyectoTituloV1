import { lazy, Suspense, useEffect, useState } from "react";
import "./App.css";
import "./Staging.css";
import { MonthlySimpleChart, MonthlyStatusChart } from "./MonthlyStatusChart";
import type { MonthlyEntry, MonthlyStatusEntry } from "./MonthlyStatusChart";

const ChannelActivityChart = lazy(() => import("./ChannelActivityChart"));

type SyncRun = { status: string; records_processed: number };
type SourceSummary = {
  source: string;
  records: number;
  resources: Record<string, number>;
  last_sync: SyncRun | null;
};
type Summary = { sources: SourceSummary[] };
type StagingRecord = {
  id: string;
  source: string;
  resource_type: string;
  external_id: string;
  payload: Record<string, unknown>;
};
type StagingResponse = { items: StagingRecord[]; total: number };
type ProviderSection = { source: string; resource: string; label: string };
type TableColumn = { label: string; value: (record: StagingRecord) => string };
type Activity = { year: number; month: number; count: number; amount: number };
type VpKpis = {
  mrr: number;
  active_subscribers: number;
  active_clients: number;
  arpu: number;
  churn_rate: number;
  ltv: number;
};
type ChannelDashboard = {
  source: string;
  records: number;
  resources: Record<string, number>;
  resource_amounts: Record<string, number>;
  statuses: { resource: string; status: string; count: number }[];
  activity_resource: string;
  activity: Activity[];
  years: number[];
  last_sync: SyncRun | null;
  kpis?: VpKpis;
  // VirtualPOS extended
  charges_monthly?: MonthlyStatusEntry[];
  payments_monthly?: MonthlyStatusEntry[];
  // Toku extended
  invoices_monthly?: MonthlyStatusEntry[];
  transactions_monthly?: MonthlyEntry[] | MonthlyStatusEntry[];
  // Shared
  activation_monthly?: MonthlyEntry[];
  churn_monthly?: MonthlyEntry[];
};
type VirtualPosClientDetail = {
  client: StagingRecord;
  subscriptions: StagingRecord[];
  subscription_total: number;
};
type VirtualPosPlanDetail = {
  plan: StagingRecord;
  subscriptions: StagingRecord[];
  subscription_total: number;
};
type VirtualPosSubscriptionDetail = {
  subscription: StagingRecord;
  payment_method: unknown;
  charges: StagingRecord[];
  charge_total: number;
};
type VirtualPosChargeDetail = { charge: StagingRecord };
type VirtualPosPaymentDetail = { payment: StagingRecord };
type RelatedRecords = {
  label: string;
  resource_type: string;
  items: StagingRecord[];
};
type ProviderRecordDetail = {
  record: StagingRecord;
  related: RelatedRecords[];
};
type FilterOption = { value: string; label: string };
type ClientEditField = { name: string; label: string; type?: string };

const providerGroups: { name: string; sections: ProviderSection[] }[] = [
  {
    name: "VirtualPOS",
    sections: [
      { source: "virtualpos", resource: "client", label: "Clientes" },
      { source: "virtualpos", resource: "plan", label: "Planes" },
      {
        source: "virtualpos",
        resource: "subscription",
        label: "Subscripciones",
      },
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
const virtualPosMetrics = [
  { resource: "client", label: "Clientes", tone: "blue" },
  { resource: "plan", label: "Planes", tone: "violet" },
  { resource: "subscription", label: "Subscripciones", tone: "gold", amount: true },
  { resource: "charge", label: "Cargos", tone: "orange", amount: true },
  { resource: "payment", label: "Transacciones", tone: "green", amount: true },
];
const tokuMetrics = [
  { resource: "customer", label: "Clientes", tone: "blue" },
  { resource: "subscription", label: "Subscripciones", tone: "violet" },
  { resource: "payment_method", label: "Metodos de pago", tone: "gold" },
  { resource: "invoice", label: "Deudas", tone: "orange" },
  { resource: "transaction", label: "Transacciones", tone: "green" },
];
const paykuMetrics = [
  { resource: "client", label: "Clientes", tone: "blue" },
  { resource: "plan", label: "Planes", tone: "violet" },
  { resource: "subscription", label: "Suscripciones", tone: "gold" },
  { resource: "transaction", label: "Transacciones", tone: "green" },
];
const statusResourceOrder: Record<string, string[]> = {
  virtualpos: ["client", "subscription", "charge", "payment", "plan"],
  toku: ["customer", "subscription", "payment_method", "invoice", "transaction"],
  payku: ["client", "subscription", "plan", "transaction"],
};
const statusResourceLabels: Record<string, string> = {
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
const months = [
  "Ene",
  "Feb",
  "Mar",
  "Abr",
  "May",
  "Jun",
  "Jul",
  "Ago",
  "Sep",
  "Oct",
  "Nov",
  "Dic",
];
const METRIC_COLORS: Record<string, string> = {
  blue: "#4a90c4",
  violet: "#7b6cc7",
  gold: "#c49d30",
  orange: "#d46a2a",
  green: "#3ba675",
};
const CHANNEL_COLORS: Record<string, string> = {
  virtualpos: "#0A5657",
  toku: "#8000CC",
  payku: "#2800D9",
};
const STATUS_PALETTE = [
  "#3ba675",
  "#4a90c4",
  "#7b6cc7",
  "#c49d30",
  "#d46a2a",
  "#a53d35",
  "#728186",
  "#2d6a4f",
];
const virtualPosClientFields = [
  "uuid",
  "status",
  "type",
  "first_name",
  "last_name",
  "email",
  "phone_number",
  "social_id_type",
  "social_id",
  "birth_date",
  "gender_id",
  "created",
  "updated",
];
const virtualPosClientFieldLabels: Record<string, string> = {
  uuid: "UUID",
  status: "Estado",
  type: "Tipo",
  first_name: "Nombre",
  last_name: "Apellido",
  email: "Correo electronico",
  phone_number: "Telefono",
  social_id_type: "Tipo documento",
  social_id: "RUT documento",
  birth_date: "Fecha nacimiento",
  gender_id: "Genero",
  created: "Creado",
  updated: "Actualizado",
};
const virtualPosDocumentTypes: Record<string, string> = { "1": "RUT", "2": "DNI" };
const fieldLabels: Record<string, string> = {
  id: "ID",
  uuid: "UUID",
  status: "Estado",
  type: "Tipo",
  name: "Nombre",
  first_name: "Nombre",
  last_name: "Apellido",
  description: "Descripcion",
  email: "Correo electronico",
  mail: "Correo electronico",
  phone: "Telefono",
  phone_number: "Telefono",
  government_id: "RUT",
  social_id_type: "Tipo documento",
  social_id: "RUT documento",
  birth_date: "Fecha nacimiento",
  gender_id: "Genero",
  is_active: "Activo",
  amount: "Monto",
  activation_amount: "Monto activacion",
  currency: "Moneda",
  trial_days: "Dias de prueba",
  num_charges: "Cantidad de cargos",
  frequency_type: "Frecuencia",
  return_url: "URL retorno",
  suscription_url: "URL subscripcion",
  fixed_amount_day_charge: "Dia cobro monto fijo",
  automatic_renewal: "Renovacion automatica",
  show_in_terminal: "Visible en terminal",
  created: "Creado",
  created_at: "Fecha creacion",
  updated: "Actualizado",
  updated_at: "Fecha actualizacion",
  shipping_address: "Direccion de envio",
  plan_id: "ID plan",
  plan_name: "Nombre plan",
  suscription_date: "Fecha subscripcion",
  canceled_at: "Fecha cancelacion",
  renewal: "Renovacion",
  channel: "Canal",
  customer: "Cliente",
  customer_id: "ID cliente",
  subscription: "Subscripcion",
  subscription_id: "ID subscripcion",
  subscription_ids: "IDs subscripciones",
  payment_method: "Metodo de pago",
  bank_name: "Banco",
  card_type: "Tipo tarjeta",
  is_paid: "Pagado",
  due_date: "Fecha limite",
  anchor: "Fecha inicio",
  end_date: "Fecha cancelacion",
  transaction_date: "Fecha transaccion",
  subscriptions: "Subscripciones",
  start: "Fecha inicio",
  end: "Fecha termino",
  rut: "RUT",
  address: "Direccion",
  city: "Ciudad",
  region: "Region",
  country: "Pais",
  postal_code: "Codigo postal",
  private_note: "Nota privada",
};
const recurringFieldLabels: Record<string, string> = {
  amount: "Monto",
  anchor: "Fecha inicio",
  status: "Estado",
  due_day: "Dia de cobro",
  end_date: "Fecha termino",
  interval: "Intervalo",
  frequency: "Frecuencia",
  creation_lead_days: "Dias de anticipacion",
  max_active_invoices: "Maximo de facturas activas",
};
const virtualPosPlanFields = [
  "id",
  "name",
  "description",
  "is_active",
  "amount",
  "activation_amount",
  "currency",
  "trial_days",
  "num_charges",
  "frequency_type",
  "return_url",
  "suscription_url",
  "type",
  "fixed_amount_day_charge",
  "automatic_renewal",
  "show_in_terminal",
  "created_at",
  "shipping_address",
];
const virtualPosSubscriptionFields = [
  "status",
  "id",
  "plan_name",
  "suscription_date",
  "canceled_at",
  "currency",
  "amount",
  "renewal",
  "channel",
];
const virtualPosClientEditFields: ClientEditField[] = [
  { name: "status", label: "Estado" },
  { name: "type", label: "Tipo" },
  { name: "first_name", label: "Nombre" },
  { name: "last_name", label: "Apellido" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone_number", label: "Teléfono", type: "tel" },
  { name: "social_id_type", label: "Tipo de documento" },
  { name: "social_id", label: "RUT / documento" },
  { name: "birth_date", label: "Fecha de nacimiento", type: "date" },
  { name: "gender_id", label: "Género" },
];
const stagingFilters: Record<string, Record<string, FilterOption[]>> = {
  virtualpos: {
    client: [{ value: "uuid", label: "UUID" }, { value: "social_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "email", label: "Email" }, { value: "phone_number", label: "Teléfono" }, { value: "status", label: "Estado" }],
    plan: [{ value: "id", label: "ID" }, { value: "name", label: "Nombre" }, { value: "amount", label: "Monto" }, { value: "automatic_renewal", label: "Renovación" }, { value: "is_active", label: "Estado" }, { value: "show_in_terminal", label: "Activo en POS" }],
    subscription: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "suscription_date", label: "F. Inicio" }, { value: "canceled_at", label: "F. Cancelación" }],
    charge: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "charge_date", label: "Fecha de cargo" }],
    payment: [{ value: "uuid", label: "UUID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "authorized_at", label: "F. Pago" }],
  },
  toku: {
    customer: [{ value: "id", label: "ID" }, { value: "government_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "mail", label: "Mail" }, { value: "phone_number", label: "Teléfono" }],
    subscription: [{ value: "id", label: "ID" }, { value: "customer", label: "ID cliente" }, { value: "amount", label: "Monto" }, { value: "status", label: "Estado" }, { value: "anchor", label: "F. Inicio" }, { value: "end_date", label: "F. Cancelación" }],
    payment_method: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "created_at", label: "F. Creación" }, { value: "bank_name", label: "Banco" }, { value: "card_type", label: "Tipo tarjeta" }, { value: "customer_id", label: "ID cliente" }, { value: "external_id", label: "RUT" }, { value: "subscription_ids", label: "Subscripciones" }],
    invoice: [{ value: "id", label: "ID" }, { value: "customer", label: "Cliente" }, { value: "subscription", label: "Subscripción" }, { value: "amount", label: "Monto" }, { value: "is_paid", label: "Pagado" }, { value: "status", label: "Estado" }, { value: "due_date", label: "Fecha límite" }],
    transaction: [{ value: "id", label: "ID" }, { value: "customer_id", label: "ID cliente" }, { value: "subscription_id", label: "ID subscripción" }, { value: "amount", label: "Monto" }, { value: "transaction_date", label: "Fecha transacción" }],
  },
  payku: {
    client: [{ value: "id", label: "ID" }, { value: "rut", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "email", label: "Email" }, { value: "phone", label: "Teléfono" }],
    plan: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "name", label: "Nombre" }],
    subscription: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "rut", label: "RUT" }, { value: "start", label: "F. Inicio" }, { value: "end", label: "F. Cancelación" }],
    transaction: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "subscriptions", label: "ID subscripciones" }, { value: "amount", label: "Monto" }, { value: "created_at", label: "F. Pago" }],
  },
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

function text(value: unknown, fallback = "Sin dato"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function fieldLabel(field: string): string {
  return fieldLabels[field] ?? field.replaceAll("_", " ");
}

function providerRecordHeading(record: StagingRecord): string {
  if (record.source === "toku" && record.resource_type === "subscription") {
    return text(record.payload.product_id, record.external_id);
  }
  return text(record.payload.name, text(record.payload.id, record.external_id));
}

function externalUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function renewalText(value: unknown): string {
  const normalized = String(value).toLowerCase();
  if (["t", "true", "1"].includes(normalized)) return "True";
  if (["f", "false", "0"].includes(normalized)) return "False";
  return text(value);
}

function cardTypeText(value: unknown): string {
  const normalized = String(value).toUpperCase();
  if (normalized === "TC") return "Tarjeta Credito";
  if (normalized === "TD") return "Tarjeta Debito";
  if (["TP", "TPE", "PREPAGO"].includes(normalized)) return "Tarjeta Prepago";
  return text(value);
}

function isActiveSubscription(record: StagingRecord): boolean {
  return String(record.payload.status).toLowerCase() === "activa";
}

function nested(
  payload: Record<string, unknown>,
  key: string,
  child: string,
): unknown {
  const value = payload[key];
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)[child]
    : undefined;
}

function objectEntries(value: unknown): [string, unknown][] {
  return value && typeof value === "object" && !Array.isArray(value)
    ? Object.entries(value as Record<string, unknown>)
    : [];
}

function virtualPosClientName(record: StagingRecord): string {
  const client = record.payload.client;
  if (!client || typeof client !== "object") return "Sin dato";
  const payload = client as Record<string, unknown>;
  return (
    `${text(payload.first_name, "")} ${text(payload.last_name, "")}`.trim() ||
    "Sin dato"
  );
}

function active(value: unknown): string {
  return String(value).toLowerCase() === "true" ? "Activo" : "Inactivo";
}

function paid(value: unknown): string {
  if (value === true || String(value).toLowerCase() === "true") return "Pagado";
  if (value === false || String(value).toLowerCase() === "false")
    return "No pagado";
  return "Sin dato";
}

function title(source: string): string {
  return source === "virtualpos"
    ? "VirtualPOS"
    : source[0].toUpperCase() + source.slice(1);
}

function resourceTitle(resource: string): string {
  return (
    {
      customer: "Cliente",
      client: "Cliente",
      subscription: "Subscripción",
      payment_method: "Método de pago",
      invoice: "Deuda",
      transaction: "Transacción",
      plan: "Plan",
    }[resource] ?? resource
  );
}

function virtualPosColumns(resource: string): TableColumn[] {
  const clientRut = (record: StagingRecord) =>
    text(
      nested(record.payload, "client", "social_id") ?? record.payload.social_id,
    );
  if (resource === "client")
    return [
      {
        label: "UUID",
        value: (record) => text(record.payload.uuid, record.external_id),
      },
      { label: "RUT", value: (record) => text(record.payload.social_id) },
      {
        label: "Nombre",
        value: (record) =>
          `${text(record.payload.first_name, "")} ${text(record.payload.last_name, "")}`.trim() ||
          "Sin dato",
      },
      { label: "Email", value: (record) => text(record.payload.email) },
      {
        label: "Telefono",
        value: (record) => text(record.payload.phone_number),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "Acciones", value: () => "Editar" },
    ];
  if (resource === "plan")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Nombre", value: (record) => text(record.payload.name) },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      {
        label: "Renovacion",
        value: (record) => active(record.payload.automatic_renewal),
      },
      { label: "Estado", value: (record) => active(record.payload.is_active) },
      {
        label: "Activo en POS",
        value: (record) => active(record.payload.show_in_terminal),
      },
    ];
  if (resource === "subscription")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "RUT cliente", value: clientRut },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      {
        label: "F. Inicio",
        value: (record) => text(record.payload.suscription_date),
      },
      {
        label: "F. Cancelacion",
        value: (record) => text(record.payload.canceled_at),
      },
      { label: "Acciones", value: () => "Cancelar" },
    ];
  if (resource === "charge")
    return [
      {
        label: "Fecha de cargo",
        value: (record) => text(record.payload.charge_date),
      },
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "RUT cliente", value: clientRut },
      { label: "Monto", value: (record) => text(record.payload.amount) },
    ];
  return [
    {
      label: "F. Pago",
      value: (record) => text(nested(record.payload, "order", "authorized_at")),
    },
    {
      label: "UUID",
      value: (record) =>
        text(nested(record.payload, "order", "uuid") ?? record.external_id),
    },
    {
      label: "Estado",
      value: (record) => text(nested(record.payload, "order", "status")),
    },
    { label: "RUT cliente", value: clientRut },
    {
      label: "Monto",
      value: (record) => text(nested(record.payload, "order", "amount")),
    },
  ];
}

function tokuColumns(resource: string): TableColumn[] {
  if (resource === "customer")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "RUT", value: (record) => text(record.payload.government_id) },
      { label: "Nombre", value: (record) => text(record.payload.name) },
      { label: "Mail", value: (record) => text(record.payload.mail) },
      {
        label: "Telefono",
        value: (record) => text(record.payload.phone_number),
      },
    ];
  if (resource === "subscription")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "ID cliente", value: (record) => text(record.payload.customer) },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "F. Inicio", value: (record) => text(record.payload.anchor) },
      {
        label: "F. Cancelacion",
        value: (record) => text(record.payload.end_date),
      },
    ];
  if (resource === "payment_method")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      {
        label: "F. Creacion",
        value: (record) => text(record.payload.created_at),
      },
      { label: "Banco", value: (record) => text(record.payload.bank_name) },
      {
        label: "Tipo tarjeta",
        value: (record) => text(record.payload.card_type),
      },
      {
        label: "ID cliente",
        value: (record) => text(record.payload.customer_id),
      },
      { label: "RUT", value: (record) => record.external_id },
      {
        label: "Subscripciones",
        value: (record) => text(record.payload.subscription_ids),
      },
    ];
  if (resource === "invoice")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Cliente", value: (record) => text(record.payload.customer) },
      {
        label: "Subscripcion",
        value: (record) => text(record.payload.subscription),
      },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      { label: "Pagado", value: (record) => paid(record.payload.is_paid) },
      { label: "Estado", value: (record) => text(record.payload.status) },
      {
        label: "Fecha limite",
        value: (record) => text(record.payload.due_date),
      },
    ];
  return [
    {
      label: "ID",
      value: (record) => text(record.payload.id, record.external_id),
    },
    {
      label: "ID cliente",
      value: (record) => text(record.payload.customer_id),
    },
    {
      label: "ID subscripcion",
      value: (record) => text(record.payload.subscription_id),
    },
    { label: "Monto", value: (record) => text(record.payload.amount) },
    {
      label: "Fecha transaccion",
      value: (record) => text(record.payload.transaction_date),
    },
  ];
}

function paykuColumns(resource: string): TableColumn[] {
  if (resource === "client")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "RUT", value: (record) => text(record.payload.rut) },
      {
        label: "Nombre",
        value: (record) =>
          `${text(record.payload.first_name, "")} ${text(record.payload.last_name, "")}`.trim() ||
          text(record.payload.name),
      },
      { label: "Email", value: (record) => text(record.payload.email) },
      { label: "Telefono", value: (record) => text(record.payload.phone) },
    ];
  if (resource === "plan")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "Nombre", value: (record) => text(record.payload.name) },
    ];
  if (resource === "subscription")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      {
        label: "RUT",
        value: (record) => text(nested(record.payload, "client", "rut")),
      },
      { label: "F. Inicio", value: (record) => text(record.payload.start) },
      { label: "F. Cancelacion", value: (record) => text(record.payload.end) },
    ];
  return [
    {
      label: "ID",
      value: (record) => text(record.payload.id, record.external_id),
    },
    { label: "Estado", value: (record) => text(record.payload.status) },
    {
      label: "ID subscripciones",
      value: (record) => text(record.payload.subscriptions),
    },
    { label: "Monto", value: (record) => text(record.payload.amount) },
    { label: "F. Pago", value: (record) => text(record.payload.created_at) },
  ];
}

function Sidebar({
  activeSection,
  channel,
  openProvider,
  theme,
  onDashboard,
  onChannel,
  onSection,
  onToggle,
  onTheme,
}: {
  activeSection: ProviderSection | null;
  channel: string | null;
  openProvider: string | null;
  theme: "light" | "dark";
  onDashboard: () => void;
  onChannel: (source: string) => void;
  onSection: (section: ProviderSection) => void;
  onToggle: (provider: string) => void;
  onTheme: () => void;
}) {
  return (
    <aside className="sidebar">
      <button className="sidebar-brand" onClick={onDashboard}>
        <span>CRM</span>
        <strong>Suscripciones</strong>
      </button>
      <nav className="sidebar-nav" aria-label="Navegacion principal">
        <button
          className={
            !activeSection && !channel ? "sidebar-item active" : "sidebar-item"
          }
          onClick={onDashboard}
        >
          Dashboard
        </button>
        {providerGroups.map((group) => (
          <section className="sidebar-group" key={group.name}>
            <div className="channel-heading">
              <button
                className={
                  channel === group.sections[0].source
                    ? "channel-dashboard active"
                    : "channel-dashboard"
                }
                onClick={() => onChannel(group.sections[0].source)}
              >
                {group.name}
              </button>
              <button
                className="sidebar-expand"
                aria-label={`Expandir ${group.name}`}
                aria-expanded={openProvider === group.name}
                onClick={() => onToggle(group.name)}
              >
                {openProvider === group.name ? "-" : "+"}
              </button>
            </div>
            {openProvider === group.name
              ? group.sections.map((section) => (
                  <button
                    className={
                      activeSection?.source === section.source &&
                      activeSection.resource === section.resource
                        ? "sidebar-item nested active"
                        : "sidebar-item nested"
                    }
                    key={section.resource}
                    onClick={() => onSection(section)}
                  >
                    {section.label}
                  </button>
                ))
              : null}
          </section>
        ))}
        <section className="sidebar-group">
          <button className="sidebar-toggle" disabled>
            TCH <span>+</span>
          </button>
        </section>
      </nav>
      <div className="sidebar-footer">
        <button className="theme-btn" onClick={onTheme} aria-label="Cambiar tema">
          <span className="theme-btn-icon">{theme === "dark" ? "☀" : "◐"}</span>
          {theme === "dark" ? "Modo claro" : "Modo oscuro"}
        </button>
      </div>
    </aside>
  );
}

function Metric({
  label,
  value,
  tone,
  amount,
}: {
  label: string;
  value: number;
  tone: string;
  amount?: number;
}) {
  const accent = METRIC_COLORS[tone] ?? "#4a90c4";
  return (
    <article
      className="metric-card"
      style={{ "--accent": accent } as React.CSSProperties}
    >
      <p className="metric-label">{label}</p>
      <strong className="metric-value">
        {value.toLocaleString("es-CL")}
      </strong>
      {amount !== undefined ? (
        <span className="metric-amount">
          ${amount.toLocaleString("es-CL")}
        </span>
      ) : null}
    </article>
  );
}

function KpiCard({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: string;
  caption?: string;
  tone: string;
}) {
  const accent = METRIC_COLORS[tone] ?? "#4a90c4";
  return (
    <article
      className="metric-card kpi-card"
      style={{ "--accent": accent } as React.CSSProperties}
    >
      <p className="metric-label">{label}</p>
      <strong className="metric-value kpi-value">{value}</strong>
      {caption ? <span className="metric-amount">{caption}</span> : null}
    </article>
  );
}

function StatusBars({
  source,
  statuses,
  resources,
}: {
  source: string;
  statuses: { resource: string; status: string; count: number }[];
  resources: Record<string, number>;
}) {
  const grouped = new Map<string, { status: string; count: number }[]>();
  for (const entry of statuses) {
    const list = grouped.get(entry.resource) ?? [];
    list.push({ status: entry.status, count: entry.count });
    grouped.set(entry.resource, list);
  }
  const preferred = statusResourceOrder[source] ?? [];
  const rows = [
    ...preferred,
    ...[...grouped.keys()].filter((r) => !preferred.includes(r)),
  ].filter(
    (r, i, arr) =>
      arr.indexOf(r) === i && (grouped.has(r) || (resources[r] ?? 0) > 0),
  );
  if (!rows.length) {
    return (
      <p className="empty-chart">Este canal no entrega estados normalizados.</p>
    );
  }
  return (
    <div className="status-bars">
      {rows.map((resource) => {
        const items = [...(grouped.get(resource) ?? [])].sort(
          (a, b) => b.count - a.count,
        );
        const total =
          items.reduce((s, item) => s + item.count, 0) ||
          (resources[resource] ?? 0);
        return (
          <div key={resource} className="status-bar-row">
            <div className="status-bar-header">
              <span>{statusResourceLabels[resource] ?? resource}</span>
              <b>{total}</b>
            </div>
            <div className="status-bar-track">
              {items.length ? (
                items.map((item, i) => (
                  <div
                    key={item.status}
                    className="status-bar-segment"
                    style={{
                      width: `${(item.count / total) * 100}%`,
                      background: STATUS_PALETTE[i % STATUS_PALETTE.length],
                    }}
                    title={`${item.status}: ${item.count}`}
                  />
                ))
              ) : (
                <div className="status-bar-segment status-bar-empty" />
              )}
            </div>
            {items.length > 0 && (
              <div className="status-bar-legend">
                {items.map((item, i) => (
                  <span key={item.status} className="status-legend-item">
                    <i
                      style={{
                        background: STATUS_PALETTE[i % STATUS_PALETTE.length],
                      }}
                    />
                    {item.status}
                    <b>{item.count}</b>
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ChannelDashboardView({
  data,
  mode,
  year,
  onMode,
  onYear,
  onOpenResource,
}: {
  data: ChannelDashboard;
  mode: "count" | "amount";
  year: number | null;
  onMode: (mode: "count" | "amount") => void;
  onYear: (year: number) => void;
  onOpenResource: (resource: string) => void;
}) {
  const metrics =
    data.source === "virtualpos"
      ? virtualPosMetrics
      : data.source === "toku"
        ? tokuMetrics
        : paykuMetrics;
  const chartData = data.activity
    .filter((entry) => year === null || entry.year === year)
    .map((entry) => ({ ...entry, label: months[entry.month - 1] }));
  const dataKey = mode;
  const activityTitle =
    data.source === "toku" ? "Actividad de deudas" : "Actividad de cobros";
  const metricSections =
    providerGroups.find((group) => group.sections[0].source === data.source)
      ?.sections ?? [];
  return (
    <main className="app-shell channel-dashboard-page">
      <p className="eyebrow">{title(data.source).toUpperCase()} / STAGING</p>
      <header className="channel-hero">
        <div>
          <h2>Resumen operativo</h2>
          <p>
            Datos locales sincronizados, pendientes de consolidación en
            BD_Central.
          </p>
        </div>
        <div className="channel-hero-controls">
          <div className="dashboard-controls">
            <div className="mode-switch">
              <button
                className={mode === "count" ? "active" : ""}
                onClick={() => onMode("count")}
              >
                Cantidad
              </button>
              <button
                className={mode === "amount" ? "active" : ""}
                onClick={() => onMode("amount")}
              >
                Monto
              </button>
            </div>
            {data.years.length ? (
              <select
                aria-label="Año"
                value={year ?? data.years[0]}
                onChange={(event) => onYear(Number(event.target.value))}
              >
                {data.years.map((entry) => (
                  <option key={entry} value={entry}>
                    {entry}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <div
            className={`sync-state ${data.last_sync?.status === "completed" ? "ready" : "attention"}`}
          >
            <span />
            {data.last_sync?.status ?? "Sin sincronización"}
          </div>
        </div>
      </header>
      <section
        className={`metrics provider-metrics ${data.source === "payku" ? "payku-metrics" : ""}`}
        aria-label={`Metricas ${title(data.source)}`}
      >
        {metrics.map((metric) => (
          <Metric
            key={metric.resource}
            label={metric.label}
            value={data.resources[metric.resource] ?? 0}
            tone={metric.tone}
            amount={
              "amount" in metric && metric.amount
                ? (data.resource_amounts[metric.resource] ?? 0)
                : undefined
            }
          />
        ))}
      </section>
      {data.kpis ? (
        <section className="metrics kpi-metrics" aria-label="KPIs técnicos">
          <KpiCard
            label="MRR"
            value={`$${data.kpis.mrr.toLocaleString("es-CL")}`}
            caption="Ingreso mensual recurrente activo"
            tone="green"
          />
          <KpiCard
            label="ARPU"
            value={`$${data.kpis.arpu.toLocaleString("es-CL")}`}
            caption={`${data.kpis.active_clients} cliente${data.kpis.active_clients !== 1 ? "s" : ""} con subs activas`}
            tone="blue"
          />
          <KpiCard
            label="Churn mensual"
            value={`${data.kpis.churn_rate}%`}
            caption={`${data.kpis.active_subscribers} subs activas · ${data.kpis.active_subscribers + (data.churn_monthly?.reduce((s, e) => s + e.count, 0) ?? 0)} total`}
            tone="orange"
          />
          <KpiCard
            label="LTV estimado"
            value={data.kpis.ltv > 0 ? `$${data.kpis.ltv.toLocaleString("es-CL")}` : "—"}
            caption="ARPU / churn rate"
            tone="violet"
          />
        </section>
      ) : null}
      <section className="channel-workspace">
        <article className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{activityTitle.toUpperCase()}</p>
              <h3>Serie mensual</h3>
            </div>
          </div>
          {chartData.length ? (
            <Suspense
              fallback={<p className="empty-chart">Cargando gráfico...</p>}
            >
              <ChannelActivityChart
                data={chartData}
                mode={dataKey}
                color={CHANNEL_COLORS[data.source]}
              />
            </Suspense>
          ) : (
            <p className="empty-chart">
              Sin fechas y montos suficientes para construir una serie mensual.
            </p>
          )}
        </article>
        <article className="panel status-panel">
          <p className="eyebrow">ESTADOS</p>
          <h3>Distribución disponible</h3>
          <StatusBars
            source={data.source}
            statuses={data.statuses}
            resources={data.resources}
          />
        </article>
      </section>
      {(data.charges_monthly?.length ||
        data.payments_monthly?.length ||
        data.invoices_monthly?.length ||
        (data.transactions_monthly as MonthlyEntry[] | undefined)?.length ||
        data.activation_monthly?.length ||
        data.churn_monthly?.length) ? (
        <section className="extended-charts">
          {data.charges_monthly?.length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">CARGOS</p>
                  <h3>Estado mensual</h3>
                </div>
              </div>
              <MonthlyStatusChart data={data.charges_monthly} mode={mode} year={year} />
            </article>
          ) : null}
          {data.payments_monthly?.length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">TRANSACCIONES</p>
                  <h3>Estado mensual</h3>
                </div>
              </div>
              <MonthlyStatusChart data={data.payments_monthly} mode={mode} year={year} />
            </article>
          ) : null}
          {data.invoices_monthly?.length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">FACTURAS</p>
                  <h3>Estado mensual</h3>
                </div>
              </div>
              <MonthlyStatusChart data={data.invoices_monthly} mode={mode} year={year} />
            </article>
          ) : null}
          {data.transactions_monthly && !("status" in (data.transactions_monthly[0] ?? {})) && (data.transactions_monthly as MonthlyEntry[]).length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">TRANSACCIONES</p>
                  <h3>Serie mensual</h3>
                </div>
              </div>
              <MonthlySimpleChart data={data.transactions_monthly as MonthlyEntry[]} color={CHANNEL_COLORS[data.source]} mode={mode} year={year} />
            </article>
          ) : data.transactions_monthly && "status" in ((data.transactions_monthly as MonthlyStatusEntry[])[0] ?? {}) && (data.transactions_monthly as MonthlyStatusEntry[]).length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">TRANSACCIONES</p>
                  <h3>Estado mensual</h3>
                </div>
              </div>
              <MonthlyStatusChart data={data.transactions_monthly as MonthlyStatusEntry[]} mode={mode} year={year} />
            </article>
          ) : null}
          {data.activation_monthly?.length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">SUSCRIPCIONES</p>
                  <h3>Activación mensual</h3>
                </div>
              </div>
              <MonthlySimpleChart data={data.activation_monthly} color="#3ba675" mode={mode} year={year} />
            </article>
          ) : null}
          {data.churn_monthly?.length ? (
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">SUSCRIPCIONES</p>
                  <h3>Caída mensual</h3>
                </div>
              </div>
              <MonthlySimpleChart data={data.churn_monthly} color="#a53d35" mode={mode} year={year} />
            </article>
          ) : null}
        </section>
      ) : null}
      <section className="panel channel-resources">
        <div>
          <p className="eyebrow">EXPLORAR STAGING</p>
          <h3>Recursos del canal</h3>
        </div>
        <div>
          {metricSections.map((section) => (
            <button
              key={section.resource}
              onClick={() => onOpenResource(section.resource)}
            >
              {section.label}
              <span>{data.resources[section.resource] ?? 0}</span>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

function App() {
  const [summary, setSummary] = useState<Summary>({ sources: [] });
  const [activeSection, setActiveSection] = useState<ProviderSection | null>(
    null,
  );
  const [channel, setChannel] = useState<string | null>(null);
  const [channelData, setChannelData] = useState<ChannelDashboard | null>(null);
  const [openProvider, setOpenProvider] = useState<string | null>("VirtualPOS");
  const [records, setRecords] = useState<StagingResponse>({
    items: [],
    total: 0,
  });
  const [loading, setLoading] = useState(true);
  const [channelLoading, setChannelLoading] = useState(false);
  const [clientDetail, setClientDetail] =
    useState<VirtualPosClientDetail | null>(null);
  const [planDetail, setPlanDetail] = useState<VirtualPosPlanDetail | null>(
    null,
  );
  const [subscriptionDetail, setSubscriptionDetail] =
    useState<VirtualPosSubscriptionDetail | null>(null);
  const [chargeDetail, setChargeDetail] = useState<VirtualPosChargeDetail | null>(null);
  const [paymentDetail, setPaymentDetail] = useState<VirtualPosPaymentDetail | null>(null);
  const [providerRecordDetail, setProviderRecordDetail] =
    useState<ProviderRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editingClient, setEditingClient] = useState<StagingRecord | null>(null);
  const [cancelingSubscription, setCancelingSubscription] = useState<StagingRecord | null>(null);
  const [filterField, setFilterField] = useState("");
  const [filterQuery, setFilterQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"count" | "amount">("count");
  const [year, setYear] = useState<number | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("crm-theme") as "light" | "dark") ?? "light";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("crm-theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => t === "light" ? "dark" : "light");

  useEffect(() => {
    let mounted = true;
    getJson<Summary>("/api/v1/staging/summary")
      .then((data) => {
        if (mounted) setSummary(data);
      })
      .catch(() => {
        if (mounted) setError("No se pudo cargar el resumen de staging local.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!activeSection) return;
    let mounted = true;
    const params = new URLSearchParams({
      source: activeSection.source,
      resource_type: activeSection.resource,
      limit: "100",
    });
    if (filterField && filterQuery.trim()) {
      params.set("filter_field", filterField);
      params.set("query", filterQuery.trim());
    }
    const path = `/api/v1/staging/records?${params}`;
    getJson<StagingResponse>(path)
      .then((data) => {
        if (mounted) setRecords(data);
      })
      .catch(() => {
        if (mounted)
          setError("No se pudieron cargar los registros de staging local.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [activeSection, filterField, filterQuery]);

  useEffect(() => {
    if (!channel) return;
    let mounted = true;
    getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${channel}`)
      .then((data) => {
        if (mounted) {
          setChannelData(data);
          setYear(data.years[0] ?? null);
        }
      })
      .catch(() => {
        if (mounted) setError("No se pudo cargar el mini dashboard del canal.");
      })
      .finally(() => {
        if (mounted) setChannelLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [channel]);

  function clearDetails() {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setProviderRecordDetail(null);
  }
  function showDashboard() {
    clearDetails();
    setActiveSection(null);
    setChannel(null);
    setError(null);
  }
  function showChannel(source: string) {
    clearDetails();
    setActiveSection(null);
    setChannelData(null);
    setChannelLoading(true);
    setError(null);
    setYear(null);
    setChannel(source);
    setOpenProvider(title(source));
  }
  function showSection(section: ProviderSection) {
    clearDetails();
    setChannel(null);
    setLoading(true);
    setError(null);
      setFilterField(stagingFilters[section.source]?.[section.resource]?.[0]?.value ?? "");
    setFilterQuery("");
    setActiveSection(section);
    setOpenProvider(title(section.source));
  }
  function openChannelResource(resource: string) {
    const section = providerGroups
      .flatMap((group) => group.sections)
      .find((entry) => entry.source === channel && entry.resource === resource);
    if (section) showSection(section);
  }
  async function openVirtualPosClient(record: StagingRecord) {
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setClientDetail(
        await getJson<VirtualPosClientDetail>(
          `/api/v1/staging/virtualpos/clients/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha del cliente.");
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPlan(record: Pick<StagingRecord, "external_id">) {
    setClientDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPlanDetail(
        await getJson<VirtualPosPlanDetail>(
          `/api/v1/staging/virtualpos/plans/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha del plan.");
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosSubscription(record: StagingRecord) {
    setClientDetail(null);
    setPlanDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setSubscriptionDetail(
        await getJson<VirtualPosSubscriptionDetail>(
          `/api/v1/staging/virtualpos/subscriptions/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha de la subscripción.");
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosCharge(record: StagingRecord) {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setChargeDetail(
        await getJson<VirtualPosChargeDetail>(
          `/api/v1/staging/virtualpos/charges/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha del cargo.");
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPayment(record: StagingRecord) {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPaymentDetail(
        await getJson<VirtualPosPaymentDetail>(
          `/api/v1/staging/virtualpos/payments/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha del pago.");
    } finally {
      setDetailLoading(false);
    }
  }
  async function openProviderRecord(
    source: string,
    resource: string,
    record: StagingRecord,
  ) {
    clearDetails();
    setDetailLoading(true);
    setError(null);
    try {
      setProviderRecordDetail(
        await getJson<ProviderRecordDetail>(
          `/api/v1/staging/${source}/${resource}/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch {
      setError("No se pudo cargar la ficha del registro.");
    } finally {
      setDetailLoading(false);
    }
  }

  const columns: TableColumn[] =
    activeSection?.source === "virtualpos"
      ? virtualPosColumns(activeSection.resource)
      : activeSection?.source === "toku"
        ? tokuColumns(activeSection.resource)
        : activeSection?.source === "payku"
          ? paykuColumns(activeSection.resource)
          : [];
  const clientDetailView = clientDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => setClientDetail(null)}>
        Volver a clientes VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / CLIENTE</p>
      <h2>
        {text(clientDetail.client.payload.first_name, "")}{" "}
        {text(clientDetail.client.payload.last_name, "")}
      </h2>
      <div className="client-detail-actions">
        <button className="edit-button" onClick={() => setEditingClient(clientDetail.client)}>
          Editar
        </button>
      </div>
      <section className="panel">
        <p className="eyebrow">FICHA DEL CLIENTE</p>
        <dl className="field-list">
          {virtualPosClientFields.map((field) => (
            <div key={field}>
              <dt>{virtualPosClientFieldLabels[field]}</dt>
              <dd>
                {field === "uuid"
                  ? text(
                      clientDetail.client.payload.uuid,
                      clientDetail.client.external_id,
                    )
                  : field === "social_id_type"
                    ? (virtualPosDocumentTypes[text(clientDetail.client.payload[field], "")] ?? text(clientDetail.client.payload[field]))
                  : text(clientDetail.client.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p>
            <h3>Relacionadas por RUT</h3>
          </div>
          <span>{clientDetail.subscription_total} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID Sub</th>
                <th>Status</th>
                <th>Monto</th>
                <th>F. Inicio</th>
              </tr>
            </thead>
            <tbody>
              {clientDetail.subscriptions.map((subscription) => (
                <tr key={subscription.id}>
                  <td>
                    <button className="record-link" onClick={() => void openVirtualPosSubscription(subscription)}>
                      {text(subscription.payload.id, subscription.external_id)}
                    </button>
                  </td>
                  <td>{text(subscription.payload.status)}</td>
                  <td>{text(subscription.payload.amount)}</td>
                  <td>{text(subscription.payload.suscription_date)}</td>
                </tr>
              ))}
              {clientDetail.subscriptions.length === 0 ? (
                <tr>
                  <td colSpan={4}>Sin suscripciones asociadas por RUT.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  ) : null;
  const planDetailView = planDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => setPlanDetail(null)}>
        Volver a planes VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / PLAN</p>
      <h2>{text(planDetail.plan.payload.name, planDetail.plan.external_id)}</h2>
      <section className="panel">
        <p className="eyebrow">FICHA DEL PLAN</p>
        <dl className="field-list">
          {virtualPosPlanFields.map((field) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>
                {field === "id"
                  ? text(
                      planDetail.plan.payload.id,
                      planDetail.plan.external_id,
                    )
                  : (field === "return_url" || field === "suscription_url") && externalUrl(planDetail.plan.payload[field])
                    ? <a className="record-link" href={externalUrl(planDetail.plan.payload[field]) ?? undefined} target="_blank" rel="noreferrer">Abrir enlace</a>
                    : text(planDetail.plan.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p>
            <h3>Asociadas al plan</h3>
          </div>
          <span>{planDetail.subscription_total} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID Sub</th>
                <th>Nombre cliente</th>
                <th>Monto</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {planDetail.subscriptions.map((subscription) => (
                <tr key={subscription.id}>
                  <td>
                    <button
                      className="record-link"
                      onClick={() =>
                        void openVirtualPosSubscription(subscription)
                      }
                    >
                      {text(subscription.payload.id, subscription.external_id)}
                    </button>
                  </td>
                  <td>{virtualPosClientName(subscription)}</td>
                  <td>{text(subscription.payload.amount)}</td>
                  <td>{text(subscription.payload.status)}</td>
                </tr>
              ))}
              {planDetail.subscriptions.length === 0 ? (
                <tr>
                  <td colSpan={4}>Sin suscripciones asociadas al plan.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  ) : null;
  const subscriptionDetailView = subscriptionDetail ? (
    <main className="app-shell detail-page">
      <button
        className="back-button"
        onClick={() => setSubscriptionDetail(null)}
      >
        Volver al listado VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / SUBSCRIPCIÓN</p>
      <h2>
        {text(
          subscriptionDetail.subscription.payload.plan_name,
          subscriptionDetail.subscription.external_id,
        )}
      </h2>
      {isActiveSubscription(subscriptionDetail.subscription) ? (
        <div className="client-detail-actions">
          <button
            className="cancel-subscription-button"
            onClick={() => setCancelingSubscription(subscriptionDetail.subscription)}
          >
            Cancelar Sub
          </button>
        </div>
      ) : null}
      <section className="panel">
        <p className="eyebrow">FICHA DE LA SUBSCRIPCIÓN</p>
        <dl className="field-list">
          {virtualPosSubscriptionFields.map((field) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>
                {field === "id"
                  ? text(
                      subscriptionDetail.subscription.payload.id,
                      subscriptionDetail.subscription.external_id,
                    )
                  : field === "plan_name" && subscriptionDetail.subscription.payload.plan_id
                    ? <button className="record-link" onClick={() => void openVirtualPosPlan({ external_id: String(subscriptionDetail.subscription.payload.plan_id) })}>{text(subscriptionDetail.subscription.payload[field])}</button>
                    : field === "renewal"
                      ? renewalText(subscriptionDetail.subscription.payload[field])
                      : text(subscriptionDetail.subscription.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <p className="eyebrow">MÉTODO DE PAGO</p>
        {objectEntries(subscriptionDetail.payment_method).length ? (
          <dl className="field-list">
            {objectEntries(subscriptionDetail.payment_method).filter(([field]) => !["bin", "last4carddigit", "last4"].includes(field.toLowerCase())).map(
              ([field, value]) => (
                <div key={field}>
                  <dt>{fieldLabel(field)}</dt>
                  <dd>{field === "card_type" ? cardTypeText(value) : text(value)}</dd>
                </div>
              ),
            )}
          </dl>
        ) : (
          <p>Sin método de pago disponible en staging.</p>
        )}
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CARGOS</p>
            <h3>Asociados a la subscripción</h3>
          </div>
          <span>{subscriptionDetail.charge_total} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha de cargo</th>
                <th>ID Cargo</th>
                <th>Estado</th>
                <th>Monto</th>
              </tr>
            </thead>
            <tbody>
              {subscriptionDetail.charges.map((charge) => (
                <tr key={charge.id}>
                  <td>{text(charge.payload.charge_date)}</td>
                  <td>
                    <button className="record-link" onClick={() => void openVirtualPosCharge(charge)}>
                      {text(charge.payload.id, charge.external_id)}
                    </button>
                  </td>
                  <td>{text(charge.payload.status)}</td>
                  <td>{text(charge.payload.amount)}</td>
                </tr>
              ))}
              {subscriptionDetail.charges.length === 0 ? (
                <tr>
                  <td colSpan={4}>Sin cargos asociados a la subscripción.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  ) : null;
  const chargeDetailView = chargeDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => setChargeDetail(null)}>
        Volver a cargos VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / CARGO</p>
      <h2>{text(chargeDetail.charge.payload.id, chargeDetail.charge.external_id)}</h2>
      <section className="panel">
        <p className="eyebrow">FICHA DEL CARGO</p>
        <dl className="field-list">
          {Object.entries(chargeDetail.charge.payload).map(([field, value]) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>{text(value)}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  ) : null;
  const paymentDetailView = paymentDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => setPaymentDetail(null)}>
        Volver a transacciones VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / TRANSACCIÓN</p>
      <h2>{text(nested(paymentDetail.payment.payload, "order", "uuid"), paymentDetail.payment.external_id)}</h2>
      <section className="panel">
        <p className="eyebrow">FICHA DE LA TRANSACCIÓN</p>
        <dl className="field-list">
          {Object.entries(paymentDetail.payment.payload).flatMap(([field, value]) => {
            if ((field === "order" || field === "client") && objectEntries(value).length) {
              return objectEntries(value).map(([nestedField, nestedValue]) => (
                <div key={`${field}-${nestedField}`}>
                  <dt>{fieldLabel(field)} {fieldLabel(nestedField)}</dt>
                  <dd>{text(nestedValue)}</dd>
                </div>
              ));
            }
            return [
              <div key={field}>
                <dt>{fieldLabel(field)}</dt>
                <dd>{text(value)}</dd>
              </div>,
            ];
          })}
        </dl>
      </section>
    </main>
  ) : null;
  const providerRecordDetailView = providerRecordDetail ? (
    <main className="app-shell detail-page">
      <button
        className="back-button"
        onClick={() => setProviderRecordDetail(null)}
      >
        Volver al listado {title(providerRecordDetail.record.source)}
      </button>
      <p className="eyebrow">
        {title(providerRecordDetail.record.source).toUpperCase()} /{" "}
        {resourceTitle(providerRecordDetail.record.resource_type).toUpperCase()}
      </p>
      <h2>{providerRecordHeading(providerRecordDetail.record)}</h2>
      <section className="panel">
        <p className="eyebrow">FICHA COMPLETA</p>
        <dl className="field-list">
          {Object.entries(providerRecordDetail.record.payload).flatMap(
            ([field, value]) => {
              if (field === "recurring" && objectEntries(value).length) {
                return objectEntries(value).map(([subField, subValue]) => (
                  <div key={`recurring-${subField}`}>
                    <dt>
                      Recurrencia{" "}
                      {recurringFieldLabels[subField] ?? fieldLabel(subField)}
                    </dt>
                    <dd>{text(subValue)}</dd>
                  </div>
                ));
              }
              return [
                <div key={field}>
                  <dt>{fieldLabel(field)}</dt>
                  <dd>{text(value)}</dd>
                </div>,
              ];
            },
          )}
        </dl>
      </section>
      {providerRecordDetail.related.map((group) => (
        <section
          className="panel client-subscriptions"
          key={group.resource_type}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{group.label.toUpperCase()}</p>
              <h3>Registros relacionados</h3>
            </div>
            <span>{group.items.length} total</span>
          </div>
          {group.items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Nombre</th>
                    <th>Estado</th>
                    <th>Monto</th>
                  </tr>
                </thead>
                <tbody>
                  {group.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <button
                          className="record-link"
                          onClick={() =>
                            void openProviderRecord(
                              item.source,
                              group.resource_type,
                              item,
                            )
                          }
                        >
                          {text(item.payload.id, item.external_id)}
                        </button>
                      </td>
                      <td>
                        {text(
                          item.payload.name,
                          text(nested(item.payload, "client", "name")),
                        )}
                      </td>
                      <td>{text(item.payload.status)}</td>
                      <td>{text(item.payload.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>Sin registros relacionados.</p>
          )}
        </section>
      ))}
    </main>
  ) : null;
  const filterOptions = activeSection
    ? (stagingFilters[activeSection.source]?.[activeSection.resource] ?? [])
    : [];
  const filterControls = filterOptions.length ? (
    <section
      className="record-filters"
      aria-label={`Filtros ${activeSection?.label}`}
    >
      <label>
        Filtrar por
        <select
          value={filterField}
          onChange={(event) => setFilterField(event.target.value)}
        >
          {filterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Buscar
        <input
          value={filterQuery}
          onChange={(event) => setFilterQuery(event.target.value)}
          placeholder={`Buscar por ${filterOptions.find((option) => option.value === filterField)?.label ?? "campo"}`}
        />
      </label>
      {filterQuery ? (
        <button onClick={() => setFilterQuery("")}>Limpiar</button>
      ) : null}
    </section>
  ) : null;
  const providerDetail = activeSection ? (
    <main className="app-shell detail-page provider-page">
      <button
        className="back-button"
        onClick={() => showChannel(activeSection.source)}
      >
        Volver al resumen {title(activeSection.source)}
      </button>
      <p className="eyebrow">
        {title(activeSection.source).toUpperCase()} / STAGING
      </p>
      <h2>{activeSection.label}</h2>
      {filterControls}
      <section className="panel provider-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SOURCE RECORDS</p>
            <h3>Payloads saneados almacenados localmente</h3>
          </div>
          <span>{loading ? "Cargando" : `${records.total} registros`}</span>
        </div>
        {error ? <p className="error-message">{error}</p> : null}
        {!loading && !error && records.items.length === 0 ? (
          <p>Sin registros sincronizados para este recurso.</p>
        ) : null}
        {records.items.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column.label}>{column.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.items.map((record) => (
                  <tr key={record.id}>
                    {columns.map((column) => (
                      <td key={column.label}>
                        {activeSection.source === "virtualpos" &&
                        activeSection.resource === "subscription" &&
                        column.label === "Acciones" ? (
                          isActiveSubscription(record) ? (
                            <button
                              className="cancel-subscription-button cancel-subscription-button-table"
                              onClick={() => setCancelingSubscription(record)}
                            >
                              Cancelar Sub
                            </button>
                          ) : (
                            "-"
                          )
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "charge" &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cargo ${column.value(record)}`}
                            onClick={() => void openVirtualPosCharge(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "payment" &&
                          column.label === "UUID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de transacción ${column.value(record)}`}
                            onClick={() => void openVirtualPosPayment(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "Acciones" ? (
                          <button
                            className="edit-button edit-button-table"
                            onClick={() => setEditingClient(record)}
                          >
                            Editar
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "UUID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cliente ${column.value(record)}`}
                            onClick={() => void openVirtualPosClient(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "plan" &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de plan ${column.value(record)}`}
                            onClick={() => void openVirtualPosPlan(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "subscription" &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de subscripción ${column.value(record)}`}
                            onClick={() =>
                              void openVirtualPosSubscription(record)
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : (activeSection.source === "toku" ||
                            activeSection.source === "payku") &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord(
                                activeSection.source,
                                activeSection.resource,
                                record,
                              )
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : (
                          column.value(record)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </main>
  ) : null;
  const globalDashboard = (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CRM</span>
          <div>
            <p className="eyebrow">OPERACIONES RECURRENTES</p>
            <h1>CRM Suscripciones</h1>
          </div>
        </div>
        <div className="sync-state ready">
          <span />
          Staging local
        </div>
      </header>
      <section className="hero-panel">
        <div>
          <p className="eyebrow">RESUMEN OPERATIVO</p>
          <h2>
            Datos por canal,
            <br />
            antes de la BD Central.
          </h2>
        </div>
        <p className="sync-copy">
          Selecciona VirtualPOS, Toku o Payku para abrir su mini dashboard
          operativo.
        </p>
      </section>
      {error ? <p className="error-message">{error}</p> : null}
      <section className="metrics" aria-label="Resumen de staging">
        {summary.sources.map((source, index) => (
          <Metric
            key={source.source}
            label={title(source.source)}
            value={source.records}
            tone={["blue", "violet", "gold"][index]}
          />
        ))}
      </section>
      <section className="source-summary">
        {summary.sources.map((source) => (
          <article className="panel" key={source.source}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{title(source.source).toUpperCase()}</p>
                <h3>{source.records} registros staging</h3>
              </div>
              <span
                className={`status-pill ${source.last_sync?.status === "completed" ? "" : "status-attention"}`}
              >
                {source.last_sync?.status ?? "Sin sync"}
              </span>
            </div>
            <p className="resource-copy">
              {Object.entries(source.resources)
                .map(([resource, count]) => `${resource}: ${count}`)
                .join(" · ") || "Sin recursos sincronizados."}
            </p>
          </article>
        ))}
      </section>
    </main>
  );
  const clientEditDialog = editingClient ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form className="edit-dialog" aria-modal="true" aria-label="Editar cliente VirtualPOS">
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / EDICIÓN</p>
            <h3>Editar cliente</h3>
          </div>
          <span>{text(editingClient.payload.uuid, editingClient.external_id)}</span>
        </div>
        <p className="edit-dialog-note">
          Formulario visual. El guardado remoto permanece deshabilitado mientras VirtualPOS opere en modo solo lectura.
        </p>
        <div className="edit-form-grid">
          {virtualPosClientEditFields.map((field) => (
            <label key={field.name}>
              {field.label}
              <input
                name={field.name}
                type={field.type ?? "text"}
                defaultValue={text(editingClient.payload[field.name], "")}
              />
            </label>
          ))}
          <label className="edit-form-wide">
            Nota privada
            <textarea name="private_note" defaultValue={text(editingClient.payload.private_note, "")} />
          </label>
        </div>
        <div className="edit-dialog-actions">
          <button type="button" className="save-button" disabled title="Guardado remoto no habilitado">
            Guardar cambios
          </button>
          <button type="button" className="cancel-button" onClick={() => setEditingClient(null)}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null;
  const subscriptionCancelDialog = cancelingSubscription ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar subscripción VirtualPOS">
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / CANCELACIÓN</p>
            <h3>Cancelar subscripción</h3>
          </div>
          <span>{text(cancelingSubscription.payload.id, cancelingSubscription.external_id)}</span>
        </div>
        <p className="edit-dialog-note">
          Esta acción utilizará DELETE `/v3/suscription/{text(cancelingSubscription.payload.id, cancelingSubscription.external_id)}` cuando se habilite la escritura. Actualmente VirtualPOS permanece en modo solo lectura.
        </p>
        <div className="edit-dialog-actions">
          <button type="button" className="cancel-subscription-button" disabled title="Cancelación remota no habilitada">
            Confirmar cancelación
          </button>
          <button type="button" className="cancel-button" onClick={() => setCancelingSubscription(null)}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null;
  const content = detailLoading ? (
    <main className="app-shell">
      <p className="muted-copy">Cargando ficha...</p>
    </main>
  ) : (
    (clientDetailView ??
    planDetailView ??
    subscriptionDetailView ??
    chargeDetailView ??
    paymentDetailView ??
    providerRecordDetailView ??
    providerDetail ??
    (channel ? (
      channelLoading || !channelData ? (
        <main className="app-shell">
          <p className="muted-copy">Cargando mini dashboard...</p>
        </main>
      ) : (
        <ChannelDashboardView
          data={channelData}
          mode={mode}
          year={year}
          onMode={setMode}
          onYear={setYear}
          onOpenResource={openChannelResource}
        />
      )
    ) : (
      globalDashboard
    )))
  );

  return (
    <div className="app-layout">
      <Sidebar
        activeSection={activeSection}
        channel={channel}
        openProvider={openProvider}
        theme={theme}
        onDashboard={showDashboard}
        onChannel={showChannel}
        onSection={showSection}
        onToggle={(provider) =>
          setOpenProvider((open) => (open === provider ? null : provider))
        }
        onTheme={toggleTheme}
      />
      {content}
      {clientEditDialog}
      {subscriptionCancelDialog}
    </div>
  );
}

export default App;
