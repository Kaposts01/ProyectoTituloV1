import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import "./App.css";
import "./Staging.css";
import { MonthlySimpleChart, MonthlyStatusChart } from "./MonthlyStatusChart";
import type { MonthlyEntry, MonthlyStatusEntry } from "./MonthlyStatusChart";
import { CHART_PRIMARY, chartStatusColor } from "./chartColors";

const ChannelActivityChart = lazy(() => import("./ChannelActivityChart"));

type SyncRun = { status: string; records_processed: number; started_at?: string | null; finished_at?: string | null };
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
type StagingResponse = { items: StagingRecord[]; total: number; offset: number; limit: number };
type ProviderSection = { source: string; resource: string; label: string };
type TableColumn = { label: string; value: (record: StagingRecord) => string };
type Activity = { year: number; month: number; count: number; amount: number };
type RejectedCharge = {
  id: string; external_id: string; source: string;
  subscription_external_id: string | null; client_external_id: string | null;
  amount: string | null; currency: string | null;
  charge_date: string | null;
  rejection_code: string | null; rejection_reason: string | null; rejection_doc_url: string | null;
};
type RejectedChargesResp = { items: RejectedCharge[]; total: number; offset: number; limit: number };
type BatchRetryResult = { charge_id: string; success: boolean; status: string | null; error: string | null };
type BatchRetryResp = { results: BatchRetryResult[]; succeeded: number; failed: number };
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
  activation_monthly?: MonthlyStatusEntry[];
  churn_monthly?: MonthlyEntry[] | MonthlyStatusEntry[];
};
type VirtualPosClientDetail = {
  client: StagingRecord;
  subscriptions: StagingRecord[];
  subscription_total: number;
  charges: StagingRecord[];
  charge_total: number;
  payments: StagingRecord[];
  payment_total: number;
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
type SortDirection = "asc" | "desc";
type EtlRun = {
  id: string;
  status: string;
  phase: string | null;
  started_at: string | null;
  finished_at: string | null;
  records_upserted: number;
  channels_processed: string[] | null;
  error_message: string | null;
};
type ClientEditField = { name: string; label: string; type?: string; options?: { value: string; label: string }[] };
type AuthUser = { id: string; username: string; is_active: boolean; roles: { id: string; name: string }[]; permissions: string[] };
type AuthSession = { user: AuthUser; csrf_token: string };
type AdminRole = { id: string; name: string; description: string | null; permission_codes: string[] };
type TchSummary = {
  suscripciones: { vigentes: number; eliminadas: number; total: number; monto_vigentes: number; monto_eliminadas: number; monto_total: number };
  transacciones: { total: number; aceptadas: number; rechazadas: number; tasa_rechazo_pct: number; monto: number };
  kpis: { mrr: number; arpu: number; active_clients: number; active_subscribers: number; churn_rate: number; ltv: number };
  years: number[];
  transacciones_mensuales: MonthlyStatusEntry[];
  activaciones_mensuales: MonthlyStatusEntry[];
  bajas_mensuales: MonthlyStatusEntry[];
  ultimo_etl: { id: string | null; status: string | null; started_at: string | null; records_upserted: number | null };
};
type GeneralDashboard = {
  clients: number;
  subscriptions: { active: number; amount: number };
  transactions: { total: number; accepted: number; rejected: number; amount: number; rejection_rate_pct: number };
  channels: { source: string; clients: number; active_subscriptions: number; accepted: number; amount: number }[];
  years: number[];
  transactions_monthly: MonthlyStatusEntry[];
  activations_monthly: MonthlyStatusEntry[];
  cancellations_monthly: MonthlyStatusEntry[];
  debts_monthly: (MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" })[];
  transactions_effective_monthly: (MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" })[];
};
type GeneralClient = { rut: string; name: string; origins: string[]; active_origins: string[] };
type GeneralClients = { items: GeneralClient[]; total: number; offset: number; limit: number };
type GeneralSubscription = { id: string; platform: string; rut: string; client: string; status: string; started_at: string | null; ended_at: string | null; amount: string | null; currency: string | null };
type GeneralSubscriptions = { items: GeneralSubscription[]; total: number; offset: number; limit: number };
type GeneralClientDetail = {
  rut: string;
  clients: { portal: string; id_cliente: string; external_id: string }[];
  subscriptions: { portal: string; id_subscription: string; external_id: string; status: string }[];
  charges: { portal: string; id_cargo: string; external_id: string; status: string; amount: string | null }[];
  transactions: { portal: string; id_transaccion: string; external_id: string; status: string; amount: string | null }[];
};
type TchSuscripcion = {
  id: string; numero_ficha: number; numero_mandato: number | null;
  cliente_rut: string | null; banco_nombre: string | null; tipo_mandato: string | null;
  tipo_cuenta: string | null; origen: string | null; centro_costo: string | null;
  captador: string | null; monto: string | null; fecha_activacion: string | null;
  equivalente_pesos: string | null;
  fecha_rechazo: string | null; fecha_eliminacion: string | null; fecha_fin: string | null;
  razon_baja: string | null; estado: string;
  created_at: string | null; updated_at: string | null;
};
type TchSuscripcionesResp = { total: number; page: number; limit: number; pages: number; items: TchSuscripcion[] };
type TchTransaccion = {
  id: string; numero_ficha: number; periodo: string | null; numero_cuota: string | null;
  total_cuotas: string | null; monto: string | null; fecha_cargo: string | null;
  tipo_transaccion: string | null; estado: string; entidad_recaudadora: string | null;
  razon_rechazo: string | null; archivo_origen: string | null;
};
type TchTransaccionesResp = { total: number; page: number; limit: number; pages: number; items: TchTransaccion[] };
type TchSuscripcionDetail = TchSuscripcion & { transacciones: TchTransaccion[] };
type TchTransaccionDetail = TchTransaccion & { suscripcion: TchSuscripcion | null };
type TchCliente = { id: string; rut: string; nombre: string | null; apellido: string | null; fecha_nacimiento: string | null; profesion: string | null; tipo_persona: string | null; tipo_socio: string | null; telefono: string | null; email: string | null; direccion: string | null; comuna: string | null; ciudad: string | null };
type TchClientesResp = { total: number; page: number; limit: number; pages: number; items: TchCliente[] };
type TchClienteDetail = TchCliente & { suscripciones: TchSuscripcion[] };

let csrfToken = "";

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
  { resource: "subscription", label: "Subscripciones", tone: "violet", amount: true },
  { resource: "payment_method", label: "Metodos de pago", tone: "gold" },
  { resource: "invoice", label: "Deudas", tone: "orange", amount: true },
  { resource: "transaction", label: "Transacciones", tone: "green", amount: true },
];
const paykuMetrics = [
  { resource: "client", label: "Clientes", tone: "blue" },
  { resource: "plan", label: "Planes", tone: "violet" },
  { resource: "subscription", label: "Suscripciones", tone: "gold", amount: true },
  { resource: "transaction", label: "Transacciones", tone: "green", amount: true },
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
// Los canales traen datos hasta anios futuros (p. ej. 2031 en VirtualPOS). El filtro debe
// abrir en el anio en curso; si no hay datos de ese anio, cae al anio disponible mas cercano.
function defaultYear(years: number[]): number | null {
  if (!years.length) return null;
  const current = new Date().getFullYear();
  if (years.includes(current)) return current;
  const past = years.filter((entry) => entry < current);
  return past.length ? Math.max(...past) : Math.min(...years);
}

const METRIC_COLORS: Record<string, string> = {
  blue: "#4a90c4",
  violet: "#7b6cc7",
  gold: "#c49d30",
  orange: "#d46a2a",
  green: "#3ba675",
};
const CHANNEL_COLORS: Record<string, string> = {
  virtualpos: CHART_PRIMARY,
  toku: CHART_PRIMARY,
  payku: CHART_PRIMARY,
};
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
  "private_note",
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
  private_note: "Nota privada",
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
  service_id: "ID servicio",
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
  "service_id",
  "plan_name",
  "suscription_date",
  "canceled_at",
  "currency",
  "amount",
  "renewal",
  "channel",
];
const virtualPosClientEditFields: ClientEditField[] = [
  {
    name: "status",
    label: "Estado",
    options: [
      { value: "ACTIVO", label: "Activo" },
      { value: "BLOQUEADO", label: "Bloqueado" },
    ],
  },
  {
    name: "type",
    label: "Tipo",
    options: [
      { value: "PERSONA", label: "Persona" },
      { value: "EMPRESA", label: "Empresa" },
    ],
  },
  { name: "first_name", label: "Nombre" },
  { name: "last_name", label: "Apellido" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone_number", label: "Teléfono", type: "tel" },
  {
    name: "social_id_type",
    label: "Tipo de documento",
    options: [
      { value: "1", label: "RUT" },
      { value: "2", label: "DNI" },
    ],
  },
  { name: "social_id", label: "RUT / documento" },
  { name: "birth_date", label: "Fecha de nacimiento", type: "date" },
  {
    name: "gender_id",
    label: "Género",
    options: [
      { value: "", label: "Sin especificar" },
      { value: "Masculino", label: "Masculino" },
      { value: "Femenino", label: "Femenino" },
    ],
  },
];
type PlanCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
const virtualPosPlanCreateFields: PlanCreateField[] = [
  { name: "name", label: "Nombre del plan", required: true },
  { name: "amount", label: "Monto", type: "number", required: true },
  {
    name: "currency",
    label: "Moneda",
    required: true,
    options: [
      { value: "CLP", label: "CLP — Peso chileno" },
      { value: "UF", label: "UF — Unidad de fomento" },
    ],
  },
  {
    name: "frequency_type",
    label: "Frecuencia de cobro",
    required: true,
    options: [
      { value: "monthly", label: "Mensual" },
      { value: "weekly", label: "Semanal" },
      { value: "bimonthly", label: "Bimestral" },
      { value: "quarterly", label: "Trimestral" },
      { value: "biannual", label: "Semestral" },
      { value: "annual", label: "Anual" },
      { value: "daily", label: "Diario" },
    ],
  },
  { name: "description", label: "Descripción" },
  { name: "trial_days", label: "Días de prueba", type: "number" },
  { name: "num_charges", label: "N° de cobros (0 = ilimitado)", type: "number" },
  { name: "activation_amount", label: "Monto de activación", type: "number" },
  { name: "fixed_amount_day_charge", label: "Día de cobro del mes (1-28)", type: "number" },
  {
    name: "automatic_renewal",
    label: "Renovación automática",
    options: [
      { value: "true", label: "Sí" },
      { value: "false", label: "No" },
    ],
  },
  {
    name: "show_in_terminal",
    label: "Visible en terminal",
    options: [
      { value: "false", label: "No" },
      { value: "true", label: "Sí" },
    ],
  },
  {
    name: "is_active",
    label: "Activo",
    options: [
      { value: "true", label: "Sí" },
      { value: "false", label: "No" },
    ],
  },
  { name: "return_url", label: "URL de retorno", type: "url" },
  { name: "suscription_url", label: "URL de suscripción", type: "url" },
  { name: "type", label: "Tipo de plan" },
];
const planDefaultValues: Record<string, string> = { currency: "CLP", frequency_type: "monthly", automatic_renewal: "true", show_in_terminal: "false", is_active: "true" };

type SubscriptionCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
const virtualPosSubscriptionCreateFields: SubscriptionCreateField[] = [
  { name: "plan_id", label: "ID del plan", required: true },
  { name: "email", label: "Email del cliente", type: "email", required: true },
  { name: "first_name", label: "Nombre", required: true },
  { name: "last_name", label: "Apellido", required: true },
  { name: "social_id", label: "RUT", required: true },
  { name: "phone_number", label: "Teléfono", type: "tel" },
  { name: "service_id", label: "ID de servicio (interno)" },
  {
    name: "channel",
    label: "Canal",
    options: [
      { value: "WEB", label: "WEB" },
      { value: "CALL_CENTER", label: "Call center" },
      { value: "PRESENCIAL", label: "Presencial" },
    ],
  },
  {
    name: "automatic_renewal",
    label: "Renovación automática",
    options: [
      { value: "T", label: "Sí" },
      { value: "F", label: "No" },
    ],
  },
  { name: "return_url", label: "URL de retorno", type: "url" },
  { name: "callback_url", label: "URL de callback", type: "url" },
];
const subscriptionRequiredFields = new Set(["plan_id", "email", "first_name", "last_name", "social_id"]);

const providerEditFields: Record<string, Record<string, ClientEditField[]>> = {
  toku: {
    customer: [
      { name: "name", label: "Nombre" },
      { name: "mail", label: "Correo electrónico", type: "email" },
    ],
    invoice: [
      { name: "amount", label: "Monto", type: "number" },
      { name: "due_date", label: "Fecha límite", type: "date" },
    ],
    subscription: [{ name: "amount", label: "Monto", type: "number" }],
  },
  payku: {
    client: [
      { name: "name", label: "Nombre" },
      { name: "email", label: "Correo electrónico", type: "email" },
      { name: "phone", label: "Teléfono", type: "tel" },
      { name: "address", label: "Dirección" },
      { name: "country", label: "País" },
      { name: "region", label: "Región" },
      { name: "city", label: "Ciudad" },
      { name: "postal_code", label: "Código postal" },
    ],
  },
};
const deletableResources: Record<string, string[]> = {
  virtualpos: ["payment"],
  toku: ["customer", "invoice", "subscription", "payment_method"],
  payku: ["client", "subscription"],
};
function deleteEndpoint(
  source: string,
  resourceType: string,
  record: StagingRecord,
): string {
  const id = text(record.payload.id, record.external_id);
  if (source === "virtualpos" && resourceType === "charge")
    return `/v3/charge/${id}`;
  if (source === "virtualpos" && resourceType === "payment")
    return `/v3/payment/${text(nested(record.payload, "order", "uuid") ?? record.payload.uuid, id)}`;
  if (source === "toku" && resourceType === "customer") return `/customers/${id}`;
  if (source === "toku" && resourceType === "invoice") return `/invoices/${id}`;
  if (source === "toku" && resourceType === "subscription")
    return `/subscriptions/${id}`;
  if (source === "toku" && resourceType === "payment_method")
    return `/payment-methods?id_payment_method=${id}`;
  if (source === "payku" && resourceType === "client") return `/api/suclient/${id}`;
  if (source === "payku" && resourceType === "subscription")
    return `/api/sususcription/${id}`;
  return `/${resourceType}/${id}`;
}
const stagingFilters: Record<string, Record<string, FilterOption[]>> = {
  virtualpos: {
    client: [{ value: "uuid", label: "UUID" }, { value: "social_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "email", label: "Email" }, { value: "phone_number", label: "Teléfono" }, { value: "status", label: "Estado" }],
    plan: [{ value: "id", label: "ID" }, { value: "name", label: "Nombre" }, { value: "amount", label: "Monto" }, { value: "automatic_renewal", label: "Renovación" }, { value: "is_active", label: "Estado" }, { value: "show_in_terminal", label: "Activo en POS" }],
    subscription: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "suscription_date", label: "F. Inicio" }, { value: "canceled_at", label: "F. Cancelación" }],
    charge: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "subscription_id", label: "ID subscripción" }, { value: "amount", label: "Monto" }, { value: "charge_date", label: "Fecha de cargo" }],
    payment: [{ value: "uuid", label: "UUID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "authorized_at", label: "F. Pago" }],
  },
  toku: {
    customer: [{ value: "id", label: "ID" }, { value: "government_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "mail", label: "Mail" }, { value: "phone_number", label: "Teléfono" }],
    subscription: [{ value: "id", label: "ID" }, { value: "customer", label: "ID cliente" }, { value: "amount", label: "Monto" }, { value: "status", label: "Estado" }, { value: "anchor", label: "F. Inicio" }, { value: "end_date", label: "F. Cancelación" }],
    payment_method: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "customer_id", label: "Cliente" }, { value: "card_brand", label: "Marca" }, { value: "last_digits", label: "Terminación" }, { value: "bank_name", label: "Banco" }, { value: "card_type", label: "Tipo tarjeta" }, { value: "created_at", label: "F. Creación" }],
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
const RECORDS_PAGE_SIZE = 100;

function filterFieldForColumn(source: string, resource: string, label: string): string | null {
  const normalize = (value: string) => value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]/gi, "")
    .toLowerCase();
  return stagingFilters[source]?.[resource]?.find(
    (option) => normalize(option.label) === normalize(label),
  )?.value ?? null;
}

function extractErrorDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail = (data as Record<string, unknown>).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item !== "object" || item === null) return String(item);
        const err = item as Record<string, unknown>;
        const loc = Array.isArray(err.loc)
          ? (err.loc as string[]).filter((l) => l !== "body").join(" → ")
          : "";
        const msg = typeof err.msg === "string" ? err.msg : "";
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean)
      .join("; ");
  }
  return null;
}

function httpErrorMessage(status: number, detail: string | null): string {
  if (detail) return detail;
  if (status === 400) return "Solicitud inválida. Verifica los datos ingresados.";
  if (status === 401) return "Sesión expirada. Vuelve a iniciar sesión.";
  if (status === 403) return "No tienes permiso para realizar esta acción.";
  if (status === 404) return "El recurso solicitado no fue encontrado.";
  if (status === 422) return "Los datos enviados no son válidos. Revisa los campos e inténtalo de nuevo.";
  if (status === 500) return "Error interno del servidor. Inténtalo de nuevo en unos momentos.";
  if (status === 503) return "El servicio no está disponible temporalmente. Inténtalo más tarde.";
  return `Error inesperado del servidor (${status}).`;
}

function friendlyError(error: unknown, fallback = "Ocurrió un error inesperado."): string {
  if (error instanceof TypeError && error.message.toLowerCase().includes("fetch")) {
    return "No se pudo conectar con el servidor. Verifica tu conexión.";
  }
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

async function checkResponse(response: Response): Promise<void> {
  if (response.ok) return;
  const data = await response.json().catch(() => null);
  const detail = extractErrorDetail(data);
  throw new Error(httpErrorMessage(response.status, detail));
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "include" });
  await checkResponse(response);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  await checkResponse(response);
  return response.json() as Promise<T>;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
    body: JSON.stringify(body),
  });
  await checkResponse(response);
  return response.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    credentials: "include",
    headers: { ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
  });
  await checkResponse(response);
  return response.json() as Promise<T>;
}

