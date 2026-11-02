/**
 * Vistas de solo lectura del recuperador general para Toku (REC-04) y TCH (REC-06).
 * Cada vista apunta a un endpoint `/api/v1/recovery/<canal>/<vista>` que exige el permiso de su pestaña.
 */

export type ReadOnlyChannel = "toku" | "tch";

export type ColumnKind = "id" | "text" | "date" | "number" | "money" | "status" | "tchStatus" | "reason" | "recoverableReason";

export type RecoveryColumn = { key: string; header: string; kind: ColumnKind };

export type ChannelView = {
  id: string;
  label: string;
  path: string;
  /** Rótulos del filtro de fechas; null si la vista no filtra por fecha. */
  dateLabels: { from: string; to: string } | null;
  /** La vista acepta el filtro de motivo (`reason`). */
  reasonFilter?: boolean;
  columns: RecoveryColumn[];
};

export type ChannelRecoveryConfig = { id: ReadOnlyChannel; label: string; notice: string; views: ChannelView[] };

const money = (key = "amount"): RecoveryColumn => ({ key, header: "Monto", kind: "money" });

export const CHANNEL_RECOVERY: Record<ReadOnlyChannel, ChannelRecoveryConfig> = {
  toku: {
    id: "toku",
    label: "Toku",
    notice: "Solo lectura: los datos salen del modelo central (core) de Toku. Las acciones de cobro siguen en el portal de Toku.",
    views: [
      {
        id: "cancelled",
        label: "Suscripciones dadas de baja",
        path: "/api/v1/recovery/toku/cancelled",
        dateLabels: { from: "Baja desde", to: "Baja hasta" },
        columns: [
          { key: "subscription_id", header: "Suscripción", kind: "id" },
          { key: "status", header: "Estado", kind: "status" },
          { key: "started_at", header: "Alta", kind: "date" },
          { key: "cancelled_at", header: "Baja", kind: "date" },
          { key: "antiquity_days", header: "Antigüedad (días)", kind: "number" },
          money(),
          { key: "payment_method_status", header: "Medio de pago", kind: "status" },
        ],
      },
      {
        id: "rejected",
        label: "Cobros rechazados",
        path: "/api/v1/recovery/toku/rejected",
        dateLabels: { from: "Rechazo desde", to: "Rechazo hasta" },
        columns: [
          { key: "charge_id", header: "Cobro", kind: "id" },
          { key: "subscription_id", header: "Suscripción", kind: "id" },
          { key: "period", header: "Período", kind: "date" },
          money(),
          { key: "status", header: "Estado", kind: "status" },
          { key: "rejection_code", header: "Código", kind: "id" },
          { key: "rejection_reason", header: "Motivo de rechazo", kind: "reason" },
          { key: "rejection_at", header: "Fecha de rechazo", kind: "date" },
        ],
      },
      {
        id: "recoverable",
        label: "Recuperables",
        path: "/api/v1/recovery/toku/recoverable",
        dateLabels: null,
        reasonFilter: true,
        columns: [
          { key: "subscription_id", header: "Suscripción", kind: "id" },
          { key: "recoverable_reason", header: "Motivo", kind: "recoverableReason" },
          { key: "consecutive_failed_debts", header: "Cuotas impagas seguidas", kind: "number" },
          { key: "payment_method_status", header: "Medio de pago", kind: "status" },
          { key: "last_response_code", header: "Último código", kind: "id" },
          { key: "last_attempt_at", header: "Último intento", kind: "date" },
          { key: "report_generated_at", header: "Reporte del", kind: "date" },
          money(),
        ],
      },
    ],
  },
  tch: {
    id: "tch",
    label: "TCH",
    notice: "Solo lectura: TCH se carga desde el Excel y no admite acciones desde el CRM. «Recuperable» aún no está definido para TCH.",
    views: [
      {
        id: "deleted",
        label: "Mandatos eliminados",
        path: "/api/v1/recovery/tch/deleted",
        dateLabels: { from: "Eliminación desde", to: "Eliminación hasta" },
        columns: [
          { key: "subscription_id", header: "Ficha", kind: "id" },
          { key: "status", header: "Estado", kind: "tchStatus" },
          { key: "started_at", header: "Activación", kind: "date" },
          { key: "cancelled_at", header: "Eliminación", kind: "date" },
          { key: "antiquity_days", header: "Antigüedad (días)", kind: "number" },
          money(),
        ],
      },
      {
        id: "rejected",
        label: "Cargos rechazados",
        path: "/api/v1/recovery/tch/rejected",
        dateLabels: { from: "Cargo desde", to: "Cargo hasta" },
        columns: [
          { key: "charge_id", header: "Cuota", kind: "id" },
          { key: "subscription_id", header: "Ficha", kind: "id" },
          { key: "charge_date", header: "Fecha", kind: "date" },
          money(),
          { key: "status", header: "Estado", kind: "tchStatus" },
          { key: "rejection_code", header: "Código", kind: "id" },
          { key: "rejection_reason", header: "Motivo de rechazo", kind: "reason" },
        ],
      },
    ],
  },
};

/** Texto del estado vacío que explica POR QUÉ no hay filas (`empty_reason` del backend). */
export const EMPTY_REASON_TEXT: Record<string, string> = {
  signals_disabled:
    "Las señales de Toku están desactivadas en este ambiente, así que aún no se calculan las suscripciones recuperables. Cuando se activen y se carguen los reportes de Toku, aparecerán aquí.",
  no_signals: "Aún no hay señales calculadas: carga los reportes de Toku y ejecuta el ETL central para ver las suscripciones recuperables.",
};

export type ChannelFilters = { dateFrom: string; dateTo: string; reason: string };

export const EMPTY_CHANNEL_FILTERS: ChannelFilters = { dateFrom: "", dateTo: "", reason: "" };

/** URL del listado con filtros y paginación; solo envía los filtros que la vista acepta. */
export function channelListPath(view: ChannelView, filters: ChannelFilters, offset: number, limit: number): string {
  const params = new URLSearchParams();
  if (view.dateLabels) {
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
  }
  if (view.reasonFilter && filters.reason) params.set("reason", filters.reason);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return `${view.path}?${params.toString()}`;
}
