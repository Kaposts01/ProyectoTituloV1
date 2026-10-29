/**
 * Traduce cada lista de datos al contrato de exportación del backend (docs/data/exports.md):
 * entidad, canal y parámetros (`filter_field`, `query`, `status`, `date_from`, `amount_min`, ...).
 * Lo que la exportación no puede expresar se devuelve en `ignored` para avisarlo al usuario.
 */
import type { ProviderSource } from "../../routes";

export type ExportEntity = "clientes" | "suscripciones" | "cobros" | "pagos";
export type ExportCanal = "virtualpos" | "virtualpos1" | "virtualpos2" | "toku" | "payku" | "tch";
export type ExportParams = Record<string, string>;

export type ExportTarget = {
  entity: ExportEntity;
  /** Sin canal: todos los canales a los que el usuario tiene permiso de vista. */
  canal?: ExportCanal;
  params: ExportParams;
  /** Filtros activos que la exportación no puede aplicar (se exportará sin ellos). */
  ignored: string[];
  /** Permiso de vista que exige el contrato para este canal y entidad (null si no aplica un único permiso). */
  viewPermission: string | null;
};

/** Permiso de vista por canal y entidad (tabla «Permisos» del contrato). */
const VIEW_PERMISSIONS: Record<string, Partial<Record<ExportEntity, string>>> = {
  virtualpos: {
    clientes: "virtualpos.clients.view",
    suscripciones: "virtualpos.subscriptions.view",
    cobros: "virtualpos.charges.view",
    pagos: "virtualpos.payments.view",
  },
  toku: {
    clientes: "toku.customers.view",
    suscripciones: "toku.subscriptions.view",
    cobros: "toku.invoices.view",
    pagos: "toku.transactions.view",
  },
  payku: {
    clientes: "payku.clients.view",
    suscripciones: "payku.subscriptions.view",
    pagos: "payku.transactions.view",
  },
  tch: {
    clientes: "tch.clientes.view",
    suscripciones: "tch.suscripciones.view",
    cobros: "tch.transacciones.view",
  },
};

export function exportViewPermission(canal: ExportCanal, entity: ExportEntity): string | null {
  const family = canal.startsWith("virtualpos") ? "virtualpos" : canal;
  return VIEW_PERMISSIONS[family]?.[entity] ?? null;
}

/** Recurso de staging -> entidad de exportación, por canal. Los recursos ausentes (planes, métodos de pago) no se exportan. */
const RESOURCE_ENTITY: Record<ProviderSource, Record<string, ExportEntity>> = {
  virtualpos: { client: "clientes", subscription: "suscripciones", charge: "cobros", payment: "pagos" },
  toku: { customer: "clientes", subscription: "suscripciones", invoice: "cobros", transaction: "pagos" },
  payku: { client: "clientes", subscription: "suscripciones", transaction: "pagos" },
};

/** Campo de búsqueda de staging -> `filter_field` de la exportación, por canal, recurso y campo. null = sin equivalente. */
const FIELD_MAP: Record<string, Record<string, Record<string, string>>> = {
  virtualpos: {
    client: { social_id: "rut", name: "name", email: "email", phone_number: "phone" },
    subscription: { id: "id", social_id: "rut" },
    charge: { id: "id", subscription_id: "subscription_id" },
    payment: { uuid: "id" },
  },
  toku: {
    customer: { government_id: "rut", name: "name", mail: "email", phone_number: "phone" },
    subscription: { id: "id", client_rut: "rut", client_name: "client" },
    invoice: { id: "id" },
    transaction: { id: "id" },
  },
  payku: {
    client: { rut: "rut", name: "name", email: "email", phone: "phone" },
    subscription: { id: "id", rut: "rut" },
    transaction: { id: "id" },
  },
};

const FIELD_LABEL: Record<string, string> = {
  social_id: "RUT", government_id: "RUT", client_rut: "RUT", rut: "RUT", name: "nombre", client_name: "cliente",
  email: "correo", mail: "correo", phone: "teléfono", phone_number: "teléfono", id: "ID", uuid: "UUID",
  status: "estado", secondary_status: "estado secundario", amount: "monto", subscription_id: "ID de suscripción",
  is_paid: "pagado", customer_id: "cliente", subscriptions: "ID de suscripciones", start: "fecha de inicio",
  end: "fecha de cancelación", transaction_date: "fecha de transacción", created_at: "fecha de pago",
  automatic_renewal: "renovación", is_active: "estado", show_in_terminal: "activo en POS",
};
const labelOf = (field: string) => FIELD_LABEL[field] ?? field;