async function refreshCsrfToken(): Promise<void> {
  const session = await getJson<AuthSession>("/api/v1/auth/me");
  csrfToken = session.csrf_token;
}

function text(value: unknown, fallback = "Sin dato"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function documentType(value: unknown): string {
  const normalized = String(value ?? "").toUpperCase();
  return normalized === "RUT" ? "1" : normalized === "DNI" ? "2" : normalized;
}

function normalizeRut(value: string): string | null {
  const compact = value.toUpperCase().replace(/[.\-\s]/g, "");
  if (!/^[0-9]+[0-9K]$/.test(compact)) return null;
  const body = compact.slice(0, -1).replace(/^0+/, "") || "0";
  const checkDigit = compact.at(-1)!;
  const total = [...body].reverse().reduce((sum, digit, index) => sum + Number(digit) * (2 + index % 6), 0);
  const remainder = total % 11;
  const expected = remainder === 0 ? "0" : remainder === 1 ? "K" : String(11 - remainder);
  return checkDigit === expected ? `${body}-${checkDigit}` : null;
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

function isPendingCharge(record: StagingRecord): boolean {
  return String(record.payload.status ?? "").toLowerCase() === "pendiente";
}

function isRejectedCharge(record: StagingRecord): boolean {
  return String(record.payload.status ?? "").toLowerCase() === "rechazado";
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

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function identifierList(value: unknown): string {
  if (!Array.isArray(value)) return text(value);
  return value
    .map((item) => text(typeof item === "object" ? record(item).id : item, ""))
    .filter(Boolean)
    .join(", ") || "Sin dato";
}

function TokuPaymentMethodProfile({ payload }: { payload: Record<string, unknown> }) {
  const customer = record(payload.customer);
  const method = record(payload.payment_method);
  const card = record(method.card);
  const fields = (items: [string, unknown][]) => (
    <dl className="field-list payment-method-fields">
      {items.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{text(value)}</dd>
        </div>
      ))}
    </dl>
  );

  return (
    <>
      <section className="panel">
        <p className="eyebrow">MÉTODO DE PAGO</p>
        <h3>{text(method.type, "Método sin tipo")}</h3>
        {fields([
          ["Estado", method.status],
          ["Gateway", payload.gateway],
          ["Creado", method.created_at],
          ["ID método", method.id],
          ["ID externo", method.external_id],
          ["Cuenta", payload.id_account],
          ["Sesión de checkout", payload.id_checkout_session],
        ])}
      </section>
      <section className="panel client-subscriptions">
        <p className="eyebrow">CLIENTE</p>
        {fields([
          ["Nombre", customer.name],
          ["RUT", customer.government_id],
          ["Correo electrónico", customer.email],
          ["Teléfono", customer.phone_number],
          ["ID cliente", customer.id ?? customer.external_id],
        ])}
      </section>
      {Object.keys(card).length ? (
        <section className="panel client-subscriptions">
          <p className="eyebrow">TARJETA</p>
          {fields([
            ["Marca", card.card_brand],
            ["Tipo", card.card_type],
            ["Titular", card.card_holder],
            ["Últimos dígitos", card.last_digits],
            ["Banco", card.bank_name],
            ["Vencimiento", card.expiration_month && card.expiration_year ? `${card.expiration_month}/${card.expiration_year}` : null],
            ["País emisor", card.institution_country],
            ["3D Secure", card.three_d_secure === true ? "Sí" : card.three_d_secure === false ? "No" : null],
          ])}
        </section>
      ) : null}
      <section className="panel client-subscriptions">
        <p className="eyebrow">ASOCIACIONES</p>
        {fields([
          ["IDs de suscripciones", identifierList(payload.subscription_ids)],
          ["IDs de productos", identifierList(payload.product_ids)],
        ])}
      </section>
    </>
  );
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

const vpPlatformLabel = (record: StagingRecord) =>
  record.source === "virtualpos1" ? "VP 1" : record.source === "virtualpos2" ? "VP 2" : record.source;

function virtualPosColumns(resource: string): TableColumn[] {
  const clientRut = (record: StagingRecord) =>
    text(
      nested(record.payload, "client", "social_id") ?? record.payload.social_id,
    );
  const plataforma: TableColumn = { label: "Plataforma", value: vpPlatformLabel };
  if (resource === "client")
    return [
      plataforma,
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
      plataforma,
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
      plataforma,
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
      plataforma,
      {
        label: "Fecha de cargo",
        value: (record) => text(record.payload.charge_date),
      },
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "Estado", value: (record) => text(record.payload.status) },
      { label: "ID subscripción", value: (record) => text(record.payload.suscription_id) },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      { label: "Acciones", value: () => "Eliminar" },
    ];
  return [
    plataforma,
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
    { label: "Acciones", value: () => "Eliminar" },
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
      { label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "subscription")
    return [
      {
        label: "ID",
        value: (record) => text(record.payload.id, record.external_id),
      },
      { label: "ID cliente", value: (record) => text(nested(record.payload, "customer", "id") ?? record.payload.customer) },
      { label: "Monto", value: (record) => text(record.payload.amount) },
      { label: "Estado", value: (record) => text(record.payload.status ?? nested(record.payload, "recurring", "status")) },
      { label: "F. Inicio", value: (record) => text(record.payload.anchor ?? nested(record.payload, "recurring", "anchor")) },
      {
        label: "F. Cancelacion",
        value: (record) => text(record.payload.end_date ?? nested(record.payload, "recurring", "end_date")),
      },
      { label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "payment_method") {
    const method = (item: StagingRecord) => record(item.payload.payment_method);
    const card = (item: StagingRecord) => record(method(item).card);
    const customer = (item: StagingRecord) => record(item.payload.customer);
    const subscriptionCount = (item: StagingRecord) => {
      const subscriptions = item.payload.subscription_ids ?? method(item).subscription_ids;
      return Array.isArray(subscriptions) ? String(subscriptions.length) : "0";
    };
    return [
      {
        label: "ID",
        value: (item) => text(method(item).id ?? item.payload.id, item.external_id),
      },
      { label: "Estado", value: (item) => text(method(item).status ?? item.payload.status) },
      {
        label: "F. Creacion",
        value: (item) => text(method(item).created_at ?? item.payload.created_at),
      },
      {
        label: "Cliente",
        value: (item) => text(customer(item).name ?? customer(item).id ?? item.payload.customer_id ?? item.payload.customer),
      },
      {
        label: "Marca",
        value: (item) => text(card(item).card_brand ?? method(item).card_brand),
      },
      { label: "Terminacion", value: (item) => text(card(item).last_digits ?? method(item).last_digits) },
      { label: "Banco", value: (item) => text(card(item).bank_name ?? method(item).bank_name) },
      { label: "Tipo tarjeta", value: (item) => cardTypeText(card(item).card_type ?? method(item).card_type) },
      {
        label: "Subscripciones",
        value: subscriptionCount,
      },
      { label: "Acciones", value: () => "Eliminar" },
    ];
  }
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
      { label: "Acciones", value: () => "Acciones" },
    ];
  return [
    {
      label: "ID",
      value: (record) => text(nested(record.payload, "transaction", "id") ?? record.payload.id, record.external_id),
    },
    {
      label: "ID cliente",
      value: (record) => text(nested(record.payload, "customer", "id") ?? record.payload.customer_id),
    },
    {
      label: "ID subscripcion",
      value: (record) => text(record.payload.subscription_id),
    },
    { label: "Monto", value: (record) => text(nested(record.payload, "transaction", "amount") ?? record.payload.amount) },
    {
      label: "Fecha transaccion",
        value: (record) => text(nested(record.payload, "transaction", "transaction_date") ?? record.payload.transaction_date),
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
      { label: "Acciones", value: () => "Acciones" },
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
      { label: "Acciones", value: () => "Eliminar" },
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
  tchView,
  openProvider,
  theme,
  onDashboard,
  generalView,
  onGeneralClients,
  onGeneralSubscriptions,
  onChannel,
  onSection,
  onToggle,
  onTheme,
  onTch,
  permissions,
  onAdmin,
  onLogout,
  open,
  onClose,
  vpRetryOpen,
  onVpRetry,
}: {
  activeSection: ProviderSection | null;
  channel: string | null;
  tchView: string | null;
  openProvider: string | null;
  theme: "light" | "dark";
  onDashboard: () => void;
  generalView: "summary" | "clients" | "subscriptions";
  onGeneralClients: () => void;
  onGeneralSubscriptions: () => void;
  onChannel: (source: string) => void;
  onSection: (section: ProviderSection) => void;
  onToggle: (provider: string) => void;
  onTheme: () => void;
  onTch: (view: "summary" | "clientes" | "suscripciones" | "transacciones") => void;
  permissions: string[];
  onAdmin: () => void;
  onLogout: () => void;
  open: boolean;
  onClose: () => void;
  vpRetryOpen: boolean;
  onVpRetry: () => void;
}) {
  const can = (permission: string) => permissions.includes(permission);
  const go = (fn: () => void) => () => { fn(); onClose(); };
  const visibleGroups = providerGroups.map((group) => ({
    ...group,
    sections: group.sections.filter((section) => can(resourcePermission(section.source, section.resource))),
  })).filter((group) => group.sections.length > 0);
  return (
    <aside className={`sidebar${open ? " open" : ""}`}>
      <div className="sidebar-toprow">
        <button className="sidebar-brand" onClick={go(onDashboard)}>
          <span>CRM</span>
          <strong>Suscripciones</strong>
        </button>
        <button className="sidebar-close" onClick={onClose} aria-label="Cerrar menú">✕</button>
      </div>
      <nav className="sidebar-nav" aria-label="Navegacion principal">
        {can("dashboard.view") ? <button
          className={!activeSection && !channel && !tchView && generalView === "summary" ? "sidebar-item active" : "sidebar-item"}
          onClick={go(onDashboard)}
        >
          Dashboard
        </button> : null}
        {can("dashboard.view") ? <>
          <button className={generalView === "clients" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(onGeneralClients)}>Clientes</button>
          <button className={generalView === "subscriptions" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(onGeneralSubscriptions)}>Suscripciones</button>
        </> : null}
        {visibleGroups.map((group) => (
          <section className="sidebar-group" key={group.name}>
            <div className="channel-heading">
              <button
                className={
                  channel === group.sections[0].source
                    ? "channel-dashboard active"
                    : "channel-dashboard"
                }
                onClick={go(() => onChannel(group.sections[0].source))}
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
              ? <>
                  {group.sections.map((section) => (
                    <button
                      className={
                        activeSection?.source === section.source &&
                        activeSection.resource === section.resource
                          ? "sidebar-item nested active"
                          : "sidebar-item nested"
                      }
                      key={section.resource}
                      onClick={go(() => onSection(section))}
                    >
                      {section.label}
                    </button>
                  ))}
                  {group.name === "VirtualPOS" && can("virtualpos.charges.retry") ? (
                    <button
                      className={vpRetryOpen ? "sidebar-item nested active" : "sidebar-item nested"}
                      onClick={go(onVpRetry)}
                    >
                      Reintento de cargos
                    </button>
                  ) : null}
                </>
              : null}
          </section>
        ))}
        {can("tch.dashboard.view") ? (
          <section className="sidebar-group">
            <div className="channel-heading">
              <button
                className={tchView ? "channel-dashboard active" : "channel-dashboard"}
                onClick={go(() => onTch("summary"))}
              >
                TCH
              </button>
              <button
                className="sidebar-expand"
                aria-label="Expandir TCH"
                aria-expanded={openProvider === "TCH"}
                onClick={() => onToggle("TCH")}
              >
                {openProvider === "TCH" ? "-" : "+"}
              </button>
            </div>
            {openProvider === "TCH" ? (
              <>
                {can("tch.clientes.view") ? <button className={tchView === "clientes" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("clientes"))}>Clientes</button> : null}
                <button className={tchView === "suscripciones" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("suscripciones"))}>Suscripciones</button>
                <button className={tchView === "transacciones" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("transacciones"))}>Transacciones</button>
              </>
            ) : null}
          </section>
        ) : null}
        {can("users.manage") || can("roles.manage") ? <button className="sidebar-item" onClick={go(onAdmin)}>Administración</button> : null}
      </nav>
      <div className="sidebar-footer">
        <button className="theme-btn" onClick={onTheme} aria-label="Cambiar tema">
          <span className="theme-btn-icon">{theme === "dark" ? "☀" : "◐"}</span>
          {theme === "dark" ? "Modo claro" : "Modo oscuro"}
        </button>
        <button className="theme-btn" onClick={go(onLogout)}>Cerrar sesión</button>
      </div>
    </aside>
  );
}

function resourcePermission(source: string, resource: string): string {
  const names: Record<string, Record<string, string>> = {
    virtualpos: { client: "clients", plan: "plans", subscription: "subscriptions", charge: "charges", payment: "payments" },
    toku: { customer: "customers", subscription: "subscriptions", payment_method: "payment_methods", invoice: "invoices", transaction: "transactions" },
    payku: { client: "clients", plan: "plans", subscription: "subscriptions", transaction: "transactions" },
  };
  return `${source}.${names[source]?.[resource] ?? resource}.view`;
}

function LoginScreen({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
      const payload = await response.json() as AuthSession | { detail?: string };
      if (!response.ok || !("user" in payload)) throw new Error("detail" in payload ? payload.detail : "No se pudo iniciar sesión");
      csrfToken = payload.csrf_token;
      onLogin(payload);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "No se pudo iniciar sesión");
    } finally { setSubmitting(false); }
  }
  return <main className="login-shell"><section className="panel login-panel"><p className="eyebrow">CRM SUSCRIPCIONES</p><h1>Iniciar sesión</h1><form className="login-form" onSubmit={submit}><label>Usuario<input name="username" required autoComplete="username" /></label><label>Contraseña<input name="password" type="password" required autoComplete="current-password" /></label><button className="save-button" disabled={submitting}>{submitting ? "Ingresando..." : "Ingresar"}</button></form>{error ? <p className="error-message">{error}</p> : null}</section></main>;
}

function AdminUsers({ canManageUsers }: { canManageUsers: boolean }) {
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { getJson<AdminRole[]>("/api/v1/admin/roles").then(setRoles).catch(() => setMessage("No se pudieron cargar los roles.")); }, []);
  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await postJson("/api/v1/admin/users", { username: form.get("username"), password: form.get("password"), role_ids: form.getAll("role_ids") });
      event.currentTarget.reset();
      setMessage("Usuario creado.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo crear el usuario."); }
  }
  return <main className="app-shell"><section className="panel"><p className="eyebrow">ADMINISTRACIÓN</p><h1>Usuarios y roles</h1>{canManageUsers ? <form className="edit-form-grid" onSubmit={createUser}><label>Usuario<input name="username" required minLength={3} /></label><label>Contraseña temporal<input name="password" type="password" required minLength={12} /></label><fieldset className="edit-form-wide"><legend>Roles</legend>{roles.map((role) => <label key={role.id}><input type="checkbox" name="role_ids" value={role.id} /> {role.name}</label>)}</fieldset><button className="save-button">Crear usuario</button></form> : <p className="muted-copy">No tiene permiso para crear usuarios.</p>}{message ? <p className="resource-copy">{message}</p> : null}</section></main>;
}

