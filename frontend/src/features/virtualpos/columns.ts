import { text, dateOnly, clp, nested, cardTypeText, record } from "../shared/utils";
import type { StagingRecord, TableColumn } from "../shared/types";

export function virtualPosClientName(rec: StagingRecord): string {
  const client = rec.payload.client;
  if (!client || typeof client !== "object") return "Sin dato";
  const payload = client as Record<string, unknown>;
  return `${text(payload.first_name, "")} ${text(payload.last_name, "")}`.trim() || "Sin dato";
}

export function vpClientRecordName(rec: StagingRecord): string {
  return `${text(rec.payload.first_name, "")} ${text(rec.payload.last_name, "")}`.trim() || "Sin dato";
}

function active(value: unknown): string {
  return String(value).toLowerCase() === "true" ? "Activo" : "Inactivo";
}

function paid(value: unknown): string {
  if (value === true || String(value).toLowerCase() === "true") return "Pagado";
  if (value === false || String(value).toLowerCase() === "false") return "No pagado";
  return "Sin dato";
}

const vpPlatformLabel = (rec: StagingRecord) =>
  rec.source === "virtualpos1" ? "VP 1" : rec.source === "virtualpos2" ? "VP 2" : rec.source;

export function virtualPosColumns(resource: string): TableColumn[] {
  const clientRut = (rec: StagingRecord) =>
    text(nested(rec.payload, "client", "social_id") ?? rec.payload.social_id);
  const plataforma: TableColumn = { label: "Plataforma", value: vpPlatformLabel };
  if (resource === "client")
    return [
      { label: "RUT", value: (rec) => text(rec.payload.social_id) },
      { label: "Nombre", value: (rec) => `${text(rec.payload.first_name, "")} ${text(rec.payload.last_name, "")}`.trim() || "Sin dato" },
      { label: "Email", value: (rec) => text(rec.payload.email) },
      { label: "Telefono", value: (rec) => text(rec.payload.phone_number) },
      plataforma,
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Acciones", value: () => "Editar" },
    ];
  if (resource === "plan")
    return [
      { label: "Nombre", value: (rec) => text(rec.payload.name) },
      { label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { label: "Subscripciones", value: (rec) => String(rec.subscription_count ?? 0) },
      { label: "Activas", value: (rec) => String(rec.active_subscription_count ?? 0) },
      { label: "Cobrables", value: (rec) => String(rec.cobrable_subscription_count ?? 0) },
      { label: "Renovacion", value: (rec) => active(rec.payload.automatic_renewal) },
      { label: "Estado", value: (rec) => active(rec.payload.is_active) },
      { label: "Activo en POS", value: (rec) => active(rec.payload.show_in_terminal) },
      plataforma,
    ];
  if (resource === "subscription")
    return [
      { label: "RUT cliente", value: clientRut },
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Estado sec.", value: (rec) => rec.secondary_status ?? "—" },
      { label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { label: "F. Inicio", value: (rec) => text(rec.payload.suscription_date) },
      { label: "F. Cancelacion", value: (rec) => text(rec.payload.canceled_at) },
      { label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      plataforma,
      { label: "Acciones", value: () => "Cancelar" },
    ];
  if (resource === "charge")
    return [
      { label: "ID subscripción", value: (rec) => rec.subscription_id ?? text(rec.payload.subscription_id ?? rec.payload.suscription_id) },
      { label: "Cliente", value: (rec) => rec.client_name ?? "Sin dato" },
      { label: "RUT cliente", value: (rec) => rec.client_social_id ?? "Sin dato" },
      { label: "Fecha de cargo", value: (rec) => text(rec.payload.charge_date) },
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Monto", value: (rec) => clp(rec.payload.amount) },
      plataforma,
      { label: "Acciones", value: () => "Eliminar" },
    ];
  return [
    { label: "RUT cliente", value: clientRut },
    { label: "Cliente", value: (rec) => rec.client_name ?? "Sin dato" },
    { label: "F. Pago", value: (rec) => text(nested(rec.payload, "order", "authorized_at")) },
    { label: "Monto", value: (rec) => clp(nested(rec.payload, "order", "amount")) },
    { label: "Estado", value: (rec) => text(nested(rec.payload, "order", "status")) },
    plataforma,
    { label: "Acciones", value: () => "Eliminar" },
  ];
}

export function tokuColumns(resource: string): TableColumn[] {
  if (resource === "customer")
    return [
      { label: "RUT", value: (rec) => text(rec.payload.government_id) },
      { label: "Nombre", value: (rec) => text(rec.payload.name) },
      { label: "Mail", value: (rec) => text(rec.payload.mail) },
      { label: "Telefono", value: (rec) => text(rec.payload.phone_number) },
      { label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "subscription")
    return [
      { label: "RUT cliente", value: (rec) => text(rec.client_rut) },
      { label: "Cliente", value: (rec) => text(rec.client_name) },
      { label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { label: "Estado", value: (rec) => text(rec.payload.status ?? nested(rec.payload, "recurring", "status")) },
      { label: "Estado sec.", value: (rec) => rec.secondary_status ?? "—" },
      { label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      { label: "F. Inicio", value: (rec) => dateOnly(rec.payload.anchor ?? nested(rec.payload, "recurring", "anchor")) },
      { label: "F. Cancelacion", value: (rec) => dateOnly(rec.payload.end_date ?? nested(rec.payload, "recurring", "end_date")) },
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
      { label: "ID", value: (item) => text(method(item).id ?? item.payload.id, item.external_id) },
      { label: "Estado", value: (item) => text(method(item).status ?? item.payload.status) },
      { label: "F. Creacion", value: (item) => dateOnly(method(item).created_at ?? item.payload.created_at) },
      { label: "Cliente", value: (item) => text(customer(item).name ?? customer(item).id ?? item.payload.customer_id ?? item.payload.customer) },
      { label: "Marca", value: (item) => text(card(item).card_brand ?? method(item).card_brand) },
      { label: "Terminacion", value: (item) => text(card(item).last_digits ?? method(item).last_digits) },
      { label: "Banco", value: (item) => text(card(item).bank_name ?? method(item).bank_name) },
      { label: "Tipo tarjeta", value: (item) => cardTypeText(card(item).card_type ?? method(item).card_type) },
      { label: "Subscripciones", value: subscriptionCount },
      { label: "Acciones", value: () => "Eliminar" },
    ];
  }
  if (resource === "invoice")
    return [
      { label: "RUT cliente", value: (rec) => text(rec.client_rut) },
      { label: "Cliente", value: (rec) => text(rec.client_name) },
      { label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { label: "Pagado", value: (rec) => paid(rec.payload.is_paid) },
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Fecha limite", value: (rec) => dateOnly(rec.payload.due_date) },
      { label: "Acciones", value: () => "Acciones" },
    ];
  return [
    { label: "RUT cliente", value: (rec) => text(nested(rec.payload, "customer", "government_id") ?? rec.client_rut) },
    { label: "Cliente", value: (rec) => text(nested(rec.payload, "customer", "name") ?? rec.client_name) },
    { label: "Monto", value: (rec) => clp(nested(rec.payload, "transaction", "amount") ?? rec.payload.amount) },
    { label: "Fecha transaccion", value: (rec) => dateOnly(nested(rec.payload, "transaction", "transaction_date") ?? rec.payload.transaction_date) },
  ];
}

export function tokuRelatedColumns(resource: string): TableColumn[] {
  if (resource === "customer")
    return [
      { label: "Nombre", value: (item) => text(item.payload.name) },
      { label: "RUT", value: (item) => text(item.payload.government_id) },
      { label: "Estado", value: (item) => text(item.payload.status) },
    ];
  if (resource === "payment_method")
    return [
      { label: "Estado", value: (item) => text(nested(item.payload, "payment_method", "status") ?? item.payload.status) },
      { label: "Fecha creación", value: (item) => dateOnly(nested(item.payload, "payment_method", "created_at") ?? item.payload.created_at) },
    ];
  if (resource === "invoice")
    return [
      { label: "Estado", value: (item) => text(item.payload.status) },
      { label: "Fecha", value: (item) => dateOnly(item.payload.due_date ?? item.payload.created_at) },
      { label: "Monto", value: (item) => clp(item.payload.amount) },
    ];
  if (resource === "transaction")
    return [
      { label: "Estado", value: (item) => text(nested(item.payload, "transaction", "status") ?? item.payload.status) },
      { label: "Fecha", value: (item) => dateOnly(nested(item.payload, "transaction", "transaction_date") ?? item.payload.transaction_date) },
      { label: "Monto", value: (item) => clp(nested(item.payload, "transaction", "amount") ?? item.payload.amount) },
    ];
  return [
    { label: "Nombre", value: (item) => text(item.payload.name, text(nested(item.payload, "client", "name"))) },
    { label: "Estado", value: (item) => text(item.payload.status) },
    { label: "Monto", value: (item) => clp(item.payload.amount) },
  ];
}

export function paykuColumns(resource: string): TableColumn[] {
  if (resource === "client")
    return [
      { label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { label: "RUT", value: (rec) => text(rec.payload.rut) },
      { label: "Nombre", value: (rec) => `${text(rec.payload.first_name, "")} ${text(rec.payload.last_name, "")}`.trim() || text(rec.payload.name) },
      { label: "Email", value: (rec) => text(rec.payload.email) },
      { label: "Telefono", value: (rec) => text(rec.payload.phone) },
      { label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "plan")
    return [
      { label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Nombre", value: (rec) => text(rec.payload.name) },
      { label: "Subscripciones activas", value: (rec) => (rec.active_subscriptions ?? 0).toLocaleString("es-CL") },
      { label: "Subscripciones cobrables", value: (rec) => (rec.collectible_subscriptions ?? 0).toLocaleString("es-CL") },
    ];
  if (resource === "subscription")
    return [
      { label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { label: "Estado", value: (rec) => text(rec.payload.status) },
      { label: "Estado sec.", value: (rec) => rec.secondary_status ?? "—" },
      { label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      { label: "RUT", value: (rec) => text(nested(rec.payload, "client", "rut")) },
      { label: "F. Inicio", value: (rec) => text(rec.payload.start) },
      { label: "F. Cancelacion", value: (rec) => text(rec.payload.end) },
      { label: "Acciones", value: () => "Eliminar" },
    ];
  return [
    { label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
    { label: "Estado", value: (rec) => text(rec.payload.status) },
    { label: "ID subscripciones", value: (rec) => text(rec.payload.subscriptions) },
    { label: "Monto", value: (rec) => clp(rec.payload.amount) },
    { label: "F. Pago", value: (rec) => text(rec.payload.created_at) },
  ];
}
