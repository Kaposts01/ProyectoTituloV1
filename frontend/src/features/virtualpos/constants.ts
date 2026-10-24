import { text, nested } from "../shared/utils";
import type { ClientEditField, FilterOption, StagingRecord } from "../shared/types";

export const virtualPosClientFields = [
  "uuid", "status", "type", "first_name", "last_name", "email",
  "phone_number", "social_id_type", "social_id", "birth_date",
  "gender_id", "private_note", "created", "updated",
];
export const virtualPosClientFieldLabels: Record<string, string> = {
  uuid: "UUID", status: "Estado", type: "Tipo", first_name: "Nombre",
  last_name: "Apellido", email: "Correo electronico", phone_number: "Telefono",
  social_id_type: "Tipo documento", social_id: "RUT documento",
  birth_date: "Fecha nacimiento", gender_id: "Genero",
  private_note: "Nota privada", created: "Creado", updated: "Actualizado",
};
export const virtualPosDocumentTypes: Record<string, string> = { "1": "RUT", "2": "DNI" };
export const recurringFieldLabels: Record<string, string> = {
  amount: "Monto", anchor: "Fecha inicio", status: "Estado",
  due_day: "Dia de cobro", end_date: "Fecha termino",
  interval: "Intervalo", frequency: "Frecuencia",
  creation_lead_days: "Dias de anticipacion",
  max_active_invoices: "Maximo de facturas activas",
};
export const virtualPosPlanFields = [
  "id", "name", "description", "is_active", "amount", "activation_amount",
  "currency", "trial_days", "num_charges", "frequency_type", "return_url",
  "suscription_url", "type", "fixed_amount_day_charge", "automatic_renewal",
  "show_in_terminal", "created_at", "shipping_address",
];
export const virtualPosSubscriptionFields = [
  "status", "secondary_status", "last_paid_date", "id", "service_id",
  "plan_name", "suscription_date", "canceled_at", "currency", "amount",
  "renewal", "channel",
];
export const virtualPosClientEditFields: ClientEditField[] = [
  { name: "status", label: "Estado", options: [{ value: "ACTIVO", label: "Activo" }, { value: "BLOQUEADO", label: "Bloqueado" }] },
  { name: "type", label: "Tipo", options: [{ value: "PERSONA", label: "Persona" }, { value: "EMPRESA", label: "Empresa" }] },
  { name: "first_name", label: "Nombre" },
  { name: "last_name", label: "Apellido" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone_number", label: "Teléfono", type: "tel" },
  { name: "social_id_type", label: "Tipo de documento", options: [{ value: "1", label: "RUT" }, { value: "2", label: "DNI" }] },
  { name: "social_id", label: "RUT / documento" },
  { name: "birth_date", label: "Fecha de nacimiento", type: "date" },
  { name: "gender_id", label: "Género", options: [{ value: "", label: "Sin especificar" }, { value: "Masculino", label: "Masculino" }, { value: "Femenino", label: "Femenino" }] },
];
export type PlanCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
export const virtualPosPlanCreateFields: PlanCreateField[] = [
  { name: "name", label: "Nombre del plan", required: true },
  { name: "amount", label: "Monto", type: "number", required: true },
  { name: "currency", label: "Moneda", required: true, options: [{ value: "CLP", label: "CLP — Peso chileno" }, { value: "UF", label: "UF — Unidad de fomento" }] },
  { name: "frequency_type", label: "Frecuencia de cobro", required: true, options: [
    { value: "monthly", label: "Mensual" }, { value: "weekly", label: "Semanal" },
    { value: "bimonthly", label: "Bimestral" }, { value: "quarterly", label: "Trimestral" },
    { value: "biannual", label: "Semestral" }, { value: "annual", label: "Anual" },
    { value: "daily", label: "Diario" },
  ]},
  { name: "description", label: "Descripción" },
  { name: "trial_days", label: "Días de prueba", type: "number" },
  { name: "num_charges", label: "N° de cobros (0 = ilimitado)", type: "number" },
  { name: "activation_amount", label: "Monto de activación", type: "number" },
  { name: "fixed_amount_day_charge", label: "Día de cobro del mes (1-28)", type: "number" },
  { name: "automatic_renewal", label: "Renovación automática", options: [{ value: "true", label: "Sí" }, { value: "false", label: "No" }] },
  { name: "show_in_terminal", label: "Visible en terminal", options: [{ value: "false", label: "No" }, { value: "true", label: "Sí" }] },
  { name: "is_active", label: "Activo", options: [{ value: "true", label: "Sí" }, { value: "false", label: "No" }] },
  { name: "return_url", label: "URL de retorno", type: "url" },
  { name: "suscription_url", label: "URL de suscripción", type: "url" },
  { name: "type", label: "Tipo de plan" },
];
export const planDefaultValues: Record<string, string> = {
  currency: "CLP", frequency_type: "monthly", automatic_renewal: "true",
  show_in_terminal: "false", is_active: "true",
};
export type SubscriptionCreateField = { name: string; label: string; type?: string; required?: boolean; options?: { value: string; label: string }[] };
export const virtualPosSubscriptionCreateFields: SubscriptionCreateField[] = [
  { name: "plan_id", label: "ID del plan", required: true },
  { name: "email", label: "Email del cliente", type: "email", required: true },
  { name: "first_name", label: "Nombre", required: true },
  { name: "last_name", label: "Apellido", required: true },
  { name: "social_id", label: "RUT", required: true },
  { name: "phone_number", label: "Teléfono", type: "tel" },
  { name: "service_id", label: "ID de servicio (interno)" },
  { name: "channel", label: "Canal", options: [{ value: "WEB", label: "WEB" }, { value: "CALL_CENTER", label: "Call center" }, { value: "PRESENCIAL", label: "Presencial" }] },
  { name: "automatic_renewal", label: "Renovación automática", options: [{ value: "T", label: "Sí" }, { value: "F", label: "No" }] },
  { name: "return_url", label: "URL de retorno", type: "url" },
  { name: "callback_url", label: "URL de callback", type: "url" },
];
export const subscriptionRequiredFields = new Set(["plan_id", "email", "first_name", "last_name", "social_id"]);

export const providerEditFields: Record<string, Record<string, ClientEditField[]>> = {
  toku: {
    customer: [{ name: "name", label: "Nombre" }, { name: "mail", label: "Correo electrónico", type: "email" }],
    invoice: [{ name: "amount", label: "Monto", type: "number" }, { name: "due_date", label: "Fecha límite", type: "date" }],
    subscription: [{ name: "amount", label: "Monto", type: "number" }],
  },
  payku: {
    client: [
      { name: "name", label: "Nombre" }, { name: "email", label: "Correo electrónico", type: "email" },
      { name: "phone", label: "Teléfono", type: "tel" }, { name: "address", label: "Dirección" },
      { name: "country", label: "País" }, { name: "region", label: "Región" },
      { name: "city", label: "Ciudad" }, { name: "postal_code", label: "Código postal" },
    ],
  },
};
export const deletableResources: Record<string, string[]> = {
  virtualpos: ["payment"],
  toku: ["customer", "invoice", "subscription", "payment_method"],
  payku: ["client", "subscription"],
};

export function deleteEndpoint(source: string, resourceType: string, record: StagingRecord): string {
  const id = text(record.payload.id, record.external_id);
  if (source === "virtualpos" && resourceType === "charge") return `/v3/charge/${id}`;
  if (source === "virtualpos" && resourceType === "payment")
    return `/v3/payment/${text(nested(record.payload, "order", "uuid") ?? record.payload.uuid, id)}`;
  if (source === "toku" && resourceType === "customer") return `/customers/${id}`;
  if (source === "toku" && resourceType === "invoice") return `/invoices/${id}`;
  if (source === "toku" && resourceType === "subscription") return `/subscriptions/${id}`;
  if (source === "toku" && resourceType === "payment_method") return `/payment-methods?id_payment_method=${id}`;
  if (source === "payku" && resourceType === "client") return `/api/suclient/${id}`;
  if (source === "payku" && resourceType === "subscription") return `/api/sususcription/${id}`;
  return `/${resourceType}/${id}`;
}

export const stagingFilters: Record<string, Record<string, FilterOption[]>> = {
  virtualpos: {
    client: [{ value: "uuid", label: "UUID" }, { value: "social_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "email", label: "Email" }, { value: "phone_number", label: "Teléfono" }, { value: "status", label: "Estado" }],
    plan: [{ value: "id", label: "ID" }, { value: "name", label: "Nombre" }, { value: "amount", label: "Monto" }, { value: "automatic_renewal", label: "Renovación" }, { value: "is_active", label: "Estado" }, { value: "show_in_terminal", label: "Activo en POS" }],
    subscription: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "secondary_status", label: "Estado sec." }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "suscription_date", label: "F. Inicio" }, { value: "canceled_at", label: "F. Cancelación" }],
    charge: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "subscription_id", label: "ID subscripción" }, { value: "amount", label: "Monto" }, { value: "charge_date", label: "Fecha de cargo" }],
    payment: [{ value: "uuid", label: "UUID" }, { value: "status", label: "Estado" }, { value: "social_id", label: "RUT cliente" }, { value: "amount", label: "Monto" }, { value: "authorized_at", label: "F. Pago" }],
  },
  toku: {
    customer: [{ value: "id", label: "ID" }, { value: "government_id", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "mail", label: "Mail" }, { value: "phone_number", label: "Teléfono" }],
    subscription: [{ value: "client_rut", label: "RUT cliente" }, { value: "client_name", label: "Cliente" }, { value: "id", label: "ID" }, { value: "amount", label: "Monto" }, { value: "status", label: "Estado" }, { value: "secondary_status", label: "Estado sec." }, { value: "anchor", label: "F. Inicio" }, { value: "end_date", label: "F. Cancelación" }],
    payment_method: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "customer_id", label: "Cliente" }, { value: "card_brand", label: "Marca" }, { value: "last_digits", label: "Terminación" }, { value: "bank_name", label: "Banco" }, { value: "card_type", label: "Tipo tarjeta" }, { value: "created_at", label: "F. Creación" }],
    invoice: [{ value: "client_rut", label: "RUT cliente" }, { value: "client_name", label: "Cliente" }, { value: "id", label: "ID" }, { value: "amount", label: "Monto" }, { value: "is_paid", label: "Pagado" }, { value: "status", label: "Estado" }, { value: "due_date", label: "Fecha límite" }],
    transaction: [{ value: "client_rut", label: "RUT cliente" }, { value: "client_name", label: "Cliente" }, { value: "id", label: "ID" }, { value: "amount", label: "Monto" }, { value: "transaction_date", label: "Fecha transacción" }],
  },
  payku: {
    client: [{ value: "id", label: "ID" }, { value: "rut", label: "RUT" }, { value: "name", label: "Nombre" }, { value: "email", label: "Email" }, { value: "phone", label: "Teléfono" }],
    plan: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "name", label: "Nombre" }],
    subscription: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "rut", label: "RUT" }, { value: "start", label: "F. Inicio" }, { value: "end", label: "F. Cancelación" }],
    transaction: [{ value: "id", label: "ID" }, { value: "status", label: "Estado" }, { value: "subscriptions", label: "ID subscripciones" }, { value: "amount", label: "Monto" }, { value: "created_at", label: "F. Pago" }],
  },
};

const vpColumnFields: Record<string, Record<string, string>> = {
  client: { RUT: "social_id", Nombre: "name", Email: "email", Telefono: "phone_number", Estado: "status" },
  plan: { Nombre: "name", Monto: "amount", Renovacion: "automatic_renewal", Estado: "is_active", "Activo en POS": "show_in_terminal" },
  subscription: { "RUT cliente": "social_id", Estado: "status", "Estado sec.": "secondary_status", Monto: "amount", "F. Inicio": "suscription_date", "F. Cancelacion": "canceled_at" },
  charge: { "ID subscripción": "subscription_id", "Fecha de cargo": "charge_date", Estado: "status", Monto: "amount" },
  payment: { "RUT cliente": "social_id", "F. Pago": "authorized_at", Monto: "amount", Estado: "status" },
};

export function virtualPosFieldForColumn(resource: string, label: string): string | null {
  return vpColumnFields[resource]?.[label] ?? null;
}

export function filterFieldForColumn(source: string, resource: string, label: string): string | null {
  if (source === "virtualpos") return virtualPosFieldForColumn(resource, label);
  const normalize = (value: string) => value.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  return stagingFilters[source]?.[resource]?.find((option) => normalize(option.label) === normalize(label))?.value ?? null;
}