function Metric({
  label,
  value,
  tone,
  amount,
  mode = "count",
}: {
  label: string;
  value: number;
  tone: string;
  amount?: number;
  mode?: "count" | "amount";
}) {
  const accent = METRIC_COLORS[tone] ?? "#4a90c4";
  const showAmountPrimary = mode === "amount" && amount !== undefined;
  return (
    <article
      className="metric-card"
      style={{ "--accent": accent } as React.CSSProperties}
    >
      <p className="metric-label">{label}</p>
      {showAmountPrimary ? (
        <>
          <strong className="metric-value metric-value-money">
            ${amount!.toLocaleString("es-CL")}
          </strong>
          <span className="metric-amount">{value.toLocaleString("es-CL")} registros</span>
        </>
      ) : (
        <>
          <strong className="metric-value">{value.toLocaleString("es-CL")}</strong>
          {amount !== undefined ? (
            <span className="metric-amount">${amount.toLocaleString("es-CL")}</span>
          ) : null}
        </>
      )}
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
                items.map((item) => (
                  <div
                    key={item.status}
                    className="status-bar-segment"
                    style={{
                      width: `${(item.count / total) * 100}%`,
                      background: chartStatusColor(item.status),
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
                {items.map((item) => (
                  <span key={item.status} className="status-legend-item">
                    <i
                      style={{
                        background: chartStatusColor(item.status),
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
  syncing,
  onMode,
  onYear,
  onOpenResource,
  onReport,
  onSync,
}: {
  data: ChannelDashboard;
  mode: "count" | "amount";
  year: number | null;
  syncing: boolean;
  onMode: (mode: "count" | "amount") => void;
  onYear: (year: number) => void;
  onOpenResource: (resource: string) => void;
  onReport: (scope: string) => void;
  onSync: (source: string) => void;
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
                value={year ?? defaultYear(data.years) ?? data.years[0]}
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
          <div className="channel-hero-bottom-row">
            <div
              className={`sync-state ${data.last_sync?.status === "completed" ? "ready" : "attention"}`}
            >
              <span />
              {data.last_sync?.status ?? "Sin sincronización"}
            </div>
            <button
              className={`sync-btn ${syncing ? "syncing" : ""}`}
              disabled={syncing}
              onClick={() => onSync(data.source)}
            >
              {syncing ? "Sincronizando…" : "↻ Sincronizar"}
            </button>
            <button className="sync-btn sync-btn-secondary" onClick={() => onReport(data.source)}>Generar reporte</button>
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
            mode={mode}
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
          {data.source === "virtualpos" && data.charges_monthly?.length ? (
            <MonthlyStatusChart data={data.charges_monthly} mode={dataKey} year={year} />
          ) : data.source === "toku" && data.invoices_monthly?.length ? (
            <MonthlyStatusChart data={data.invoices_monthly} mode={dataKey} year={year} />
          ) : data.source === "payku" && (data.transactions_monthly as MonthlyStatusEntry[] | undefined)?.length ? (
            <MonthlyStatusChart data={data.transactions_monthly as MonthlyStatusEntry[]} mode={dataKey} year={year} />
          ) : chartData.length ? (
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
              <MonthlyStatusChart data={data.activation_monthly} mode={mode} year={year} />
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
              {"status" in ((data.churn_monthly as MonthlyStatusEntry[])[0] ?? {}) ? (
                <MonthlyStatusChart data={data.churn_monthly as MonthlyStatusEntry[]} mode={mode} year={year} />
              ) : (
                <MonthlySimpleChart data={data.churn_monthly as MonthlyEntry[]} color={CHANNEL_COLORS[data.source]} mode={mode} year={year} />
              )}
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

function ReportDialog({ scope, onClose }: { scope: string; onClose: () => void }) {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const names: Record<string, string> = { general: "operación consolidada", virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
  function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dateFrom || !dateTo) return setError("Selecciona ambas fechas.");
    if (dateFrom >= dateTo) return setError("La fecha inicial debe ser menor que la fecha final.");
    const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
    window.open(`/api/v1/reports/${scope}?${query}`, "_blank", "noopener,noreferrer");
    onClose();
  }
  return <div className="edit-dialog-backdrop" role="presentation">
    <form className="edit-dialog" aria-modal="true" aria-label="Generar reporte" onSubmit={generate}>
      <div className="edit-dialog-heading"><div><p className="eyebrow">REPORTE OPERATIVO</p><h3>{names[scope] ?? scope}</h3></div></div>
      <p className="edit-dialog-note">Los indicadores muestran el estado actual. Los gráficos se calcularán solo para el período seleccionado.</p>
      <div className="edit-form-grid"><label>Fecha inicial<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} required /></label><label>Fecha final<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} required /></label></div>
      {error ? <p className="error-message form-error">{error}</p> : null}
      <div className="edit-dialog-actions"><button type="submit" className="save-button">Generar reporte</button><button type="button" className="cancel-button" onClick={onClose}>Cancelar</button></div>
    </form>
  </div>;
}

type ChargeEntry = MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" };
function applyChargeFilter(data: ChargeEntry[], filter: "todas" | "pagada" | "rechazada"): MonthlyStatusEntry[] {
  const entries = filter === "todas" ? data : data.filter(e => e.charge_status === filter);
  if (filter !== "todas") return entries;
  const map = new Map<string, MonthlyStatusEntry>();
  for (const e of entries) {
    const key = `${e.year}-${e.month}-${e.status}`;
    const existing = map.get(key);
    if (existing) { existing.count += e.count; existing.amount += e.amount; }
    else map.set(key, { ...e });
  }
  return [...map.values()];
}

function App() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [adminOpen, setAdminOpen] = useState(false);
  const [summary, setSummary] = useState<Summary>({ sources: [] });
  const [generalData, setGeneralData] = useState<GeneralDashboard | null>(null);
  const [generalView, setGeneralView] = useState<"summary" | "clients" | "subscriptions">("summary");
  const [generalClients, setGeneralClients] = useState<GeneralClients | null>(null);
  const [generalClientQuery, setGeneralClientQuery] = useState("");
  const [generalClientFilter, setGeneralClientFilter] = useState<"all" | "rut" | "name" | "last_name" | "platform" | "email" | "phone">("all");
  const [generalClientOffset, setGeneralClientOffset] = useState(0);
  const [generalClientDetail, setGeneralClientDetail] = useState<GeneralClientDetail | null>(null);
  const [generalSubscriptions, setGeneralSubscriptions] = useState<GeneralSubscriptions | null>(null);
  const [generalSubscriptionQuery, setGeneralSubscriptionQuery] = useState("");
  const [generalSubscriptionFilter, setGeneralSubscriptionFilter] = useState<"all" | "id" | "rut" | "client" | "platform" | "status">("all");
  const [generalSubscriptionOffset, setGeneralSubscriptionOffset] = useState(0);
  const [activeSection, setActiveSection] = useState<ProviderSection | null>(
    null,
  );
  const [channel, setChannel] = useState<string | null>(null);
  const [channelData, setChannelData] = useState<ChannelDashboard | null>(null);
  const [openProvider, setOpenProvider] = useState<string | null>("VirtualPOS");
  const [records, setRecords] = useState<StagingResponse>({
    items: [],
    total: 0,
    offset: 0,
    limit: RECORDS_PAGE_SIZE,
  });
  const [recordsOffset, setRecordsOffset] = useState(0);
  const [statusValues, setStatusValues] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [channelLoading, setChannelLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
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
  const [creatingClient, setCreatingClient] = useState(false);
  const [clientVpPlatform, setClientVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingClient, setSavingClient] = useState(false);
  const [clientFormError, setClientFormError] = useState<string | null>(null);
  const [clientFieldErrors, setClientFieldErrors] = useState<Record<string, string>>({});
  const [clientSaveNotice, setClientSaveNotice] = useState<string | null>(null);
  const [creatingPlan, setCreatingPlan] = useState(false);
  const [planVpPlatform, setPlanVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingPlan, setSavingPlan] = useState(false);
  const [planFormError, setPlanFormError] = useState<string | null>(null);
  const [planFieldErrors, setPlanFieldErrors] = useState<Record<string, string>>({});
  const [planSaveNotice, setPlanSaveNotice] = useState<string | null>(null);
  const [creatingSubscription, setCreatingSubscription] = useState(false);
  const [subVpPlatform, setSubVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingSubscription, setSavingSubscription] = useState(false);
  const [subscriptionFormError, setSubscriptionFormError] = useState<string | null>(null);
  const [subscriptionFieldErrors, setSubscriptionFieldErrors] = useState<Record<string, string>>({});
  const [subscriptionSaveNotice, setSubscriptionSaveNotice] = useState<string | null>(null);
  const [cancelingSubscription, setCancelingSubscription] = useState<StagingRecord | null>(null);
  const [savingCancelSubscription, setSavingCancelSubscription] = useState(false);
  const [cancelSubscriptionError, setCancelSubscriptionError] = useState<string | null>(null);
  const [creatingCharge, setCreatingCharge] = useState<StagingRecord | null>(null);
  const [savingCharge, setSavingCharge] = useState(false);
  const [chargeFormError, setChargeFormError] = useState<string | null>(null);
  const [chargeFieldErrors, setChargeFieldErrors] = useState<Record<string, string>>({});
  const [chargeSaveNotice, setChargeSaveNotice] = useState<string | null>(null);
  const [cancelingCharge, setCancelingCharge] = useState<StagingRecord | null>(null);
  const [savingCancelCharge, setSavingCancelCharge] = useState(false);
  const [cancelChargeError, setCancelChargeError] = useState<string | null>(null);
  const [retryingCharge, setRetryingCharge] = useState<StagingRecord | null>(null);
  const [savingRetryCharge, setSavingRetryCharge] = useState(false);
  const [retryChargeError, setRetryChargeError] = useState<string | null>(null);
  const [editingProviderRecord, setEditingProviderRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderEdit, setSavingProviderEdit] = useState(false);
  const [providerEditError, setProviderEditError] = useState<string | null>(null);
  const [deletingRecord, setDeletingRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderDelete, setSavingProviderDelete] = useState(false);
  const [providerDeleteError, setProviderDeleteError] = useState<string | null>(null);
  const [managingTokuSub, setManagingTokuSub] = useState<StagingRecord | null>(null);
  const [savingTokuSubStatus, setSavingTokuSubStatus] = useState(false);
  const [tokuSubStatusError, setTokuSubStatusError] = useState<string | null>(null);
  const [filterField, setFilterField] = useState("");
  const [filterQuery, setFilterQuery] = useState("");
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"count" | "amount">("count");
  const [year, setYear] = useState<number | null>(null);
  const [generalMode, setGeneralMode] = useState<"count" | "amount">("count");
  const [generalYear, setGeneralYear] = useState<number | null>(null);
  const [reportScope, setReportScope] = useState<string | null>(null);
  const [debtFilter, setDebtFilter] = useState<"todas" | "pagada" | "rechazada">("todas");
  const [transFilter, setTransFilter] = useState<"todas" | "pagada" | "rechazada">("todas");
  // Reintento de cargos VirtualPOS
  const [vpRetryOpen, setVpRetryOpen] = useState(false);
  const [retryCharges, setRetryCharges] = useState<RejectedChargesResp | null>(null);
  const [retryLoading, setRetryLoading] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryDateFrom, setRetryDateFrom] = useState("");
  const [retryDateTo, setRetryDateTo] = useState("");
  const [retryPlatform, setRetryPlatform] = useState<"all" | "virtualpos" | "virtualpos1" | "virtualpos2">("all");
  const [retryReasonFilter, setRetryReasonFilter] = useState("");
  const [retryReasonOptions, setRetryReasonOptions] = useState<string[]>([]);
  const [retrySnapshot, setRetrySnapshot] = useState<Map<string, RejectedCharge>>(new Map());
  const [retryOffset, setRetryOffset] = useState(0);
  const [retrySelected, setRetrySelected] = useState<Set<string>>(new Set());
  const [retrying, setRetrying] = useState(false);
  const [retryResults, setRetryResults] = useState<BatchRetryResp | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("crm-theme") as "light" | "dark") ?? "light";
  });
  const [etlRunning, setEtlRunning] = useState(false);
  const [lastEtlRun, setLastEtlRun] = useState<EtlRun | null>(null);
  const [etlError, setEtlError] = useState<string | null>(null);
  const [vpPlatform, setVpPlatform] = useState<"all" | "virtualpos1" | "virtualpos2">("all");
  const [tchView, setTchView] = useState<"summary" | "clientes" | "suscripciones" | "transacciones" | "cliente-detalle" | "suscripcion-detalle" | "transaccion-detalle" | null>(null);
  const [tchSummary, setTchSummary] = useState<TchSummary | null>(null);
  const [tchSuscripciones, setTchSuscripciones] = useState<TchSuscripcionesResp | null>(null);
  const [tchTransacciones, setTchTransacciones] = useState<TchTransaccionesResp | null>(null);
  const [tchClientes, setTchClientes] = useState<TchClientesResp | null>(null);
  const [tchLoading, setTchLoading] = useState(false);
  const [tchError, setTchError] = useState<string | null>(null);
  const [tchSusPage, setTchSusPage] = useState(1);
  const [tchTransPage, setTchTransPage] = useState(1);
  const [tchSusFiltroEstado, setTchSusFiltroEstado] = useState("");
  const [tchClienteFiltro, setTchClienteFiltro] = useState("");
  const [tchClientesPage, setTchClientesPage] = useState(1);
  const [tchTransFiltroPeriodo, setTchTransFiltroPeriodo] = useState("");
  const [tchMode, setTchMode] = useState<"count" | "amount">("count");
  const [tchYear, setTchYear] = useState<number | null>(null);
  const [tchSuscripcionDetail, setTchSuscripcionDetail] = useState<TchSuscripcionDetail | null>(null);
  const [tchTransaccionDetail, setTchTransaccionDetail] = useState<TchTransaccionDetail | null>(null);
  const [tchClienteDetail, setTchClienteDetail] = useState<TchClienteDetail | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    getJson<AuthSession>("/api/v1/auth/me")
      .then((current) => { csrfToken = current.csrf_token; setSession(current); })
      .catch(() => setSession(null));
  }, []);

  useEffect(() => {
    if (!session) return;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("crm-theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => t === "light" ? "dark" : "light");

  useEffect(() => {
    if (!session) return;
    let mounted = true;
    getJson<Summary>("/api/v1/staging/summary")
      .then((data) => {
        if (mounted) setSummary(data);
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el resumen de staging."));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [session]);

  useEffect(() => {
    if (!session) return;
    let mounted = true;
    getJson<GeneralDashboard>("/api/v1/staging/dashboard/general")
      .then((data) => {
        if (mounted) {
          setGeneralData(data);
          setGeneralYear((current) => current ?? defaultYear(data.years));
        }
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el dashboard general."));
      });
    return () => {
      mounted = false;
    };
  }, [session, lastEtlRun?.finished_at]);

  useEffect(() => {
    if (!session || generalView !== "clients") return;
    const params = new URLSearchParams({ limit: "100", offset: String(generalClientOffset), filter_field: generalClientFilter });
    if (generalClientQuery.trim()) params.set("query", generalClientQuery.trim());
    getJson<GeneralClients>(`/api/v1/staging/dashboard/general/clients?${params}`)
      .then(setGeneralClients)
      .catch((err: unknown) => setError(friendlyError(err, "No se pudieron cargar los clientes consolidados.")));
  }, [session, generalView, generalClientQuery, generalClientFilter, generalClientOffset]);

  useEffect(() => {
    if (!session || generalView !== "subscriptions") return;
    const params = new URLSearchParams({ limit: "100", offset: String(generalSubscriptionOffset), filter_field: generalSubscriptionFilter });
    if (generalSubscriptionQuery.trim()) params.set("query", generalSubscriptionQuery.trim());
    getJson<GeneralSubscriptions>(`/api/v1/staging/dashboard/general/subscriptions?${params}`)
      .then(setGeneralSubscriptions)
      .catch((err: unknown) => setError(friendlyError(err, "No se pudieron cargar las suscripciones consolidadas.")));
  }, [session, generalView, generalSubscriptionQuery, generalSubscriptionFilter, generalSubscriptionOffset]);

  useEffect(() => {
    if (!session || !activeSection) return;
    let mounted = true;
    const effectiveSource =
      activeSection.source === "virtualpos" && vpPlatform !== "all"
        ? vpPlatform
        : activeSection.source;
    const params = new URLSearchParams({
      source: effectiveSource,
      resource_type: activeSection.resource,
      offset: String(recordsOffset),
      limit: String(RECORDS_PAGE_SIZE),
    });
    if (filterField && filterQuery.trim()) {
      params.set("filter_field", filterField);
      params.set("query", filterQuery.trim());
    }
    const sortField = sortColumn
      ? filterFieldForColumn(activeSection.source, activeSection.resource, sortColumn)
      : null;
    if (sortField) {
      params.set("sort_field", sortField);
      params.set("sort_direction", sortDirection);
    }
    const path = `/api/v1/staging/records?${params}`;
    setLoading(true);
    getJson<StagingResponse>(path)
      .then((data) => {
        if (mounted) {
          setRecords((current) => recordsOffset === 0
            ? data
            : { ...data, items: [...current.items, ...data.items.filter((item) => !current.items.some((existing) => existing.id === item.id))] });
        }
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudieron cargar los registros."));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [session, activeSection, filterField, filterQuery, sortColumn, sortDirection, vpPlatform, recordsOffset]);

  useEffect(() => {
    if (!session || !activeSection || filterField !== "status") {
      setStatusValues([]);
      return;
    }
    const source = activeSection.source === "virtualpos" && vpPlatform !== "all"
      ? vpPlatform
      : activeSection.source;
    const params = new URLSearchParams({
      source,
      resource_type: activeSection.resource,
      filter_field: "status",
    });
    getJson<{ values: string[] }>(`/api/v1/staging/records/filter-values?${params}`)
      .then((data) => setStatusValues(data.values))
      .catch((err: unknown) => setError(friendlyError(err, "No se pudieron cargar los estados.")));
  }, [session, activeSection, filterField, vpPlatform]);

  useEffect(() => {
    if (!session || !channel) return;
    let mounted = true;
    getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${channel}`)
      .then((data) => {
        if (mounted) {
          setChannelData(data);
          setYear(defaultYear(data.years));
        }
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el dashboard del canal."));
      })
      .finally(() => {
        if (mounted) setChannelLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [session, channel]);

  useEffect(() => {
    if (!session || !tchView) return;
    let mounted = true;
    setTchLoading(true);
    setTchError(null);
    if (tchView === "summary") {
      getJson<TchSummary>("/api/v1/tch/summary")
        .then((d) => {
          if (mounted) {
            setTchSummary(d);
            setTchYear((current) => current ?? defaultYear(d.years));
          }
        })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar el resumen TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "clientes") {
      const params = new URLSearchParams({ limit: "50", page: String(tchClientesPage) });
      if (tchClienteFiltro) params.set("nombre", tchClienteFiltro);
      getJson<TchClientesResp>(`/api/v1/tch/clientes?${params}`)
        .then((d) => { if (mounted) setTchClientes(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar los clientes TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripciones") {
      const params = new URLSearchParams({ limit: "50", page: String(tchSusPage) });
      if (tchSusFiltroEstado) params.set("estado", tchSusFiltroEstado);
      getJson<TchSuscripcionesResp>(`/api/v1/tch/suscripciones?${params}`)
        .then((d) => { if (mounted) setTchSuscripciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las suscripciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transacciones") {
      const params = new URLSearchParams({ limit: "100", page: String(tchTransPage) });
      if (tchTransFiltroPeriodo) params.set("periodo", tchTransFiltroPeriodo);
      getJson<TchTransaccionesResp>(`/api/v1/tch/transacciones?${params}`)
        .then((d) => { if (mounted) setTchTransacciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las transacciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripcion-detalle" && tchSuscripcionDetail) {
      getJson<TchSuscripcionDetail>(`/api/v1/tch/suscripciones/${tchSuscripcionDetail.numero_ficha}`)
        .then((d) => { if (mounted) setTchSuscripcionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transaccion-detalle" && tchTransaccionDetail) {
      getJson<TchTransaccionDetail>(`/api/v1/tch/transacciones/${tchTransaccionDetail.id}`)
        .then((d) => { if (mounted) setTchTransaccionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "cliente-detalle" && tchClienteDetail) {
      getJson<TchClienteDetail>(`/api/v1/tch/clientes/${encodeURIComponent(tchClienteDetail.rut)}`)
        .then((d) => { if (mounted) setTchClienteDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha del cliente TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    }
    return () => { mounted = false; };
  }, [session, tchView, tchClientesPage, tchClienteFiltro, tchSusPage, tchSusFiltroEstado, tchTransPage, tchTransFiltroPeriodo, tchSuscripcionDetail?.numero_ficha, tchTransaccionDetail?.id, tchClienteDetail?.rut]);

  useEffect(() => {
    setClientFormError(null);
    setClientFieldErrors({});
    setClientSaveNotice(null);
  }, [editingClient?.id, creatingClient]);

  function clearDetails() {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setProviderRecordDetail(null);
  }

  async function saveVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingClient || savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const changes: Record<string, string> = {};
    for (const field of virtualPosClientEditFields) {
      const rawValue = String(formData.get(field.name) ?? "").trim();
      const value = field.name === "social_id_type" ? documentType(rawValue) : rawValue;
      const current = field.name === "social_id_type"
        ? documentType(editingClient.payload[field.name])
        : text(editingClient.payload[field.name], "");
      if (value !== current) changes[field.name] = value;
    }
    const selectedDocumentType = documentType(formData.get("social_id_type"));
    if (selectedDocumentType === "1" && (changes.social_id || changes.social_id_type)) {
      const rut = normalizeRut(String(formData.get("social_id") ?? ""));
      if (!rut) {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados.");
        return;
      }
      if (changes.social_id) changes.social_id = rut;
    }
    if (changes.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(changes.email)) {
      setClientFieldErrors({ email: "Ingresa un correo electrónico válido." });
      setClientFormError("Revisa los campos marcados.");
      return;
    }
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote !== text(editingClient.payload.private_note, "")) changes.private_note = privateNote;
    if (!Object.keys(changes).length) {
      setClientFormError("No hay cambios para guardar.");
      return;
    }

    const clientId = text(editingClient.payload.uuid, editingClient.external_id);
    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const updated = await putJson<{ payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/clients/${encodeURIComponent(clientId)}`,
        changes,
      );
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) => (
          record.id === editingClient.id ? { ...record, payload: updated.payload } : record
        )),
      }));
      setClientDetail((current) => current && current.client.id === editingClient.id
        ? { ...current, client: { ...current.client, payload: updated.payload } }
        : current);
      setEditingClient(null);
      setClientSaveNotice("Cambios guardados correctamente.");
    } catch (saveError) {
      const message = friendlyError(saveError, "No se pudo guardar el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const fieldErrors: Record<string, string> = {};

    const rawValues = Object.fromEntries(
      virtualPosClientEditFields.map((field) => [field.name, String(formData.get(field.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.first_name) fieldErrors.first_name = "El nombre es obligatorio.";
    if (!rawValues.email) {
      fieldErrors.email = "El correo electrónico es obligatorio.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(rawValues.email)) {
      fieldErrors.email = "Ingresa un correo electrónico válido.";
    }
    if (!rawValues.social_id_type) {
      fieldErrors.social_id_type = "Selecciona el tipo de documento.";
    }
    if (!rawValues.social_id) {
      fieldErrors.social_id = "El número de documento es obligatorio.";
    }

    const socialIdType = documentType(rawValues.social_id_type);
    if (!fieldErrors.social_id && rawValues.social_id) {
      if (socialIdType === "1") {
        const rut = normalizeRut(rawValues.social_id);
        if (!rut) fieldErrors.social_id = "El RUT no es válido. Ejemplo: 12345678-9";
        else rawValues.social_id = rut;
      } else if (socialIdType === "2") {
        if (rawValues.social_id.length < 5) fieldErrors.social_id = "El DNI debe tener al menos 5 caracteres.";
      }
    }

    if (rawValues.phone_number && !/^\+?[\d\s\-()]{7,20}$/.test(rawValues.phone_number)) {
      fieldErrors.phone_number = "Ingresa un teléfono válido.";
    }

    if (Object.keys(fieldErrors).length) {
      setClientFieldErrors(fieldErrors);
      setClientFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const normalizedSocialId = socialIdType === "1" ? normalizeRut(rawValues.social_id) ?? rawValues.social_id : rawValues.social_id;
    const duplicate = records.items.find((item) => {
      const itemSocial = String(item.payload.social_id ?? "");
      return itemSocial && itemSocial === normalizedSocialId;
    });
    if (duplicate) {
      setClientFieldErrors({ social_id: "Ya existe un cliente con este documento en el listado actual." });
      setClientFormError("Ya existe un cliente con ese documento de identidad en VirtualPOS.");
      return;
    }

    const client: Record<string, string> = {};
    for (const [key, value] of Object.entries(rawValues)) {
      if (value !== "") client[key] = value;
    }
    if (client.social_id_type) client.social_id_type = socialIdType;
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote) client.private_note = privateNote;
    client.platform = clientVpPlatform;

    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/clients",
        client,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "client", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingClient(false);
      setClientSaveNotice("Cliente creado correctamente.");
    } catch (createError) {
      const message = friendlyError(createError, "No se pudo crear el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingPlan) return;
    setPlanFormError(null);
    setPlanFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const rawValues = Object.fromEntries(
      virtualPosPlanCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.name) errors.name = "El nombre del plan es obligatorio.";
    const amount = rawValues.amount === "" ? NaN : Number(rawValues.amount);
    if (rawValues.amount === "" || isNaN(amount) || amount < 0) errors.amount = "Ingresa un monto válido (número ≥ 0).";
    if (!rawValues.currency) errors.currency = "Selecciona una moneda.";
    if (!rawValues.frequency_type) errors.frequency_type = "Selecciona la frecuencia de cobro.";

    const trialDays = rawValues.trial_days ? Number(rawValues.trial_days) : undefined;
    if (rawValues.trial_days && (isNaN(trialDays!) || trialDays! < 0)) errors.trial_days = "Los días de prueba deben ser un número ≥ 0.";
    const numCharges = rawValues.num_charges ? Number(rawValues.num_charges) : undefined;
    if (rawValues.num_charges && (isNaN(numCharges!) || numCharges! < 0)) errors.num_charges = "El número de cobros debe ser ≥ 0.";
    const fixedDay = rawValues.fixed_amount_day_charge ? Number(rawValues.fixed_amount_day_charge) : undefined;
    if (rawValues.fixed_amount_day_charge && (isNaN(fixedDay!) || fixedDay! < 1 || fixedDay! > 28)) errors.fixed_amount_day_charge = "El día de cobro debe ser entre 1 y 28.";
    const activationAmount = rawValues.activation_amount ? Number(rawValues.activation_amount) : undefined;
    if (rawValues.activation_amount && (isNaN(activationAmount!) || activationAmount! < 0)) errors.activation_amount = "El monto de activación debe ser ≥ 0.";

    if (Object.keys(errors).length) {
      setPlanFieldErrors(errors);
      setPlanFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = { platform: planVpPlatform, name: rawValues.name, amount, currency: rawValues.currency, frequency_type: rawValues.frequency_type };
    if (rawValues.description) body.description = rawValues.description;
    if (trialDays !== undefined) body.trial_days = trialDays;
    if (numCharges !== undefined) body.num_charges = numCharges;
    if (fixedDay !== undefined) body.fixed_amount_day_charge = fixedDay;
    if (activationAmount !== undefined) body.activation_amount = activationAmount;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal === "true";
    if (rawValues.show_in_terminal) body.show_in_terminal = rawValues.show_in_terminal === "true";
    if (rawValues.is_active) body.is_active = rawValues.is_active === "true";
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.suscription_url) body.suscription_url = rawValues.suscription_url;
    if (rawValues.type) body.type = rawValues.type;

    setSavingPlan(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/plans",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "plan", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingPlan(false);
      setPlanSaveNotice("Plan creado correctamente.");
    } catch (err) {
      setPlanFormError(friendlyError(err, "No se pudo crear el plan."));
    } finally {
      setSavingPlan(false);
    }
  }

  async function createVirtualPOSSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingSubscription) return;
    setSubscriptionFormError(null);
    setSubscriptionFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const rawValues = Object.fromEntries(
      virtualPosSubscriptionCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    const errors: Record<string, string> = {};
    if (!rawValues.plan_id) errors.plan_id = "El ID del plan es obligatorio.";
    if (!rawValues.email) errors.email = "El email es obligatorio.";
    if (!rawValues.first_name) errors.first_name = "El nombre es obligatorio.";
    if (!rawValues.last_name) errors.last_name = "El apellido es obligatorio.";
    if (!rawValues.social_id) errors.social_id = "El RUT es obligatorio.";

    if (Object.keys(errors).length) {
      setSubscriptionFieldErrors(errors);
      setSubscriptionFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = {
      platform: subVpPlatform,
      plan_id: rawValues.plan_id,
      email: rawValues.email,
      first_name: rawValues.first_name,
      last_name: rawValues.last_name,
      social_id: rawValues.social_id,
    };
    if (rawValues.phone_number) body.phone_number = rawValues.phone_number;
    if (rawValues.service_id) body.service_id = rawValues.service_id;
    if (rawValues.channel) body.channel = rawValues.channel;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal;
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.callback_url) body.callback_url = rawValues.callback_url;

    setSavingSubscription(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/subscriptions",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "subscription", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingSubscription(false);
      setSubscriptionSaveNotice("Suscripción creada correctamente.");
    } catch (err) {
      setSubscriptionFormError(friendlyError(err, "No se pudo crear la suscripción."));
    } finally {
      setSavingSubscription(false);
    }
  }

  async function createVirtualPOSCharge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingCharge || !creatingCharge) return;
    setChargeFormError(null);
    setChargeFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const chargeDate = String(formData.get("charge_date") ?? "").trim();
    const amountRaw = String(formData.get("amount") ?? "").trim();
    const description = String(formData.get("description") ?? "").trim();
    const internalCode = String(formData.get("internal_code") ?? "").trim();

    if (!chargeDate) {
      errors.charge_date = "La fecha del cargo es obligatoria.";
    } else {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const selected = new Date(chargeDate);
      if (isNaN(selected.getTime())) {
        errors.charge_date = "Ingresa una fecha válida.";
      } else if (selected < today) {
        errors.charge_date = "La fecha del cargo no puede ser una fecha pasada.";
      }
    }
    const amount = amountRaw === "" ? NaN : Number(amountRaw);
    if (amountRaw === "" || isNaN(amount) || amount < 1) {
      errors.amount = "Ingresa un monto válido (número ≥ 1).";
    }

    if (Object.keys(errors).length) {
      setChargeFieldErrors(errors);
      setChargeFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const subscriptionId = String(creatingCharge.payload.id ?? creatingCharge.external_id);
    const body: Record<string, unknown> = { charge_date: chargeDate, amount };
    if (description) body.description = description;
    if (internalCode) body.internal_code = internalCode;

    setSavingCharge(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subscriptionId)}/charges`,
        body,
      );
      setCreatingCharge(null);
      setChargeSaveNotice(`Cargo creado correctamente (ID: ${created.external_id}).`);
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === creatingCharge.external_id) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: [{ id: created.id, source: created.source, resource_type: "charge", external_id: created.external_id, payload: created.payload }, ...prev.charges],
                charge_total: prev.charge_total + 1,
              }
            : prev,
        );
      }
    } catch (err) {
      setChargeFormError(friendlyError(err, "No se pudo crear el cargo."));
    } finally {
      setSavingCharge(false);
    }
  }

  async function cancelVirtualPOSSubscription() {
    if (savingCancelSubscription || !cancelingSubscription) return;
    setSavingCancelSubscription(true);
    setCancelSubscriptionError(null);
    const subExternalId = String(cancelingSubscription.payload.id ?? cancelingSubscription.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subExternalId)}`,
      );
      const updatedStatus = result.status ?? "CANCELADA";
      setCancelingSubscription(null);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "subscription" && record.external_id === subExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === subExternalId) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                subscription: {
                  ...prev.subscription,
                  payload: { ...prev.subscription.payload, status: updatedStatus },
                },
              }
            : prev,
        );
      }
      if (clientDetail) {
        setClientDetail((prev) =>
          prev
            ? {
                ...prev,
                subscriptions: prev.subscriptions.map((s) =>
                  s.external_id === subExternalId
                    ? { ...s, payload: { ...s.payload, status: updatedStatus } }
                    : s,
                ),
              }
            : prev,
        );
      }
    } catch (err) {
      setCancelSubscriptionError(friendlyError(err, "No se pudo cancelar la suscripción."));
    } finally {
      setSavingCancelSubscription(false);
    }
  }

  async function cancelVirtualPOSCharge() {
    if (savingCancelCharge || !cancelingCharge) return;
    setSavingCancelCharge(true);
    setCancelChargeError(null);
    const chargeExternalId = String(cancelingCharge.payload.id ?? cancelingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}`,
      );
      const updatedStatus = result.status ?? "cancelado";
      setCancelingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} cancelado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setCancelChargeError(friendlyError(err, "No se pudo cancelar el cargo."));
    } finally {
      setSavingCancelCharge(false);
    }
  }

  async function retryVirtualPOSCharge() {
    if (savingRetryCharge || !retryingCharge) return;
    setSavingRetryCharge(true);
    setRetryChargeError(null);
    const chargeExternalId = String(retryingCharge.payload.id ?? retryingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}/retry`,
      );
      const rawStatus = result.status ?? "procesando";
      const updatedStatus = rawStatus.toLowerCase() === "rechazado" ? "procesando" : rawStatus;
      const updatedPayload = result.payload ?? retryingCharge.payload;
      setRetryingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} reintentado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, ...updatedPayload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, ...updatedPayload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, ...updatedPayload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setRetryChargeError(friendlyError(err, "No se pudo reintentar el cargo."));
    } finally {
      setSavingRetryCharge(false);
    }
  }

  async function saveProviderEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProviderRecord || savingProviderEdit) return;
    setProviderEditError(null);
    const { record, source, resourceType } = editingProviderRecord;
    const formData = new FormData(event.currentTarget);
    const fields = providerEditFields[source]?.[resourceType] ?? [];
    const changes: Record<string, unknown> = {};
    for (const field of fields) {
      const val = String(formData.get(field.name) ?? "").trim();
      const current = String(record.payload[field.name] ?? "").trim();
      if (val !== "" && val !== current) changes[field.name] = field.type === "number" ? Number(val) : val;
    }
    if (Object.keys(changes).length === 0) { setEditingProviderRecord(null); return; }
    setSavingProviderEdit(true);
    try {
      await refreshCsrfToken();
      let updatedPayload: Record<string, unknown> = record.payload;
      if (source === "toku" && resourceType === "customer") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      } else if (source === "payku" && resourceType === "client") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      }
      setEditingProviderRecord(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === record.external_id && item.source === source
            ? { ...item, payload: updatedPayload }
            : item,
        ),
      }));
    } catch (err) {
      setProviderEditError(friendlyError(err, "No se pudo guardar el cambio."));
    } finally {
      setSavingProviderEdit(false);
    }
  }

  async function confirmProviderDelete() {
    if (!deletingRecord || savingProviderDelete) return;
    setProviderDeleteError(null);
    const { record, source, resourceType } = deletingRecord;
    setSavingProviderDelete(true);
    try {
      await refreshCsrfToken();
      if (source === "toku" && resourceType === "customer") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "client") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "subscription") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/subscriptions/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "cancelled" } }
              : item,
          ),
        }));
      }
    } catch (err) {
      setProviderDeleteError(friendlyError(err, "No se pudo eliminar el registro."));
    } finally {
      setSavingProviderDelete(false);
    }
  }

  async function changeTokuSubscriptionStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!managingTokuSub || savingTokuSubStatus) return;
    setTokuSubStatusError(null);
    const formData = new FormData(event.currentTarget);
    const status = String(formData.get("status") ?? "").trim();
    if (!status) { setTokuSubStatusError("Selecciona un estado."); return; }
    const subId = String(managingTokuSub.payload.id ?? managingTokuSub.external_id);
    setSavingTokuSubStatus(true);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/toku/subscriptions/${encodeURIComponent(subId)}/status`,
        { status },
      );
      const updatedPayload = result.payload;
      setManagingTokuSub(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === managingTokuSub.external_id && item.source === "toku"
            ? { ...item, payload: { ...item.payload, ...updatedPayload, status: result.status } }
            : item,
        ),
      }));
    } catch (err) {
      setTokuSubStatusError(friendlyError(err, "No se pudo cambiar el estado."));
    } finally {
      setSavingTokuSubStatus(false);
    }
  }

  function showDashboard() {
    setAdminOpen(false);
    setVpRetryOpen(false);
    clearDetails();
    setActiveSection(null);
    setChannel(null);
    setTchView(null);
    setGeneralView("summary");
    setGeneralClientDetail(null);
    setError(null);
  }

  function showGeneralClients() {
    showDashboard();
    setGeneralView("clients");
  }

  function showGeneralSubscriptions() {
    showDashboard();
    setGeneralView("subscriptions");
  }

  function showTch(view: "summary" | "clientes" | "suscripciones" | "transacciones") {
    clearDetails();
    setChannel(null);
    setActiveSection(null);
    setAdminOpen(false);
    setVpRetryOpen(false);
    setError(null);
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail(null);
    setTchClienteDetail(null);
    setTchView(view);
    setOpenProvider("TCH");
  }

  function showTchSuscripcion(numeroFicha: number) {
    setTchClienteDetail(null);
    setTchTransaccionDetail(null);
    setTchSuscripcionDetail({ numero_ficha: numeroFicha } as TchSuscripcionDetail);
    setTchView("suscripcion-detalle");
  }

  function showTchTransaccion(id: string) {
    setTchClienteDetail(null);
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail({ id } as TchTransaccionDetail);
    setTchView("transaccion-detalle");
  }

  function showTchCliente(rut: string) {
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail(null);
    setTchClienteDetail({ rut, suscripciones: [] } as unknown as TchClienteDetail);
    setTchView("cliente-detalle");
  }

  function showChannel(source: string) {
    clearDetails();
    setActiveSection(null);
    setTchView(null);
    setVpRetryOpen(false);
    setChannelData(null);
    setChannelLoading(true);
    setError(null);
    setYear(null);
    setChannel(source);
    setOpenProvider(title(source));
  }
  function _pollEtlRun(run_id: string) {
    const poll = setInterval(() => {
      getJson<EtlRun>(`/api/v1/etl/runs/${run_id}`)
        .then((run) => {
          setLastEtlRun(run);
          if (run.status !== "running") {
            clearInterval(poll);
            setEtlRunning(false);
          }
        })
        .catch((err: unknown) => {
          clearInterval(poll);
          setEtlRunning(false);
          setEtlError(friendlyError(err, "Error al consultar el estado del ETL."));
        });
    }, 3000);
  }
  function runEtl() {
    if (etlRunning) return;
    setEtlRunning(true);
    setEtlError(null);
    postJson<{ run_id: string }>("/api/v1/etl/run")
      .then(({ run_id }) => _pollEtlRun(run_id))
      .catch((err: unknown) => {
        setEtlRunning(false);
        setEtlError(friendlyError(err, "Error al iniciar el ETL."));
      });
  }
  function runFullSync() {
    if (etlRunning) return;
    setEtlRunning(true);
    setEtlError(null);
    postJson<{ run_id: string }>("/api/v1/etl/full-sync", {
      providers: ["virtualpos", "toku", "payku"],
    })
      .then(({ run_id }) => _pollEtlRun(run_id))
      .catch((err: unknown) => {
        setEtlRunning(false);
        setEtlError(friendlyError(err, "Error al iniciar el Sync completo."));
      });
  }
  function syncChannel(source: string) {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    postJson<{ status: string }>(`/api/v1/staging/sync/${source}`)
      .then(() => {
        setChannelData(null);
        setChannelLoading(true);
        return getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${source}`);
      })
      .then((data) => {
        setChannelData(data);
        setYear(defaultYear(data.years));
      })
      .catch((err: unknown) => setError(friendlyError(err, "Error al sincronizar el canal.")))
      .finally(() => setSyncing(false));
  }
  function showSection(section: ProviderSection) {
    clearDetails();
    setChannel(null);
    setVpRetryOpen(false);
    setLoading(true);
    setError(null);
    setFilterField(stagingFilters[section.source]?.[section.resource]?.[0]?.value ?? "");
    setFilterQuery("");
    setRecordsOffset(0);
    setSortColumn(null);
    setSortDirection("asc");
    if (section.source === "virtualpos") setVpPlatform("all");
    setActiveSection(section);
    setOpenProvider(title(section.source));
  }
  function openChannelResource(resource: string) {
    const section = providerGroups
      .flatMap((group) => group.sections)
      .find((entry) => entry.source === channel && entry.resource === resource);
    if (section) showSection(section);
  }

  function showVpRetry() {
    clearDetails();
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(false);
    setVpRetryOpen(true);
    setOpenProvider("VirtualPOS");
    setRetryCharges(null);
    setRetryError(null);
    setRetryOffset(0);
    setRetrySelected(new Set());
    setRetryResults(null);
    setRetryReasonFilter("");
    getJson<{ reasons: string[] }>("/api/v1/writes/virtualpos/charges/rejection-reasons")
      .then((r) => setRetryReasonOptions(r.reasons))
      .catch(() => setRetryReasonOptions([]));
  }

  async function loadRetryCharges() {
    setRetryLoading(true);
    setRetryError(null);
    try {
      const params = new URLSearchParams({ offset: String(retryOffset), limit: "50" });
      if (retryDateFrom) params.set("date_from", retryDateFrom);
      if (retryDateTo) params.set("date_to", retryDateTo);
      if (retryPlatform !== "all") params.set("platform", retryPlatform);
      if (retryReasonFilter.trim()) params.set("rejection_reason", retryReasonFilter.trim());
      const data = await getJson<RejectedChargesResp>(`/api/v1/writes/virtualpos/charges/rejected?${params}`);
      setRetryCharges(data);
      setRetrySelected(new Set());
    } catch (err) {
      setRetryError(friendlyError(err, "Error al cargar cargos rechazados."));
    } finally {
      setRetryLoading(false);
    }
  }

  async function runBatchRetry() {
    if (retrySelected.size === 0 || retrying) return;
    setRetrying(true);
    setRetryResults(null);
    const snapshot = new Map(
      (retryCharges?.items ?? [])
        .filter((c) => retrySelected.has(c.id))
        .map((c) => [c.id, c])
    );
    setRetrySnapshot(snapshot);
    try {
      const result = await postJson<BatchRetryResp>("/api/v1/writes/virtualpos/charges/batch-retry", {
        charge_ids: [...retrySelected],
      });
      setRetryResults(result);
      setRetrySelected(new Set());
      await loadRetryCharges();
    } catch (err) {
      setRetryError(friendlyError(err, "Error al reintentar cargos."));
    } finally {
      setRetrying(false);
    }
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cliente."));
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del plan."));
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha de la subscripción."));
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cargo."));
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del pago."));
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
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del registro."));
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
  function toggleColumnSort(column: TableColumn) {
    if (!activeSection || !filterFieldForColumn(activeSection.source, activeSection.resource, column.label)) return;
    if (sortColumn === column.label) {
      setRecordsOffset(0);
      setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
      return;
    }
    setRecordsOffset(0);
    setSortColumn(column.label);
    setSortDirection("asc");
  }

  async function logout() {
    try { await postJson("/api/v1/auth/logout"); } finally {
      csrfToken = "";
      setSession(null);
      setAdminOpen(false);
    }
  }
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
                <th>Acción</th>
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
                  <td>
                    {isActiveSubscription(subscription) ? (
                      <button
                        className="cancel-subscription-button"
                        onClick={() => { setCancelSubscriptionError(null); setCancelingSubscription(subscription); }}
                      >
                        Cancelar
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {clientDetail.subscriptions.length === 0 ? (
                <tr>
                  <td colSpan={5}>Sin suscripciones asociadas por RUT.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CARGOS</p>
            <h3>Cobros generados por suscripción</h3>
          </div>
          <span>{clientDetail.charge_total} total{clientDetail.charge_total > 100 ? " · mostrando últimos 100" : ""}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>ID Cargo</th>
                <th>Suscripción</th>
                <th>Estado</th>
                <th>Monto</th>
              </tr>
            </thead>
            <tbody>
              {clientDetail.charges.map((charge) => (
                <tr key={charge.id}>
                  <td>{text(charge.payload.charge_date)}</td>
                  <td>
                    <button className="record-link" onClick={() => void openVirtualPosCharge(charge)}>
                      {text(charge.payload.id, charge.external_id)}
                    </button>
                  </td>
                  <td>{text(charge.payload.suscription_id, "—")}</td>
                  <td>{text(charge.payload.status)}</td>
                  <td>{text(charge.payload.amount)}</td>
                </tr>
              ))}
              {clientDetail.charges.length === 0 ? (
                <tr>
                  <td colSpan={5}>Sin cargos registrados para este cliente.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">TRANSACCIONES</p>
            <h3>Pagos procesados</h3>
          </div>
          <span>{clientDetail.payment_total} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha autorización</th>
                <th>ID Transacción</th>
                <th>Estado</th>
                <th>Monto bruto</th>
                <th>Abono neto</th>
                <th>Tipo</th>
              </tr>
            </thead>
            <tbody>
              {clientDetail.payments.map((payment) => {
                const order = (payment.payload as Record<string, Record<string, unknown>>).order ?? {};
                const deposit = (Array.isArray(order.deposits) ? order.deposits[0] : null) as Record<string, unknown> | null;
                return (
                  <tr key={payment.id}>
                    <td>{text(order.authorized_at as string)}</td>
                    <td>{text(payment.external_id)}</td>
                    <td>{text(order.status as string)}</td>
                    <td>{text(order.amount as string)}</td>
                    <td>{deposit ? text(String(deposit.payout_amount ?? "—")) : "—"}</td>
                    <td>{text(order.payment_type_code as string, "—")}</td>
                  </tr>
                );
              })}
              {clientDetail.payments.length === 0 ? (
                <tr>
                  <td colSpan={6}>Sin transacciones procesadas para este cliente.</td>
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
          <button
            className="create-charge-button"
            onClick={() => { setChargeFormError(null); setChargeFieldErrors({}); setCreatingCharge(subscriptionDetail.subscription); }}
          >
            + Nuevo cargo
          </button>
        </div>
      ) : null}
      {chargeSaveNotice ? <p className="save-notice">{chargeSaveNotice}</p> : null}
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
                <th>Acción</th>
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
                  <td>
                    {isPendingCharge(charge) ? (
                      <button
                        className="cancel-charge-button"
                        onClick={() => { setCancelChargeError(null); setCancelingCharge(charge); }}
                      >
                        Cancelar
                      </button>
                    ) : isRejectedCharge(charge) ? (
                      <button
                        className="retry-charge-button"
                        onClick={() => { setRetryChargeError(null); setRetryingCharge(charge); }}
                      >
                        Reintentar
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {subscriptionDetail.charges.length === 0 ? (
                <tr>
                  <td colSpan={5}>Sin cargos asociados a la subscripción.</td>
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
      <div className="client-detail-actions">
        {isPendingCharge(chargeDetail.charge) ? (
          <button
            className="cancel-charge-button"
            onClick={() => { setCancelChargeError(null); setCancelingCharge(chargeDetail.charge); }}
          >
            Cancelar en VP
          </button>
        ) : null}
        {isRejectedCharge(chargeDetail.charge) ? (
          <button
            className="retry-charge-button"
            onClick={() => { setRetryChargeError(null); setRetryingCharge(chargeDetail.charge); }}
          >
            Reintentar en VP
          </button>
        ) : null}
      </div>
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
      <div className="client-detail-actions">
        <button
          className="delete-button"
          onClick={() => setDeletingRecord({ record: paymentDetail.payment, source: "virtualpos", resourceType: "payment" })}
        >
          Eliminar
        </button>
      </div>
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
      <div className="client-detail-actions">
        {(providerEditFields[providerRecordDetail.record.source]?.[providerRecordDetail.record.resource_type] ?? []).length > 0 ? (
          <button
            className="edit-button"
            onClick={() => { setProviderEditError(null); setEditingProviderRecord({
              record: providerRecordDetail.record,
              source: providerRecordDetail.record.source,
              resourceType: providerRecordDetail.record.resource_type,
            }); }}
          >
            Editar
          </button>
        ) : null}
        {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "subscription" ? (
          <button
            className="edit-button"
            onClick={() => { setTokuSubStatusError(null); setManagingTokuSub(providerRecordDetail.record); }}
          >
            Gestionar estado
          </button>
        ) : null}
        {(deletableResources[providerRecordDetail.record.source] ?? []).includes(providerRecordDetail.record.resource_type) ? (
          <button
            className="delete-button"
            onClick={() => { setProviderDeleteError(null); setDeletingRecord({
              record: providerRecordDetail.record,
              source: providerRecordDetail.record.source,
              resourceType: providerRecordDetail.record.resource_type,
            }); }}
          >
            Eliminar
          </button>
        ) : null}
      </div>
      {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "payment_method" ? (
        <TokuPaymentMethodProfile payload={providerRecordDetail.record.payload} />
      ) : (
        <section className="panel">
          <p className="eyebrow">FICHA COMPLETA</p>
          <dl className="field-list">
            {Object.entries(providerRecordDetail.record.payload).flatMap(
              ([field, value]) => {
                const entries = objectEntries(value);
                if (entries.length) {
                  return entries.map(([subField, subValue]) => (
                    <div key={`${field}-${subField}`}>
                      <dt>
                        {field === "recurring"
                          ? `Recurrencia ${recurringFieldLabels[subField] ?? fieldLabel(subField)}`
                          : `${fieldLabel(field)} — ${fieldLabel(subField)}`}
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
      )}
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
                    <th>Acción</th>
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
                      <td className="action-cell">
                        {item.source === "toku" && group.resource_type === "subscription" ? (
                          <button
                            className="edit-button"
                            onClick={() => { setTokuSubStatusError(null); setManagingTokuSub(item); }}
                          >
                            Gestionar estado
                          </button>
                        ) : null}
                        {(providerEditFields[item.source]?.[group.resource_type] ?? []).length > 0 && !(item.source === "toku" && group.resource_type === "subscription") ? (
                          <button
                            className="edit-button"
                            onClick={() => { setProviderEditError(null); setEditingProviderRecord({ record: item, source: item.source, resourceType: group.resource_type }); }}
                          >
                            Editar
                          </button>
                        ) : null}
                        {(deletableResources[item.source] ?? []).includes(group.resource_type) && !(item.source === "toku" && group.resource_type === "subscription") ? (
                          <button
                            className="delete-button"
                            onClick={() => { setProviderDeleteError(null); setDeletingRecord({ record: item, source: item.source, resourceType: group.resource_type }); }}
                          >
                            Eliminar
                          </button>
                        ) : null}
                      </td>
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
  const availableStatuses = filterField === "status" ? statusValues : [];
  const isStatusFilter = filterField === "status";
  const filterControls = filterOptions.length ? (
    <section
      className="record-filters"
      aria-label={`Filtros ${activeSection?.label}`}
    >
      <div className="record-filters-copy">
        <p className="eyebrow">BÚSQUEDA</p>
        <strong>Filtrar registros</strong>
      </div>
      <label>
        Campo
        <select
          value={filterField}
          onChange={(event) => {
            setFilterField(event.target.value);
            setFilterQuery("");
            setRecordsOffset(0);
          }}
        >
          {filterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="record-filter-query">
        {isStatusFilter ? "Estado" : "Buscar"}
        {isStatusFilter ? (
          <select
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
          >
            <option value="">Todos los estados</option>
            {availableStatuses.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        ) : (
          <input
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
            placeholder={`Buscar por ${filterOptions.find((option) => option.value === filterField)?.label ?? "campo"}`}
          />
        )}
      </label>
      <button
        className="clear-filter-button"
        disabled={!filterQuery && filterField === filterOptions[0]?.value}
        onClick={() => {
          setFilterField(filterOptions[0]?.value ?? "");
          setFilterQuery("");
          setRecordsOffset(0);
        }}
      >
        Restablecer
      </button>
    </section>
  ) : null;
  const allSelected = (retryCharges?.items.length ?? 0) > 0 && retrySelected.size === (retryCharges?.items.length ?? 0);
  const vpRetryView = vpRetryOpen ? (
    <main className="app-shell">
      <div className="topbar">
        <div>
          <p className="eyebrow">VirtualPOS</p>
          <h1>Reintento de cargos</h1>
        </div>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 20 }}>
        <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".08em" }}>
          Desde
          <input type="date" value={retryDateFrom} onChange={(e) => setRetryDateFrom(e.target.value)} style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-1)", font: "inherit" }} />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".08em" }}>
          Hasta
          <input type="date" value={retryDateTo} onChange={(e) => setRetryDateTo(e.target.value)} style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-1)", font: "inherit" }} />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".08em" }}>
          Plataforma
          <select value={retryPlatform} onChange={(e) => setRetryPlatform(e.target.value as typeof retryPlatform)} style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-1)", font: "inherit" }}>
            <option value="all">Todas</option>
            <option value="virtualpos">VirtualPOS</option>
            <option value="virtualpos1">VirtualPOS 1</option>
            <option value="virtualpos2">VirtualPOS 2</option>
          </select>
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".08em", flex: "1 1 220px" }}>
          Motivo de rechazo
          <input
            list="retry-reason-options"
            value={retryReasonFilter}
            onChange={(e) => setRetryReasonFilter(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { setRetryOffset(0); loadRetryCharges(); } }}
            placeholder="Seleccionar o escribir motivo..."
            style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-input)", color: "var(--text-1)", font: "inherit" }}
          />
          <datalist id="retry-reason-options">
            {retryReasonOptions.map((r) => <option key={r} value={r} />)}
          </datalist>
        </label>
        <button className="primary-button" onClick={() => { setRetryOffset(0); loadRetryCharges(); }} disabled={retryLoading}>
          {retryLoading ? "Cargando..." : "Buscar"}
        </button>
        {retrySelected.size > 0 ? (
          <button className="primary-button" style={{ background: "var(--color-danger, #c0392b)" }} onClick={runBatchRetry} disabled={retrying}>
            {retrying ? "Reintentando..." : `Reintentar seleccionados (${retrySelected.size})`}
          </button>
        ) : null}
      </div>
      {retryError ? <p className="error-message">{retryError}</p> : null}
      {retryResults ? (() => {
        const failed = retryResults.results.filter((r) => !r.success);
        const errorGroups = new Map<string, number>();
        for (const r of failed) {
          const key = r.error ?? "Error desconocido";
          errorGroups.set(key, (errorGroups.get(key) ?? 0) + 1);
        }
        return (
          <div style={{ marginBottom: 20 }}>
            <div className={retryResults.succeeded > 0 && retryResults.failed === 0 ? "success-message" : retryResults.succeeded === 0 ? "error-message" : "success-message"} style={{ marginBottom: failed.length > 0 ? 12 : 0 }}>
              Reintento completado: <strong>{retryResults.succeeded}</strong> exitosos, <strong>{retryResults.failed}</strong> fallidos.
            </div>
            {failed.length > 0 && (
              <div className="panel" style={{ marginTop: 8, padding: "16px 20px" }}>
                <p style={{ margin: "0 0 10px", fontWeight: 700, fontSize: 13, color: "var(--text-2)" }}>Detalle de fallos</p>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
                  {[...errorGroups.entries()].map(([msg, count]) => (
                    <div key={msg} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "7px 10px", background: "var(--bg-muted)", borderRadius: 8 }}>
                      <span style={{ fontSize: 13, color: "var(--text-1)" }}>{msg}</span>
                      <span style={{ fontSize: 12, fontWeight: 800, color: "var(--text-3)", whiteSpace: "nowrap" }}>{count} cargo{count !== 1 ? "s" : ""}</span>
                    </div>
                  ))}
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "6px 8px", color: "var(--text-3)", fontWeight: 800, letterSpacing: ".08em", textTransform: "uppercase", borderBottom: "1px solid var(--border-subtle)" }}>ID externo</th>
                      <th style={{ textAlign: "left", padding: "6px 8px", color: "var(--text-3)", fontWeight: 800, letterSpacing: ".08em", textTransform: "uppercase", borderBottom: "1px solid var(--border-subtle)" }}>Monto</th>
                      <th style={{ textAlign: "left", padding: "6px 8px", color: "var(--text-3)", fontWeight: 800, letterSpacing: ".08em", textTransform: "uppercase", borderBottom: "1px solid var(--border-subtle)" }}>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {failed.map((r) => {
                      const charge = retrySnapshot.get(r.charge_id);
                      return (
                        <tr key={r.charge_id}>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-1)" }}>{charge?.external_id ?? r.charge_id}</td>
                          <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-2)" }}>{charge?.amount ? `${charge.currency ?? ""} ${Number(charge.amount).toLocaleString("es-CL")}` : "—"}</td>
                          <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-subtle)", color: "var(--error-text, #c0392b)" }}>{r.error ?? "Error desconocido"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })() : null}
      {retryCharges ? (
        <>
          <div className="table-wrap panel" style={{ marginBottom: 16 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input type="checkbox" checked={allSelected} onChange={(e) => {
                      if (e.target.checked) setRetrySelected(new Set(retryCharges.items.map((c) => c.id)));
                      else setRetrySelected(new Set());
                    }} />
                  </th>
                  <th>ID externo</th>
                  <th>Fuente</th>
                  <th>Suscripción</th>
                  <th>Cliente</th>
                  <th>Monto</th>
                  <th>Fecha</th>
                  <th>Motivo rechazo</th>
                </tr>
              </thead>
              <tbody>
                {retryCharges.items.map((charge) => (
                  <tr key={charge.id}>
                    <td>
                      <input type="checkbox" checked={retrySelected.has(charge.id)} onChange={(e) => {
                        setRetrySelected((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(charge.id);
                          else next.delete(charge.id);
                          return next;
                        });
                      }} />
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{charge.external_id}</td>
                    <td>{charge.source}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{charge.subscription_external_id ?? "—"}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{charge.client_external_id ?? "—"}</td>
                    <td>{charge.amount ? `${charge.currency ?? ""} ${Number(charge.amount).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{charge.charge_date ?? "—"}</td>
                    <td style={{ maxWidth: 260 }}>
                      {charge.rejection_reason ? (
                        <span>
                          {charge.rejection_code ? <code style={{ fontSize: 11, marginRight: 5, color: "var(--text-3)" }}>[{charge.rejection_code}]</code> : null}
                          {charge.rejection_doc_url ? (
                            <a href={charge.rejection_doc_url} target="_blank" rel="noreferrer" title={charge.rejection_reason} style={{ color: "var(--link-color)", textDecoration: "none", fontSize: 13 }}>
                              {charge.rejection_reason}
                            </a>
                          ) : (
                            <span style={{ fontSize: 13 }} title={charge.rejection_reason}>{charge.rejection_reason}</span>
                          )}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button className="primary-button" disabled={retryOffset === 0} onClick={() => { setRetryOffset(Math.max(0, retryOffset - 50)); loadRetryCharges(); }}>← Anterior</button>
            <span style={{ fontSize: 13, color: "var(--text-3)" }}>
              {retryOffset + 1}–{Math.min(retryOffset + 50, retryCharges.total)} de {retryCharges.total}
            </span>
            <button className="primary-button" disabled={retryOffset + 50 >= retryCharges.total} onClick={() => { setRetryOffset(retryOffset + 50); loadRetryCharges(); }}>Siguiente →</button>
          </div>
        </>
      ) : !retryLoading ? (
        <p className="muted-copy">Usa los filtros y haz clic en "Buscar" para cargar los cargos rechazados.</p>
      ) : null}
    </main>
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
      {activeSection.source === "virtualpos" ? (
        <div className="vp-platform-filter">
          {(["all", "virtualpos1", "virtualpos2"] as const).map((p) => (
            <button
              key={p}
              className={`vp-platform-btn${vpPlatform === p ? " active" : ""}`}
              onClick={() => { setVpPlatform(p); setRecordsOffset(0); }}
            >
              {p === "all" ? "Todas" : p === "virtualpos1" ? "VP 1" : "VP 2"}
            </button>
          ))}
        </div>
      ) : null}
      <section className="panel provider-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SOURCE RECORDS</p>
            <h3>Payloads saneados almacenados localmente</h3>
          </div>
          <span aria-live="polite">{loading ? "Cargando" : `${records.total} registros`}</span>
        </div>
        {activeSection.source === "virtualpos" && activeSection.resource === "client" ? (
          <button className="new-client-button" onClick={() => setCreatingClient(true)}>+ Nuevo cliente</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "plan" ? (
          <button className="new-client-button" onClick={() => { setPlanFormError(null); setPlanFieldErrors({}); setPlanSaveNotice(null); setCreatingPlan(true); }}>+ Nuevo plan</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "subscription" ? (
          <button className="new-client-button" onClick={() => { setSubscriptionFormError(null); setSubscriptionFieldErrors({}); setSubscriptionSaveNotice(null); setCreatingSubscription(true); }}>+ Nueva suscripción</button>
        ) : null}
        {clientSaveNotice ? <p className="success-message" role="status">{clientSaveNotice}</p> : null}
        {planSaveNotice ? <p className="success-message" role="status">{planSaveNotice}</p> : null}
        {subscriptionSaveNotice ? <p className="success-message" role="status">{subscriptionSaveNotice}</p> : null}
        {chargeSaveNotice ? <p className="success-message" role="status">{chargeSaveNotice}</p> : null}
        {error ? <p className="error-message">{error}</p> : null}
        {!loading && !error && records.items.length === 0 ? (
          <p>Sin registros sincronizados para este recurso.</p>
        ) : null}
        {records.items.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((column) => {
                    const sortable = Boolean(activeSection && filterFieldForColumn(activeSection.source, activeSection.resource, column.label));
                    const activeSort = sortColumn === column.label;
                    return (
                      <th
                        key={column.label}
                        aria-sort={activeSort ? (sortDirection === "asc" ? "ascending" : "descending") : undefined}
                      >
                        {sortable ? (
                          <button
                            className={`table-sort-button${activeSort ? " active" : ""}`}
                            title={`Ordenar por ${column.label}${activeSort ? " en sentido inverso" : ""}`}
                            onClick={() => toggleColumnSort(column)}
                          >
                            {column.label}
                            <span className="table-sort-indicator" aria-hidden="true">
                              {activeSort ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
                            </span>
                          </button>
                        ) : column.label}
                      </th>
                    );
                  })}
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
                            <div className="table-actions-group">
                              <button
                                className="cancel-subscription-button cancel-subscription-button-table"
                                onClick={() => setCancelingSubscription(record)}
                              >
                                Cancelar Sub
                              </button>
                              <button
                                className="create-charge-button create-charge-button-table"
                                onClick={() => { setChargeFormError(null); setChargeFieldErrors({}); setChargeSaveNotice(null); setCreatingCharge(record); }}
                              >
                                + Cargo
                              </button>
                            </div>
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
                          activeSection.resource === "charge" &&
                          column.label === "Acciones" ? (
                          <div className="table-actions-group">
                            {isPendingCharge(record) ? (
                              <button
                                className="cancel-charge-button"
                                onClick={() => { setCancelChargeError(null); setCancelingCharge(record); }}
                              >
                                Cancelar
                              </button>
                            ) : isRejectedCharge(record) ? (
                              <button
                                className="retry-charge-button"
                                onClick={() => { setRetryChargeError(null); setRetryingCharge(record); }}
                              >
                                Reintentar
                              </button>
                            ) : null}
                          </div>
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
                        ) : column.label === "Acciones" ? (
                          <div className="table-actions">
                            {(providerEditFields[activeSection.source]?.[activeSection.resource] ?? []).length > 0 ? (
                              <button
                                className="edit-button edit-button-table"
                                onClick={() => setEditingProviderRecord({ record, source: activeSection.source, resourceType: activeSection.resource })}
                              >
                                Editar
                              </button>
                            ) : null}
                            <button
                              className="delete-button delete-button-table"
                              onClick={() => setDeletingRecord({ record, source: activeSection.source, resourceType: activeSection.resource })}
                            >
                              Eliminar
                            </button>
                          </div>
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
        {records.items.length < records.total ? (
          <div className="table-load-more">
            <span>Mostrando {records.items.length.toLocaleString("es-CL")} de {records.total.toLocaleString("es-CL")}</span>
            <button disabled={loading} onClick={() => setRecordsOffset((offset) => offset + RECORDS_PAGE_SIZE)}>
              {loading ? "Cargando..." : "Ver más"}
            </button>
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
            Operación consolidada,
            <br />
            desde todos los canales.
          </h2>
        </div>
        {generalData ? (
          <div className="dashboard-controls">
            <div className="mode-switch">
              <button className={generalMode === "count" ? "active" : ""} onClick={() => setGeneralMode("count")}>Cantidad</button>
              <button className={generalMode === "amount" ? "active" : ""} onClick={() => setGeneralMode("amount")}>Monto</button>
            </div>
            {generalData.years.length ? (
              <select aria-label="Año dashboard general" value={generalYear ?? defaultYear(generalData.years) ?? generalData.years[0]} onChange={(event) => setGeneralYear(Number(event.target.value))}>
                {generalData.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
              </select>
            ) : null}
            <button className="sync-btn sync-btn-secondary" onClick={() => setReportScope("general")}>Generar reporte</button>
          </div>
        ) : (
          <p className="sync-copy">KPIs y actividad mensual calculados desde las entidades canónicas y TCH.</p>
        )}
      </section>
      {error ? <p className="error-message">{error}</p> : null}
      {generalView === "subscriptions" ? (
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES CONSOLIDADAS</p><h3>{generalSubscriptions?.total.toLocaleString("es-CL") ?? ""} suscripciones</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de suscripciones" value={generalSubscriptionFilter} onChange={(event) => { setGeneralSubscriptionFilter(event.target.value as typeof generalSubscriptionFilter); setGeneralSubscriptionOffset(0); }}><option value="all">Todos los campos</option><option value="id">ID</option><option value="rut">RUT</option><option value="client">Cliente</option><option value="platform">Plataforma</option><option value="status">Estado</option></select><input aria-label="Buscar suscripción consolidada" placeholder="Buscar suscripciones" value={generalSubscriptionQuery} onChange={(event) => { setGeneralSubscriptionQuery(event.target.value); setGeneralSubscriptionOffset(0); }} /></div></div>
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Cliente</th><th>RUT</th><th>Plataforma</th><th>Estado</th><th>Inicio</th><th>Término</th><th>Monto</th></tr></thead><tbody>{(generalSubscriptions?.items ?? []).map((subscription) => <tr key={`${subscription.platform}-${subscription.id}`}><td>{subscription.id}</td><td>{subscription.client || "—"}</td><td>{subscription.rut || "—"}</td><td>{subscription.platform}</td><td>{subscription.status || "—"}</td><td>{subscription.started_at ?? "—"}</td><td>{subscription.ended_at ?? "—"}</td><td>{subscription.amount ? `${subscription.currency ?? ""} $${Number(subscription.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{(generalSubscriptions?.items ?? []).length === 0 ? <tr><td colSpan={8}>Sin suscripciones.</td></tr> : null}</tbody></table></div>{generalSubscriptions && generalSubscriptions.total > generalSubscriptions.limit ? <div className="pagination"><button disabled={generalSubscriptionOffset === 0} onClick={() => setGeneralSubscriptionOffset((offset) => Math.max(0, offset - generalSubscriptions.limit))}>← Anterior</button><span>{generalSubscriptionOffset + 1}-{Math.min(generalSubscriptionOffset + generalSubscriptions.items.length, generalSubscriptions.total)} de {generalSubscriptions.total.toLocaleString("es-CL")}</span><button disabled={generalSubscriptionOffset + generalSubscriptions.limit >= generalSubscriptions.total} onClick={() => setGeneralSubscriptionOffset((offset) => offset + generalSubscriptions.limit)}>Siguiente →</button></div> : null}
        </section>
      ) : generalView === "clients" ? (
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">CLIENTES CONSOLIDADOS</p><h3>{generalClients?.total.toLocaleString("es-CL") ?? ""} clientes por RUT</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de clientes" value={generalClientFilter} onChange={(event) => { setGeneralClientFilter(event.target.value as typeof generalClientFilter); setGeneralClientOffset(0); }}><option value="all">Todos los campos</option><option value="rut">RUT</option><option value="name">Nombre</option><option value="last_name">Apellido</option><option value="platform">Plataforma</option><option value="email">Correo</option><option value="phone">Teléfono</option></select><input aria-label="Buscar cliente consolidado" placeholder="Buscar clientes" value={generalClientQuery} onChange={(event) => { setGeneralClientQuery(event.target.value); setGeneralClientOffset(0); }} /></div></div>
          {generalClientDetail ? (
            <div className="record-detail"><button onClick={() => setGeneralClientDetail(null)}>← Volver a clientes</button><h3>Ficha general: {generalClientDetail.rut}</h3>{(["clients", "subscriptions", "charges", "transactions"] as const).map((section) => <div key={section}><h4>{section === "clients" ? "IDs de cliente" : section === "subscriptions" ? "Suscripciones" : section === "charges" ? "Cargos" : "Transacciones"}</h4><div className="table-wrap"><table><thead><tr><th>Portal</th><th>ID interno</th><th>ID origen</th><th>Estado</th><th>Monto</th></tr></thead><tbody>{generalClientDetail[section].map((item) => <tr key={`${item.portal}-${item.external_id}`}><td>{item.portal}</td><td>{("id_cliente" in item ? item.id_cliente : "id_subscription" in item ? item.id_subscription : "id_cargo" in item ? item.id_cargo : item.id_transaccion)}</td><td>{item.external_id}</td><td>{"status" in item ? item.status : "—"}</td><td>{"amount" in item && item.amount ? `$${Number(item.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{generalClientDetail[section].length === 0 ? <tr><td colSpan={5}>Sin registros relacionados.</td></tr> : null}</tbody></table></div></div>)}</div>
          ) : <><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre completo</th><th>Plataforma de origen</th><th>Suscripciones activas</th></tr></thead><tbody>{(generalClients?.items ?? []).map((client) => <tr key={client.rut}><td><button className="record-link" onClick={() => getJson<GeneralClientDetail>(`/api/v1/staging/dashboard/general/clients/${encodeURIComponent(client.rut)}`).then(setGeneralClientDetail).catch((err: unknown) => setError(friendlyError(err, "No se pudo cargar la ficha general.")))}>{client.rut}</button></td><td>{client.name || "—"}</td><td>{client.origins.join(" · ")}</td><td>{client.active_origins.join(" · ") || "—"}</td></tr>)}{(generalClients?.items ?? []).length === 0 ? <tr><td colSpan={4}>Sin clientes con RUT.</td></tr> : null}</tbody></table></div>{generalClients && generalClients.total > generalClients.limit ? <div className="pagination"><button disabled={generalClientOffset === 0} onClick={() => setGeneralClientOffset((offset) => Math.max(0, offset - generalClients.limit))}>← Anterior</button><span>{generalClientOffset + 1}-{Math.min(generalClientOffset + generalClients.items.length, generalClients.total)} de {generalClients.total.toLocaleString("es-CL")}</span><button disabled={generalClientOffset + generalClients.limit >= generalClients.total} onClick={() => setGeneralClientOffset((offset) => offset + generalClients.limit)}>Siguiente →</button></div> : null}</>}
        </section>
      ) : generalData ? (
        <>
          <section className="metrics provider-metrics" aria-label="Métricas generales">
            <Metric label="Clientes" value={generalData.clients} tone="blue" />
            <Metric label="Suscripciones vigentes" value={generalData.subscriptions.active} tone="green" amount={generalData.subscriptions.amount} mode={generalMode} />
            <Metric label="Transacciones" value={generalData.transactions.total} tone="violet" amount={generalData.transactions.amount} mode={generalMode} />
            <KpiCard label="Monto recaudado" value={`$${generalData.transactions.amount.toLocaleString("es-CL")}`} caption="Transacciones aceptadas" tone="gold" />
          </section>
          <section className="metrics kpi-metrics" aria-label="KPIs generales">
            <KpiCard label="Aceptadas" value={generalData.transactions.accepted.toLocaleString("es-CL")} caption="Transacciones cobradas" tone="green" />
            <KpiCard label="Rechazadas" value={generalData.transactions.rejected.toLocaleString("es-CL")} caption="Transacciones fallidas" tone="orange" />
            <KpiCard label="Tasa de rechazo" value={`${generalData.transactions.rejection_rate_pct}%`} caption="Rechazadas / total" tone={generalData.transactions.rejection_rate_pct > 20 ? "orange" : "blue"} />
          </section>
          <section className="extended-charts">
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">TRANSACCIONES</p><h3>Estado mensual consolidado</h3></div></div>
              <MonthlyStatusChart data={generalData.transactions_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Activaciones mensuales por canal</h3></div></div>
              <MonthlyStatusChart data={generalData.activations_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel" style={{ gridColumn: "1 / -1" }}>
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Bajas mensuales por canal</h3></div></div>
              <MonthlyStatusChart data={generalData.cancellations_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading">
                <div><p className="eyebrow">RECAUDACIÓN</p><h3>Deudas mensuales por canal</h3></div>
                <div className="mode-switch">
                  {(["todas", "pagada", "rechazada"] as const).map(f => (
                    <button key={f} className={debtFilter === f ? "active" : ""} onClick={() => setDebtFilter(f)}>
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <MonthlyStatusChart data={applyChargeFilter(generalData.debts_monthly, debtFilter)} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading">
                <div><p className="eyebrow">RECAUDACIÓN</p><h3>Transacciones por canal</h3></div>
                <div className="mode-switch">
                  {(["todas", "pagada", "rechazada"] as const).map(f => (
                    <button key={f} className={transFilter === f ? "active" : ""} onClick={() => setTransFilter(f)}>
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <MonthlyStatusChart data={applyChargeFilter(generalData.transactions_effective_monthly, transFilter)} mode={generalMode} year={generalYear} />
            </article>
          </section>
          <section className="source-summary">
            {generalData.channels.map((channel) => {
              const staging = summary.sources.find((source) => source.source === channel.source.toLowerCase());
              const lastSync = staging?.last_sync;
              return (
                <article className="panel channel-summary-card" key={channel.source}>
                  <div className="panel-heading">
                    <div><p className="eyebrow">{channel.source.toUpperCase()}</p><h3>{channel.active_subscriptions.toLocaleString("es-CL")} suscripciones vigentes</h3></div>
                    {lastSync ? <span className={`status-pill ${lastSync.status === "completed" ? "" : "status-attention"}`}>{lastSync.status}</span> : null}
                  </div>
                  <div className="channel-summary-details">
                    <div><span>Operación</span><strong>{channel.clients.toLocaleString("es-CL")} clientes · {channel.accepted.toLocaleString("es-CL")} aceptadas</strong></div>
                    <div><span>Recaudación</span><strong>${channel.amount.toLocaleString("es-CL")}</strong></div>
                    <div><span>{staging ? "Carga staging" : "Carga local"}</span><strong>{staging ? `${staging.records.toLocaleString("es-CL")} registros` : "Histórico TCH integrado"}</strong></div>
                    <div><span>Consolidación</span><strong>Entidades canónicas disponibles</strong></div>
                  </div>
                  {staging ? <p className="resource-copy">{Object.entries(staging.resources).map(([resource, count]) => `${resource}: ${count}`).join(" · ")}</p> : null}
                  {lastSync?.finished_at ? <p className="channel-summary-sync">Última carga: {new Date(lastSync.finished_at).toLocaleString("es-CL")} · {lastSync.records_processed.toLocaleString("es-CL")} procesados</p> : null}
                </article>
              );
            })}
          </section>
        </>
      ) : (
        <p className="muted-copy">Cargando indicadores consolidados...</p>
      )}
      <section className="etl-panel">
        <div className="etl-panel-heading">
          <div>
            <p className="eyebrow">CONSOLIDACIÓN</p>
            <h3>Base de datos unificada</h3>
          </div>
          <button
            className={`sync-btn ${etlRunning ? "syncing" : ""}`}
            disabled={etlRunning}
            onClick={runFullSync}
          >
            {etlRunning
              ? lastEtlRun?.phase
                ? `Sincronizando ${lastEtlRun.phase.replace("sync_", "")}…`
                : "Procesando…"
              : "↻ Sync completo"}
          </button>
          <button
            className="sync-btn sync-btn-secondary"
            disabled={etlRunning}
            onClick={runEtl}
            title="Solo ETL: rematerializa staging → canonical sin re-sync desde APIs"
          >
            Solo ETL
          </button>
        </div>
        {etlError ? <p className="error-message">{etlError}</p> : null}
        {lastEtlRun ? (
          <div className="etl-status">
            <span className={`status-pill ${lastEtlRun.status === "completed" ? "" : lastEtlRun.status === "failed" ? "status-attention" : ""}`}>
              {lastEtlRun.status}
            </span>
            {lastEtlRun.phase && lastEtlRun.status === "running" ? (
              <span className="etl-phase-badge">{lastEtlRun.phase}</span>
            ) : null}
            <span className="muted-copy">
              {lastEtlRun.records_upserted.toLocaleString()} registros
              {lastEtlRun.finished_at
                ? ` · ${new Date(lastEtlRun.finished_at).toLocaleString("es-CL")}`
                : " · en progreso…"}
            </span>
            {lastEtlRun.error_message ? (
              <p className="error-message">{lastEtlRun.error_message}</p>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
  const createRequiredFields = new Set(["first_name", "email", "social_id", "social_id_type"]);
  const createDefaultValues: Record<string, string> = { status: "ACTIVO", type: "PERSONA", social_id_type: "1" };
  const clientEditDialog = editingClient || creatingClient ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form className="edit-dialog" aria-modal="true" aria-label={creatingClient ? "Crear cliente VirtualPOS" : "Editar cliente VirtualPOS"} noValidate onSubmit={creatingClient ? createVirtualPOSClient : saveVirtualPOSClient}>
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / {creatingClient ? "CREACIÓN" : "EDICIÓN"}</p>
            <h3>{creatingClient ? "Nuevo cliente" : "Editar cliente"}</h3>
          </div>
          {!creatingClient && editingClient ? <span>{text(editingClient.payload.uuid, editingClient.external_id)}</span> : null}
        </div>
        <p className="edit-dialog-note">
          {creatingClient
            ? "Los campos marcados con * son obligatorios. El cliente se creará en VirtualPOS y en la base de datos local."
            : "Los cambios se aplican mediante la API interna. VirtualPOS debe estar habilitado localmente para completar el guardado."}
        </p>
        {creatingClient && (
          <div className="vp-account-selector">
            <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
            <div className="vp-account-selector-buttons">
              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos1")}>
                Cuenta 1
              </button>
              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos2")}>
                Cuenta 2
              </button>
            </div>
          </div>
        )}
        <div className="edit-form-grid">
          {virtualPosClientEditFields.map((field) => {
            const isRequired = creatingClient && createRequiredFields.has(field.name);
            const hasError = Boolean(clientFieldErrors[field.name]);
            const defaultVal = creatingClient
              ? (createDefaultValues[field.name] ?? "")
              : (field.name === "social_id_type" ? documentType(editingClient!.payload[field.name]) : text(editingClient!.payload[field.name], ""));
            return (
              <label className={hasError ? "field-error" : ""} key={field.name}>
                {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                {field.options ? (
                  <select
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    name={field.name}
                    defaultValue={defaultVal}
                  >
                    {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                ) : (
                  <input
                    name={field.name}
                    type={field.type ?? "text"}
                    defaultValue={defaultVal}
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    placeholder={field.name === "social_id" ? (creatingClient ? "Ej: 12345678-9" : undefined) : undefined}
                  />
                )}
                {hasError ? <span className="field-error-message">{clientFieldErrors[field.name]}</span> : null}
              </label>
            );
          })}
          <label className="edit-form-wide">
            Nota privada
            <textarea name="private_note" defaultValue={creatingClient ? "" : text(editingClient!.payload.private_note, "")} />
          </label>
        </div>
        {clientFormError ? <p className="error-message form-error">{clientFormError}</p> : null}
        <div className="edit-dialog-actions">
          <button type="submit" className="save-button" disabled={savingClient}>
            {savingClient ? "Guardando..." : creatingClient ? "Crear cliente" : "Guardar cambios"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setEditingClient(null); setCreatingClient(false); }}>
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
            <h3>¿Estás seguro de cancelar esta suscripción?</h3>
          </div>
          <span>{text(cancelingSubscription.payload.id, cancelingSubscription.external_id)}</span>
        </div>
        <p className="edit-dialog-note">
          Esta acción cancelará la suscripción en VirtualPOS (DELETE /v3/suscription/…). Los cargos futuros se detendrán y no se puede deshacer.
        </p>
        {cancelSubscriptionError && <p className="edit-dialog-error">{cancelSubscriptionError}</p>}
        <div className="edit-dialog-actions">
          <button
            type="button"
            className="cancel-subscription-button"
            disabled={savingCancelSubscription}
            onClick={() => void cancelVirtualPOSSubscription()}
          >
            {savingCancelSubscription ? "Cancelando..." : "Confirmar cancelación"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setCancelingSubscription(null); setCancelSubscriptionError(null); }}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null;
  const isTokuWritable = editingProviderRecord?.source === "toku" && editingProviderRecord?.resourceType === "customer";
  const isPaykuWritable = editingProviderRecord?.source === "payku" && editingProviderRecord?.resourceType === "client";
  const isProviderWritable = isTokuWritable || isPaykuWritable;
  const providerEditDialog = editingProviderRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form
        className="edit-dialog"
        aria-modal="true"
        aria-label={`Editar ${resourceTitle(editingProviderRecord.resourceType)}`}
        noValidate
        onSubmit={isProviderWritable ? saveProviderEdit : (e) => e.preventDefault()}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(editingProviderRecord.source).toUpperCase()} / EDICIÓN
            </p>
            <h3>Editar {resourceTitle(editingProviderRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(editingProviderRecord.record.payload.id, editingProviderRecord.record.external_id)}
          </span>
        </div>
        {!isProviderWritable ? (
          <p className="edit-dialog-note">
            Formulario visual. El guardado remoto permanece deshabilitado mientras{" "}
            {title(editingProviderRecord.source)} opere en modo solo lectura.
          </p>
        ) : null}
        <div className="edit-form-grid">
          {(providerEditFields[editingProviderRecord.source]?.[editingProviderRecord.resourceType] ?? []).map(
            (field) => (
              <label key={field.name}>
                {field.label}
                <input
                  name={field.name}
                  type={field.type ?? "text"}
                  defaultValue={text(editingProviderRecord.record.payload[field.name], "")}
                />
              </label>
            ),
          )}
        </div>
        {providerEditError ? <p className="error-message form-error">{providerEditError}</p> : null}
        <div className="edit-dialog-actions">
          {isProviderWritable ? (
            <button type="submit" className="save-button" disabled={savingProviderEdit}>
              {savingProviderEdit ? "Guardando..." : "Guardar cambios"}
            </button>
          ) : (
            <button type="button" className="save-button" disabled title="Guardado remoto no habilitado">
              Guardar cambios
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setEditingProviderRecord(null)}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null;
  const providerDeleteDialog = deletingRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section
        className="edit-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Eliminar ${resourceTitle(deletingRecord.resourceType)}`}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(deletingRecord.source).toUpperCase()} / ELIMINACIÓN
            </p>
            <h3>Eliminar {resourceTitle(deletingRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(deletingRecord.record.payload.id, deletingRecord.record.external_id)}
          </span>
        </div>
        <p className="edit-dialog-note">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription"))
            ? `Se enviará DELETE ${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)} a ${title(deletingRecord.source)}. Esta acción no se puede deshacer.`
            : `Esta acción utilizará DELETE \`${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)}\` cuando se habilite la escritura. Actualmente ${title(deletingRecord.source)} permanece en modo solo lectura.`}
        </p>
        {providerDeleteError ? <p className="error-message form-error">{providerDeleteError}</p> : null}
        <div className="edit-dialog-actions">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription")) ? (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled={savingProviderDelete}
              onClick={() => void confirmProviderDelete()}
            >
              {savingProviderDelete ? "Eliminando..." : "Confirmar eliminación"}
            </button>
          ) : (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled
              title="Eliminación remota no habilitada"
            >
              Confirmar eliminación
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setDeletingRecord(null)}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null;
  const tchContent = tchView ? (
    tchLoading ? (
      <main className="app-shell"><p className="muted-copy">Cargando datos TCH...</p></main>
    ) : tchError ? (
      <main className="app-shell"><p className="error-message">{tchError}</p></main>
    ) : tchView === "summary" && tchSummary ? (
      <main className="app-shell channel-dashboard-page">
        <p className="eyebrow">TCH / CANAL</p>
        <header className="channel-hero">
          <div>
            <h2>Resumen operativo</h2>
            <p>Datos cargados desde reportes Excel mensuales vía ETL.</p>
          </div>
          <div className="channel-hero-controls">
            <div className="dashboard-controls">
              <div className="mode-switch">
                <button className={tchMode === "count" ? "active" : ""} onClick={() => setTchMode("count")}>Cantidad</button>
                <button className={tchMode === "amount" ? "active" : ""} onClick={() => setTchMode("amount")}>Monto</button>
              </div>
              {tchSummary.years.length ? (
                <select aria-label="Año TCH" value={tchYear ?? defaultYear(tchSummary.years) ?? tchSummary.years[0]} onChange={(event) => setTchYear(Number(event.target.value))}>
                  {tchSummary.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
                </select>
              ) : null}
              <button className="sync-btn sync-btn-secondary" onClick={() => setReportScope("tch")}>Generar reporte</button>
            </div>
            {tchSummary.ultimo_etl.started_at ? (
              <>
              <div className={`sync-state ${tchSummary.ultimo_etl.status === "completed" ? "ready" : "attention"}`}>
                <span />{tchSummary.ultimo_etl.status ?? "Sin ETL"}
              </div>
              <p className="muted-copy" style={{ fontSize: "0.78rem" }}>
                Último ETL: {tchSummary.ultimo_etl.started_at?.slice(0, 10)} · {(tchSummary.ultimo_etl.records_upserted ?? 0).toLocaleString("es-CL")} registros
              </p>
              </>
            ) : null}
          </div>
        </header>
        <section className="metrics provider-metrics" aria-label="KPIs TCH">
          <Metric label="Suscripciones vigentes" value={tchSummary.suscripciones.vigentes} tone="green" amount={tchSummary.suscripciones.monto_vigentes} mode={tchMode} />
          <Metric label="Suscripciones eliminadas" value={tchSummary.suscripciones.eliminadas} tone="orange" amount={tchSummary.suscripciones.monto_eliminadas} mode={tchMode} />
          <Metric label="Total suscripciones" value={tchSummary.suscripciones.total} tone="blue" amount={tchSummary.suscripciones.monto_total} mode={tchMode} />
          <Metric label="Total transacciones" value={tchSummary.transacciones.total} tone="violet" amount={tchSummary.transacciones.monto} mode={tchMode} />
        </section>
        <section className="metrics kpi-metrics" aria-label="KPIs financieros TCH">
          <KpiCard
            label="MRR"
            value={`$${tchSummary.kpis.mrr.toLocaleString("es-CL")}`}
            caption="Ingreso mensual recurrente activo"
            tone="green"
          />
          <KpiCard
            label="ARPU"
            value={`$${tchSummary.kpis.arpu.toLocaleString("es-CL")}`}
            caption={`${tchSummary.kpis.active_clients} cliente${tchSummary.kpis.active_clients !== 1 ? "s" : ""} con subs activas`}
            tone="blue"
          />
          <KpiCard
            label="Churn mensual"
            value={`${tchSummary.kpis.churn_rate}%`}
            caption={`${tchSummary.kpis.active_subscribers} subs activas · ${tchSummary.suscripciones.total} total`}
            tone="orange"
          />
          <KpiCard
            label="LTV estimado"
            value={tchSummary.kpis.ltv > 0 ? `$${tchSummary.kpis.ltv.toLocaleString("es-CL")}` : "—"}
            caption="ARPU / churn rate"
            tone="violet"
          />
        </section>
        <section className="metrics kpi-metrics" aria-label="KPIs transacciones TCH">
          <KpiCard label="Aceptadas" value={tchSummary.transacciones.aceptadas.toLocaleString("es-CL")} tone="green" caption="Transacciones cobradas" />
          <KpiCard label="Rechazadas" value={tchSummary.transacciones.rechazadas.toLocaleString("es-CL")} tone="orange" caption="Transacciones fallidas" />
          <KpiCard label="Tasa de rechazo" value={`${tchSummary.transacciones.tasa_rechazo_pct}%`} tone={tchSummary.transacciones.tasa_rechazo_pct > 20 ? "orange" : "blue"} caption="Rechazadas / total" />
        </section>
        <section className="extended-charts">
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Resultado mensual</h3></div></div>
            <MonthlyStatusChart data={tchSummary.transacciones_mensuales} mode={tchMode} year={tchYear} />
          </article>
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas mensuales</h3></div></div>
            <MonthlyStatusChart data={tchSummary.activaciones_mensuales} mode={tchMode} year={tchYear} />
          </article>
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Bajas mensuales</h3></div></div>
            <MonthlyStatusChart data={tchSummary.bajas_mensuales} mode={tchMode} year={tchYear} />
          </article>
        </section>
        <section className="panel channel-resources">
          <div><p className="eyebrow">EXPLORAR TCH</p><h3>Vistas disponibles</h3></div>
          <div>
            <button onClick={() => showTch("suscripciones")}>Suscripciones<span>{tchSummary.suscripciones.total}</span></button>
            <button onClick={() => showTch("transacciones")}>Transacciones<span>{tchSummary.transacciones.total}</span></button>
          </div>
        </section>
      </main>
    ) : tchView === "cliente-detalle" && tchClienteDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("clientes")}>← Clientes TCH</button>
        <p className="eyebrow">TCH / CLIENTE</p>
        <header className="detail-header"><div><h2>{[tchClienteDetail.nombre, tchClienteDetail.apellido].filter(Boolean).join(" ") || "Cliente TCH"}</h2><p>{tchClienteDetail.rut}</p></div></header>
        <section className="detail-grid"><article className="panel"><h3>Datos personales</h3><dl><dt>RUT</dt><dd>{tchClienteDetail.rut}</dd><dt>Fecha de nacimiento</dt><dd>{tchClienteDetail.fecha_nacimiento ?? "—"}</dd><dt>Profesión</dt><dd>{tchClienteDetail.profesion ?? "—"}</dd><dt>Tipo de socio</dt><dd>{tchClienteDetail.tipo_socio ?? "—"}</dd></dl></article><article className="panel"><h3>Contacto</h3><dl><dt>Email</dt><dd>{tchClienteDetail.email ?? "—"}</dd><dt>Teléfono</dt><dd>{tchClienteDetail.telefono ?? "—"}</dd><dt>Dirección</dt><dd>{tchClienteDetail.direccion ?? "—"}</dd><dt>Comuna</dt><dd>{tchClienteDetail.comuna ?? "—"}</dd><dt>Ciudad</dt><dd>{tchClienteDetail.ciudad ?? "—"}</dd></dl></article><article className="panel"><h3>Mandatos</h3><p className="metric-value">{(tchClienteDetail.suscripciones ?? []).length.toLocaleString("es-CL")}</p><p className="muted-copy">Suscripciones TCH asociadas</p></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Mandatos asociados</h3></div></div><div className="table-wrap"><table><thead><tr><th>Ficha</th><th>Inicio</th><th>Fin</th><th>Monto</th><th>Estado</th></tr></thead><tbody>{(tchClienteDetail.suscripciones ?? []).map((s) => <tr key={s.id}><td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td><td>{s.fecha_activacion ?? "—"}</td><td>{s.fecha_fin ?? "—"}</td><td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td><td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "suscripcion-detalle" && tchSuscripcionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("suscripciones")}>← Suscripciones TCH</button>
        <p className="eyebrow">TCH / SUSCRIPCIÓN</p>
        <header className="detail-header"><div><h2>Ficha {tchSuscripcionDetail.numero_ficha}</h2><p>Mandato físico e historial de cargos.</p></div><span className={`status-pill${tchSuscripcionDetail.estado === "VIGENTE" ? "" : " status-attention"}`}>{tchSuscripcionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Mandato</h3><dl><dt>Inicio</dt><dd>{tchSuscripcionDetail.fecha_activacion ?? "—"}</dd><dt>Fin</dt><dd>{tchSuscripcionDetail.fecha_fin ?? "—"}</dd><dt>Motivo</dt><dd>{tchSuscripcionDetail.razon_baja ?? "—"}</dd><dt>Monto (CLP)</dt><dd>{(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto) ? `$${Number(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Banco</dt><dd>{tchSuscripcionDetail.banco_nombre ?? "—"}</dd><dt>RUT cliente</dt><dd>{tchSuscripcionDetail.cliente_rut ?? "—"}</dd></dl></article><article className="panel"><h3>Captación</h3><dl><dt>Origen</dt><dd>{tchSuscripcionDetail.origen ?? "—"}</dd><dt>Centro de costo</dt><dd>{tchSuscripcionDetail.centro_costo ?? "—"}</dd><dt>Captador</dt><dd>{tchSuscripcionDetail.captador ?? "—"}</dd><dt>Mandato</dt><dd>{tchSuscripcionDetail.numero_mandato ?? "—"}</dd><dt>Tipo de cuenta</dt><dd>{tchSuscripcionDetail.tipo_cuenta ?? "—"}</dd></dl></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Historial</h3></div></div><div className="table-wrap"><table><thead><tr><th>Período</th><th>Monto</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{tchSuscripcionDetail.transacciones.map((t) => <tr key={t.id}><td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.periodo ?? "—"}</button></td><td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td><td>{t.fecha_cargo ?? "—"}</td><td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "transaccion-detalle" && tchTransaccionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("transacciones")}>← Transacciones TCH</button>
        <p className="eyebrow">TCH / TRANSACCIÓN</p>
        <header className="detail-header"><div><h2>Cargo {tchTransaccionDetail.periodo ?? "sin período"}</h2><p>Ficha {tchTransaccionDetail.numero_ficha}</p></div><span className={`status-pill${tchTransaccionDetail.estado === "ACEPTADA" ? "" : " status-attention"}`}>{tchTransaccionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Detalle del cargo</h3><dl><dt>Monto</dt><dd>{tchTransaccionDetail.monto ? `$${Number(tchTransaccionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Fecha de cargo</dt><dd>{tchTransaccionDetail.fecha_cargo ?? "—"}</dd><dt>Cuota</dt><dd>{tchTransaccionDetail.numero_cuota ?? "—"}</dd><dt>Entidad</dt><dd>{tchTransaccionDetail.entidad_recaudadora ?? "—"}</dd><dt>Motivo</dt><dd>{tchTransaccionDetail.razon_rechazo ?? "—"}</dd></dl></article><article className="panel"><h3>Suscripción</h3>{tchTransaccionDetail.suscripcion ? <dl><dt>Ficha</dt><dd><button className="record-link" onClick={() => showTchSuscripcion(tchTransaccionDetail.numero_ficha)}>{tchTransaccionDetail.numero_ficha}</button></dd><dt>RUT cliente</dt><dd>{tchTransaccionDetail.suscripcion.cliente_rut ?? "—"}</dd><dt>Banco</dt><dd>{tchTransaccionDetail.suscripcion.banco_nombre ?? "—"}</dd><dt>Inicio</dt><dd>{tchTransaccionDetail.suscripcion.fecha_activacion ?? "—"}</dd></dl> : <p className="muted-copy">No hay suscripción local asociada.</p>}</article></section>
      </main>
    ) : tchView === "clientes" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / CLIENTES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}><div><h2>Clientes TCH</h2><p>Socios asociados a mandatos físicos.</p></div><div className="dashboard-controls"><input aria-label="Buscar cliente" placeholder="Buscar por nombre" value={tchClienteFiltro} onChange={(event) => { setTchClienteFiltro(event.target.value); setTchClientesPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} /></div></header>
        <section className="panel"><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre</th><th>Fecha nacimiento</th><th>Profesión</th><th>Tipo socio</th></tr></thead><tbody>{(tchClientes?.items ?? []).map((c) => <tr key={c.id}><td><button className="record-link" onClick={() => showTchCliente(c.rut)}>{c.rut}</button></td><td>{[c.nombre, c.apellido].filter(Boolean).join(" ") || "—"}</td><td>{c.fecha_nacimiento ?? "—"}</td><td>{c.profesion ?? "—"}</td><td>{c.tipo_socio ?? "—"}</td></tr>)}{(tchClientes?.items ?? []).length === 0 ? <tr><td colSpan={5}>Sin registros.</td></tr> : null}</tbody></table></div>{tchClientes && tchClientes.pages > 1 ? <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}><button disabled={tchClientesPage <= 1} onClick={() => setTchClientesPage((page) => page - 1)}>← Anterior</button><span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchClientesPage} / {tchClientes.pages} ({tchClientes.total.toLocaleString("es-CL")} total)</span><button disabled={tchClientesPage >= tchClientes.pages} onClick={() => setTchClientesPage((page) => page + 1)}>Siguiente →</button></div> : null}</section>
      </main>
    ) : tchView === "suscripciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / SUSCRIPCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Suscripciones TCH</h2><p>Mandatos activos e históricos de débito físico.</p></div>
          <div className="dashboard-controls">
            <select aria-label="Filtrar por estado" value={tchSusFiltroEstado} onChange={(e) => { setTchSusFiltroEstado(e.target.value); setTchSusPage(1); }}>
              <option value="">Todos los estados</option>
              <option value="VIGENTE">Vigentes</option>
              <option value="ELIMINADA">Eliminadas</option>
            </select>
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>RUT cliente</th><th>Banco</th>
                <th>Tipo mandato</th><th>Origen</th><th>Centro costo</th>
                <th>Monto</th><th>F. Activación</th><th>Estado</th>
              </tr></thead>
              <tbody>
                {(tchSuscripciones?.items ?? []).map((s) => (
                  <tr key={s.id}>
                    <td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td>
                    <td>{s.cliente_rut ?? "—"}</td>
                    <td>{s.banco_nombre ?? "—"}</td>
                    <td>{s.tipo_mandato ?? "—"}</td>
                    <td>{s.origen ?? "—"}</td>
                    <td>{s.centro_costo ?? "—"}</td>
                    <td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{s.fecha_activacion ?? "—"}</td>
                    <td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td>
                  </tr>
                ))}
                {(tchSuscripciones?.items ?? []).length === 0 ? <tr><td colSpan={9}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchSuscripciones && tchSuscripciones.pages > 1 ? (
            <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchSusPage <= 1} onClick={() => setTchSusPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchSusPage} / {tchSuscripciones.pages} ({tchSuscripciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchSusPage >= tchSuscripciones.pages} onClick={() => setTchSusPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : tchView === "transacciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / TRANSACCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Transacciones TCH</h2><p>Historial de cargos aceptados y rechazados.</p></div>
          <div className="dashboard-controls">
            <input type="month" aria-label="Filtrar por período" value={tchTransFiltroPeriodo} onChange={(e) => { setTchTransFiltroPeriodo(e.target.value); setTchTransPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>Período</th><th>Entidad</th>
                <th>Monto</th><th>Fecha cargo</th><th>Cuota</th><th>Estado</th>
              </tr></thead>
              <tbody>
                {(tchTransacciones?.items ?? []).map((t) => (
                  <tr key={t.id}>
                    <td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.numero_ficha}</button></td>
                    <td>{t.periodo ?? "—"}</td>
                    <td>{t.entidad_recaudadora ?? "—"}</td>
                    <td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{t.fecha_cargo ?? "—"}</td>
                    <td>{t.numero_cuota && t.total_cuotas ? `${t.numero_cuota}/${t.total_cuotas}` : (t.numero_cuota ?? "—")}</td>
                    <td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td>
                  </tr>
                ))}
                {(tchTransacciones?.items ?? []).length === 0 ? <tr><td colSpan={7}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchTransacciones && tchTransacciones.pages > 1 ? (
            <div style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchTransPage <= 1} onClick={() => setTchTransPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchTransPage} / {tchTransacciones.pages} ({tchTransacciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchTransPage >= tchTransacciones.pages} onClick={() => setTchTransPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : <main className="app-shell"><p className="muted-copy">Cargando...</p></main>
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
    vpRetryView ??
    providerDetail ??
    tchContent ??
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
          syncing={syncing}
          onMode={setMode}
          onYear={setYear}
          onOpenResource={openChannelResource}
          onReport={setReportScope}
          onSync={syncChannel}
        />
      )
    ) : (
      globalDashboard
    )))
  );

  if (session === undefined) return <main className="app-shell"><p className="muted-copy">Verificando sesión...</p></main>;
  if (session === null) return <LoginScreen onLogin={setSession} />;

  return (
    <div className="app-layout">
      <button
        className="burger-btn"
        aria-label="Abrir menú"
        onClick={() => setSidebarOpen(true)}
      >
        <span /><span /><span />
      </button>
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}
      <Sidebar
        activeSection={activeSection}
        channel={channel}
        tchView={tchView}
        openProvider={openProvider}
        theme={theme}
        onDashboard={showDashboard}
        generalView={generalView}
        onGeneralClients={showGeneralClients}
        onGeneralSubscriptions={showGeneralSubscriptions}
        onChannel={showChannel}
        onSection={showSection}
        onToggle={(provider) =>
          setOpenProvider((open) => (open === provider ? null : provider))
        }
        onTheme={toggleTheme}
        onTch={showTch}
        permissions={session.user.permissions}
        onAdmin={() => { clearDetails(); setChannel(null); setActiveSection(null); setTchView(null); setAdminOpen(true); }}
        onLogout={logout}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        vpRetryOpen={vpRetryOpen}
        onVpRetry={showVpRetry}
      />
      {adminOpen ? <AdminUsers canManageUsers={session.user.permissions.includes("users.manage")} /> : content}
      {clientEditDialog}
      {creatingPlan ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog edit-dialog-wide"
            aria-modal="true"
            aria-label="Crear plan VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSPlan}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / PLANES</p>
                <h3>Nuevo plan</h3>
              </div>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. El plan se creará en VirtualPOS y en la base de datos local.
            </p>
            <div className="vp-account-selector">
              <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
              <div className="vp-account-selector-buttons">
                <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos1")}>
                  Cuenta 1
                </button>
                <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos2")}>
                  Cuenta 2
                </button>
              </div>
            </div>
            <div className="edit-form-grid">
              {virtualPosPlanCreateFields.map((field) => {
                const hasError = Boolean(planFieldErrors[field.name]);
                const defaultVal = planDefaultValues[field.name] ?? "";
                return (
                  <label className={hasError ? "field-error" : ""} key={field.name}>
                    {field.label}{field.required ? <span className="field-required" aria-hidden="true"> *</span> : null}
                    {field.options ? (
                      <select name={field.name} defaultValue={defaultVal} aria-invalid={hasError} aria-required={field.required}>
                        {!field.required && <option value="">Sin especificar</option>}
                        {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : (
                      <input
                        name={field.name}
                        type={field.type ?? "text"}
                        defaultValue={defaultVal}
                        aria-invalid={hasError}
                        aria-required={field.required}
                        placeholder={field.name === "amount" ? "Ej: 9990" : field.name === "num_charges" ? "0 = ilimitado" : undefined}
                      />
                    )}
                    {hasError ? <span className="field-error-message">{planFieldErrors[field.name]}</span> : null}
                  </label>
                );
              })}
            </div>
            {planFormError ? <p className="error-message form-error">{planFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingPlan}>
                {savingPlan ? "Creando..." : "Crear plan"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingPlan(false)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {creatingSubscription ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog edit-dialog-wide"
            aria-modal="true"
            aria-label="Crear suscripción VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSSubscription}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / SUSCRIPCIONES</p>
                <h3>Nueva suscripción</h3>
              </div>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. El RUT será validado. Las URLs de retorno y callback se codificarán en Base64 automáticamente.
            </p>
            <div className="vp-account-selector">
              <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
              <div className="vp-account-selector-buttons">
                <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos1")}>
                  Cuenta 1
                </button>
                <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos2")}>
                  Cuenta 2
                </button>
              </div>
            </div>
            <div className="edit-form-grid">
              {virtualPosSubscriptionCreateFields.map((field) => {
                const hasError = Boolean(subscriptionFieldErrors[field.name]);
                const isRequired = subscriptionRequiredFields.has(field.name);
                return (
                  <label className={hasError ? "field-error" : ""} key={field.name}>
                    {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                    {field.options ? (
                      <select name={field.name} aria-invalid={hasError} aria-required={isRequired}>
                        <option value="">Sin especificar</option>
                        {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : (
                      <input
                        name={field.name}
                        type={field.type ?? "text"}
                        aria-invalid={hasError}
                        aria-required={isRequired}
                        placeholder={
                          field.name === "social_id" ? "Ej: 12345678-9"
                          : field.name === "plan_id" ? "ID exacto del plan en VirtualPOS"
                          : field.name === "phone_number" ? "Ej: 56912345678"
                          : undefined
                        }
                      />
                    )}
                    {hasError ? <span className="field-error-message">{subscriptionFieldErrors[field.name]}</span> : null}
                  </label>
                );
              })}
            </div>
            {subscriptionFormError ? <p className="error-message form-error">{subscriptionFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingSubscription}>
                {savingSubscription ? "Creando..." : "Crear suscripción"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingSubscription(false)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {subscriptionCancelDialog}
      {cancelingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar cargo VirtualPOS">
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Cancelar cargo</h3>
              </div>
              <span>{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará DELETE <code>/v3/charge/{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</code> a VirtualPOS.
              Solo cargos en estado <strong>pendiente</strong> pueden cancelarse. Esta acción no se puede deshacer.
            </p>
            {cancelChargeError ? <p className="error-message form-error">{cancelChargeError}</p> : null}
            <div className="edit-dialog-actions">
              <button
                type="button"
                className="cancel-subscription-button"
                disabled={savingCancelCharge}
                onClick={() => void cancelVirtualPOSCharge()}
              >
                {savingCancelCharge ? "Cancelando..." : "Confirmar cancelación"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCancelingCharge(null)}>
                Volver
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {retryingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Reintentar cargo VirtualPOS">
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Reintentar cargo</h3>
              </div>
              <span>{text(retryingCharge.payload.id, retryingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará GET <code>/v3/charge/{text(retryingCharge.payload.id, retryingCharge.external_id)}/retry</code> a VirtualPOS.
              Solo cargos en estado <strong>rechazado</strong> pueden reintentarse (máximo una vez diaria durante tres días consecutivos).
            </p>
            {retryChargeError ? <p className="error-message form-error">{retryChargeError}</p> : null}
            <div className="edit-dialog-actions">
              <button
                type="button"
                className="retry-charge-button"
                disabled={savingRetryCharge}
                onClick={() => void retryVirtualPOSCharge()}
              >
                {savingRetryCharge ? "Reintentando..." : "Confirmar reintento"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setRetryingCharge(null)}>
                Volver
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {creatingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog"
            aria-modal="true"
            aria-label="Crear cargo VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSCharge}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Nuevo cargo</h3>
              </div>
              <span className="edit-dialog-subtitle">Sub: {text(creatingCharge.payload.id, creatingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. La fecha del cargo no puede ser pasada.
            </p>
            <div className="edit-form-grid">
              <label className={chargeFieldErrors.charge_date ? "field-error" : ""}>
                Fecha del cargo<span className="field-required" aria-hidden="true"> *</span>
                <input
                  name="charge_date"
                  type="date"
                  aria-required="true"
                  aria-invalid={Boolean(chargeFieldErrors.charge_date)}
                  min={new Date().toISOString().split("T")[0]}
                />
                {chargeFieldErrors.charge_date ? <span className="field-error-message">{chargeFieldErrors.charge_date}</span> : null}
              </label>
              <label className={chargeFieldErrors.amount ? "field-error" : ""}>
                Monto<span className="field-required" aria-hidden="true"> *</span>
                <input
                  name="amount"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="Ej: 9990"
                  aria-required="true"
                  aria-invalid={Boolean(chargeFieldErrors.amount)}
                />
                {chargeFieldErrors.amount ? <span className="field-error-message">{chargeFieldErrors.amount}</span> : null}
              </label>
              <label>
                Descripción
                <input name="description" type="text" placeholder="Ej: Cuota agosto 2026" />
              </label>
              <label>
                Código interno
                <input name="internal_code" type="text" placeholder="Ej: AGO2026" />
              </label>
            </div>
            {chargeFormError ? <p className="error-message form-error">{chargeFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingCharge}>
                {savingCharge ? "Creando..." : "Crear cargo"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingCharge(null)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {managingTokuSub ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog"
            aria-modal="true"
            aria-label="Gestionar estado suscripción Toku"
            noValidate
            onSubmit={changeTokuSubscriptionStatus}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">TOKU / SUSCRIPCIÓN</p>
                <h3>Cambiar estado</h3>
              </div>
              <span>{text(managingTokuSub.payload.id, managingTokuSub.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará POST <code>/subscriptions/{text(managingTokuSub.payload.id, managingTokuSub.external_id)}/status</code> a Toku.
              Estado actual: <strong>{text(managingTokuSub.payload.status)}</strong>
            </p>
            <div className="edit-form-grid">
              <label>
                Nuevo estado<span className="field-required" aria-hidden="true"> *</span>
                <select name="status">
                  <option value="">Seleccionar...</option>
                  <option value="ACTIVE">ACTIVE — Activar</option>
                  <option value="PAUSED">PAUSED — Pausar</option>
                  <option value="CANCELLED">CANCELLED — Cancelar</option>
                </select>
              </label>
            </div>
            {tokuSubStatusError ? <p className="error-message form-error">{tokuSubStatusError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingTokuSubStatus}>
                {savingTokuSubStatus ? "Aplicando..." : "Confirmar cambio"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setManagingTokuSub(null)}>
                Volver
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {providerEditDialog}
      {providerDeleteDialog}
      {reportScope ? <ReportDialog scope={reportScope} onClose={() => setReportScope(null)} /> : null}
    </div>
  );
}

export default App;
