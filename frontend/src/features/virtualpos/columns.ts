import { label, labelOr } from "../../i18n/label";
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
  const plataforma: TableColumn = { key: "Plataforma", label: "Plataforma", value: vpPlatformLabel };
  if (resource === "client")
    return [
      { key: "RUT", label: "RUT", value: (rec) => text(rec.payload.social_id) },
      { key: "Nombre", label: "Nombre", value: (rec) => `${text(rec.payload.first_name, "")} ${text(rec.payload.last_name, "")}`.trim() || "Sin dato" },
      { key: "Email", label: "Correo electrónico", value: (rec) => text(rec.payload.email) },
      { key: "Telefono", label: "Teléfono", value: (rec) => text(rec.payload.phone_number) },
      plataforma,
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Acciones", label: "Acciones", value: () => "Editar" },
    ];
  if (resource === "plan")
    return [
      { key: "Nombre", label: "Nombre", value: (rec) => text(rec.payload.name) },
      { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { key: "Subscripciones", label: "Suscripciones", value: (rec) => String(rec.subscription_count ?? 0) },
      { key: "Activas", label: "Activas", value: (rec) => String(rec.active_subscription_count ?? 0) },
      { key: "Cobrables", label: "Cobrables", value: (rec) => String(rec.cobrable_subscription_count ?? 0) },
      { key: "Renovacion", label: "Renovación", value: (rec) => active(rec.payload.automatic_renewal) },
      { key: "Estado", label: "Estado", value: (rec) => active(rec.payload.is_active) },
      { key: "Activo en POS", label: "Activo en POS", value: (rec) => active(rec.payload.show_in_terminal) },
      plataforma,
    ];
  if (resource === "subscription")
    return [
      { key: "RUT cliente", label: "RUT cliente", value: clientRut },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Estado sec.", label: "Estado sec.", value: (rec) => labelOr("secondaryStatus", rec.secondary_status, "—") },
      { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { key: "F. Inicio", label: "F. Inicio", value: (rec) => text(rec.payload.suscription_date) },
      { key: "F. Cancelacion", label: "F. Cancelación", value: (rec) => text(rec.payload.canceled_at) },
      { key: "Último cobro", label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      plataforma,
      { key: "Acciones", label: "Acciones", value: () => "Cancelar" },
    ];
  if (resource === "charge")
    return [
      { key: "ID subscripción", label: "ID suscripción", value: (rec) => rec.subscription_id ?? text(rec.payload.subscription_id ?? rec.payload.suscription_id) },
      { key: "Cliente", label: "Cliente", value: (rec) => rec.client_name ?? "Sin dato" },
      { key: "RUT cliente", label: "RUT cliente", value: (rec) => rec.client_social_id ?? "Sin dato" },
      { key: "Fecha de cargo", label: "Fecha de cargo", value: (rec) => text(rec.payload.charge_date) },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
      plataforma,
      { key: "Acciones", label: "Acciones", value: () => "Eliminar" },
    ];
  return [
    { key: "RUT cliente", label: "RUT cliente", value: clientRut },
    { key: "Cliente", label: "Cliente", value: (rec) => rec.client_name ?? "Sin dato" },
    { key: "F. Pago", label: "F. Pago", value: (rec) => text(nested(rec.payload, "order", "authorized_at")) },
    { key: "Monto", label: "Monto", value: (rec) => clp(nested(rec.payload, "order", "amount")) },
    { key: "Estado", label: "Estado", value: (rec) => label("status", nested(rec.payload, "order", "status")) },
    plataforma,
    { key: "Acciones", label: "Acciones", value: () => "Eliminar" },
  ];
}

export function tokuColumns(resource: string): TableColumn[] {
  if (resource === "customer")
    return [
      { key: "RUT", label: "RUT", value: (rec) => text(rec.payload.government_id) },
      { key: "Nombre", label: "Nombre", value: (rec) => text(rec.payload.name) },
      { key: "Mail", label: "Correo electrónico", value: (rec) => text(rec.payload.mail) },
      { key: "Telefono", label: "Teléfono", value: (rec) => text(rec.payload.phone_number) },
      { key: "Acciones", label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "subscription")
    return [
      { key: "RUT cliente", label: "RUT cliente", value: (rec) => text(rec.client_rut) },
      { key: "Cliente", label: "Cliente", value: (rec) => text(rec.client_name) },
      { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status ?? nested(rec.payload, "recurring", "status")) },
      { key: "Estado sec.", label: "Estado sec.", value: (rec) => labelOr("secondaryStatus", rec.secondary_status, "—") },
      { key: "Último cobro", label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      { key: "F. Inicio", label: "F. Inicio", value: (rec) => dateOnly(rec.payload.anchor ?? nested(rec.payload, "recurring", "anchor")) },
      { key: "F. Cancelacion", label: "F. Cancelación", value: (rec) => dateOnly(rec.payload.end_date ?? nested(rec.payload, "recurring", "end_date")) },
      { key: "Acciones", label: "Acciones", value: () => "Acciones" },
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
      { key: "ID", label: "ID", value: (item) => text(method(item).id ?? item.payload.id, item.external_id) },
      { key: "Estado", label: "Estado", value: (item) => label("status", method(item).status ?? item.payload.status) },
      { key: "F. Creacion", label: "F. Creación", value: (item) => dateOnly(method(item).created_at ?? item.payload.created_at) },
      { key: "Cliente", label: "Cliente", value: (item) => text(customer(item).name ?? customer(item).id ?? item.payload.customer_id ?? item.payload.customer) },
      { key: "Marca", label: "Marca", value: (item) => text(card(item).card_brand ?? method(item).card_brand) },
      { key: "Terminacion", label: "Terminación", value: (item) => text(card(item).last_digits ?? method(item).last_digits) },
      { key: "Banco", label: "Banco", value: (item) => text(card(item).bank_name ?? method(item).bank_name) },
      { key: "Tipo tarjeta", label: "Tipo tarjeta", value: (item) => cardTypeText(card(item).card_type ?? method(item).card_type) },
      { key: "Subscripciones", label: "Suscripciones", value: subscriptionCount },
      { key: "Acciones", label: "Acciones", value: () => "Eliminar" },
    ];
  }
  if (resource === "invoice")
    return [
      { key: "RUT cliente", label: "RUT cliente", value: (rec) => text(rec.client_rut) },
      { key: "Cliente", label: "Cliente", value: (rec) => text(rec.client_name) },
      { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
      { key: "Pagado", label: "Pagado", value: (rec) => paid(rec.payload.is_paid) },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Fecha limite", label: "Fecha límite", value: (rec) => dateOnly(rec.payload.due_date) },
      { key: "Acciones", label: "Acciones", value: () => "Acciones" },
    ];
  return [
    { key: "RUT cliente", label: "RUT cliente", value: (rec) => text(nested(rec.payload, "customer", "government_id") ?? rec.client_rut) },
    { key: "Cliente", label: "Cliente", value: (rec) => text(nested(rec.payload, "customer", "name") ?? rec.client_name) },
    { key: "Monto", label: "Monto", value: (rec) => clp(nested(rec.payload, "transaction", "amount") ?? rec.payload.amount) },
    { key: "Fecha transaccion", label: "Fecha transacción", value: (rec) => dateOnly(nested(rec.payload, "transaction", "transaction_date") ?? rec.payload.transaction_date) },
  ];
}

export function tokuRelatedColumns(resource: string): TableColumn[] {
  if (resource === "customer")
    return [
      { key: "Nombre", label: "Nombre", value: (item) => text(item.payload.name) },
      { key: "RUT", label: "RUT", value: (item) => text(item.payload.government_id) },
      { key: "Estado", label: "Estado", value: (item) => label("status", item.payload.status) },
    ];
  if (resource === "payment_method")
    return [
      { key: "Estado", label: "Estado", value: (item) => label("status", nested(item.payload, "payment_method", "status") ?? item.payload.status) },
      { key: "Fecha creación", label: "Fecha creación", value: (item) => dateOnly(nested(item.payload, "payment_method", "created_at") ?? item.payload.created_at) },
    ];
  if (resource === "invoice")
    return [
      { key: "Estado", label: "Estado", value: (item) => label("status", item.payload.status) },
      { key: "Fecha", label: "Fecha", value: (item) => dateOnly(item.payload.due_date ?? item.payload.created_at) },
      { key: "Monto", label: "Monto", value: (item) => clp(item.payload.amount) },
    ];
  if (resource === "transaction")
    return [
      { key: "Estado", label: "Estado", value: (item) => label("status", nested(item.payload, "transaction", "status") ?? item.payload.status) },
      { key: "Fecha", label: "Fecha", value: (item) => dateOnly(nested(item.payload, "transaction", "transaction_date") ?? item.payload.transaction_date) },
      { key: "Monto", label: "Monto", value: (item) => clp(nested(item.payload, "transaction", "amount") ?? item.payload.amount) },
    ];
  return [
    { key: "Nombre", label: "Nombre", value: (item) => text(item.payload.name, text(nested(item.payload, "client", "name"))) },
    { key: "Estado", label: "Estado", value: (item) => label("status", item.payload.status) },
    { key: "Monto", label: "Monto", value: (item) => clp(item.payload.amount) },
  ];
}

export function paykuColumns(resource: string): TableColumn[] {
  if (resource === "client")
    return [
      { key: "ID", label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { key: "RUT", label: "RUT", value: (rec) => text(rec.payload.rut) },
      { key: "Nombre", label: "Nombre", value: (rec) => `${text(rec.payload.first_name, "")} ${text(rec.payload.last_name, "")}`.trim() || text(rec.payload.name) },
      { key: "Email", label: "Correo electrónico", value: (rec) => text(rec.payload.email) },
      { key: "Telefono", label: "Teléfono", value: (rec) => text(rec.payload.phone) },
      { key: "Acciones", label: "Acciones", value: () => "Acciones" },
    ];
  if (resource === "plan")
    return [
      { key: "ID", label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Nombre", label: "Nombre", value: (rec) => text(rec.payload.name) },
      { key: "Subscripciones activas", label: "Suscripciones activas", value: (rec) => (rec.active_subscriptions ?? 0).toLocaleString("es-CL") },
      { key: "Subscripciones cobrables", label: "Suscripciones cobrables", value: (rec) => (rec.collectible_subscriptions ?? 0).toLocaleString("es-CL") },
    ];
  if (resource === "subscription")
    return [
      { key: "ID", label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
      { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
      { key: "Estado sec.", label: "Estado sec.", value: (rec) => labelOr("secondaryStatus", rec.secondary_status, "—") },
      { key: "Último cobro", label: "Último cobro", value: (rec) => rec.last_paid_date ? String(rec.last_paid_date).slice(0, 10) : "—" },
      { key: "RUT", label: "RUT", value: (rec) => text(nested(rec.payload, "client", "rut")) },
      { key: "F. Inicio", label: "F. Inicio", value: (rec) => text(rec.payload.start) },
      { key: "F. Cancelacion", label: "F. Cancelación", value: (rec) => text(rec.payload.end) },
      { key: "Acciones", label: "Acciones", value: () => "Eliminar" },
    ];
  return [
    { key: "ID", label: "ID", value: (rec) => text(rec.payload.id, rec.external_id) },
    { key: "Estado", label: "Estado", value: (rec) => label("status", rec.payload.status) },
    { key: "ID subscripciones", label: "ID suscripciones", value: (rec) => text(rec.payload.subscriptions) },
    { key: "Monto", label: "Monto", value: (rec) => clp(rec.payload.amount) },
    { key: "F. Pago", label: "F. Pago", value: (rec) => text(rec.payload.created_at) },
  ];
}