/** Campos de VirtualPOS que son de fecha: el contrato solo ofrece `date_from`/`date_to` sobre la fecha propia de la entidad. */
const DATE_KEYS = new Set(["date_from", "date_to"]);

export type StagingExportInput = {
  source: ProviderSource;
  resource: string;
  /** Solo VirtualPOS: «all» o la plataforma elegida. */
  vpPlatform?: "all" | "virtualpos1" | "virtualpos2";
  filterField: string;
  filterQuery: string;
  vpColumnFilters: Record<string, string>;
};

/** null si el recurso no tiene exportación (planes, métodos de pago). */
export function stagingExportTarget(input: StagingExportInput): ExportTarget | null {
  const entity = RESOURCE_ENTITY[input.source]?.[input.resource];
  if (!entity) return null;
  const canal: ExportCanal =
    input.source === "virtualpos" && input.vpPlatform && input.vpPlatform !== "all" ? input.vpPlatform : input.source;
  const params: ExportParams = {};
  const ignored: string[] = [];
  const fieldMap = FIELD_MAP[input.source]?.[input.resource] ?? {};
  let textUsed = false;
  const setText = (field: string, value: string) => {
    const mapped = fieldMap[field];
    if (!mapped) { ignored.push(`${labelOf(field)}: «${value}»`); return; }
    if (textUsed) { ignored.push(`${labelOf(field)}: «${value}» (solo se puede enviar una búsqueda de texto)`); return; }
    textUsed = true;
    params.filter_field = mapped;
    params.query = value;
  };

  if (input.source === "virtualpos") {
    for (const [key, raw] of Object.entries(input.vpColumnFilters)) {
      const value = raw.trim();
      if (!value) continue;
      if (key === "amount_min" || key === "amount_max") {
        if (entity === "clientes") ignored.push(`${labelOf("amount")}: ${value}`);
        else params[key] = value;
      } else if (DATE_KEYS.has(key)) {
        params[key] = value;
      } else if (key === "status") {
        params.status = value;
      } else {
        setText(key, value);
      }
    }
  } else {
    const value = input.filterQuery.trim();
    if (value) {
      if (input.filterField === "status") params.status = value;
      else setText(input.filterField, value);
    }
  }
  return { entity, canal, params, ignored, viewPermission: exportViewPermission(canal, entity) };
}

/** Clientes y suscripciones consolidados: sus campos de búsqueda coinciden con los del contrato. */
export function consolidatedExportTarget(
  entity: "clientes" | "suscripciones",
  filterField: string,
  query: string,
): ExportTarget {
  const params: ExportParams = {};
  const value = query.trim();
  if (value) {
    params.filter_field = filterField || "all";
    params.query = value;
  }
  return { entity, params, ignored: [], viewPermission: null };
}

/** Listas TCH. `periodo` llega como `AAAA-MM` y se traduce al mes completo en `date_from`/`date_to`. */
export function tchExportTarget(
  view: "clientes" | "suscripciones" | "transacciones",
  filters: { nombre?: string; estado?: string; periodo?: string },
): ExportTarget {
  const entity: ExportEntity = view === "transacciones" ? "cobros" : view;
  const params: ExportParams = {};
  if (view === "clientes" && filters.nombre?.trim()) {
    params.filter_field = "name";
    params.query = filters.nombre.trim();
  }
  if (view === "suscripciones" && filters.estado) params.status = filters.estado;
  if (view === "transacciones" && filters.periodo && /^\d{4}-\d{2}$/.test(filters.periodo)) {
    const [year, month] = filters.periodo.split("-").map(Number);
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    params.date_from = `${filters.periodo}-01`;
    params.date_to = `${filters.periodo}-${String(last).padStart(2, "0")}`;
  }
  return { entity, canal: "tch", params, ignored: [], viewPermission: exportViewPermission("tch", entity) };
}
