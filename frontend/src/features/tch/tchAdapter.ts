/**
 * ADAPTADOR de TCH (decisiones D33 y D36): único módulo del frontend que conoce las claves en español del
 * backend (`numero_ficha`, `estado`, `fecha_cargo`…). Convierte cada respuesta a los tipos internos en inglés de
 * `tchTypes.ts`. Tolera valores ausentes: un texto ausente queda en `null` (nunca se inventa un dato), un
 * estado ausente queda en "" y un número de ficha ausente en 0; las listas ausentes quedan vacías.
 */
import type { MonthlyStatusEntry } from "../../MonthlyStatusChart";
import type { DashboardAlert } from "../shared/types";
import type {
  TchClient, TchClientDetail, TchClientsPage, TchKpis, TchPage, TchSubscription, TchSubscriptionDetail,
  TchSubscriptionsPage, TchSummary, TchTransaction, TchTransactionDetail, TchTransactionsPage,
} from "./tchTypes";

// ---- Tipos "wire": SOLO aquí. Todas las claves son opcionales porque el backend puede omitirlas. ----
export type TchSubscriptionWire = {
  id?: string; numero_ficha?: number; numero_mandato?: number | null; cliente_rut?: string | null; banco_nombre?: string | null;
  tipo_mandato?: string | null; tipo_cuenta?: string | null; origen?: string | null; centro_costo?: string | null;
  captador?: string | null; monto?: string | number | null; fecha_activacion?: string | null; equivalente_pesos?: string | number | null;
  fecha_rechazo?: string | null; fecha_eliminacion?: string | null; fecha_fin?: string | null; razon_baja?: string | null;
  estado?: string | null; last_paid_date?: string | null; secondary_status?: string | null; created_at?: string | null; updated_at?: string | null;
  transacciones?: TchTransactionWire[] | null;
};
export type TchTransactionWire = {
  id?: string; numero_ficha?: number; periodo?: string | null; numero_cuota?: string | number | null; total_cuotas?: string | number | null;
  monto?: string | number | null; fecha_cargo?: string | null; tipo_transaccion?: string | null; estado?: string | null;
  entidad_recaudadora?: string | null; razon_rechazo?: string | null; archivo_origen?: string | null;
  suscripcion?: TchSubscriptionWire | null;
};
export type TchClientWire = {
  id?: string; rut?: string; nombre?: string | null; apellido?: string | null; fecha_nacimiento?: string | null; profesion?: string | null;
  tipo_persona?: string | null; tipo_socio?: string | null; telefono?: string | null; email?: string | null; direccion?: string | null;
  comuna?: string | null; ciudad?: string | null; suscripciones?: TchSubscriptionWire[] | null;
};
export type TchPageWire<T> = { total?: number; page?: number; limit?: number; pages?: number; items?: T[] | null };
export type TchSummaryWire = {
  suscripciones?: { vigentes?: number; eliminadas?: number; total?: number; monto_vigentes?: number; monto_eliminadas?: number; monto_total?: number } | null;
  transacciones?: { total?: number; aceptadas?: number; rechazadas?: number; tasa_rechazo_pct?: number | null; monto?: number } | null;
  kpis?: Partial<TchKpis> | null;
  churn_window_label?: string | null;
  years?: number[] | null;
  transacciones_mensuales?: MonthlyStatusEntry[] | null;
  transacciones_fuente?: string | null;
  activaciones_mensuales?: MonthlyStatusEntry[] | null;
  bajas_mensuales?: MonthlyStatusEntry[] | null;
  active_subs_monthly?: { year: number; month: number; count: number }[] | null;
  churn_rate_monthly?: { year: number; month: number; rate: number }[] | null;
  ultimo_etl?: { id?: string | null; status?: string | null; started_at?: string | null; records_upserted?: number | null } | null;
  alerts?: DashboardAlert[] | null;
};

// ---- Utilidades ----
const text = (value: unknown): string | null => (typeof value === "string" ? value : typeof value === "number" ? String(value) : null);
const textOr = (value: unknown, fallback: string): string => text(value) ?? fallback;
const count = (value: unknown, fallback: number): number => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
const countOrNull = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const list = <T>(value: T[] | null | undefined): T[] => (Array.isArray(value) ? value : []);

// ---- Conversión por recurso ----
export function adaptTchSubscription(wire: TchSubscriptionWire | null | undefined): TchSubscription {
  const w = wire ?? {};
  return {
    id: textOr(w.id, ""),
    fileNumber: count(w.numero_ficha, 0),
    mandateNumber: countOrNull(w.numero_mandato),
    clientRut: text(w.cliente_rut),
    bankName: text(w.banco_nombre),
    mandateType: text(w.tipo_mandato),
    accountType: text(w.tipo_cuenta),
    origin: text(w.origen),
    costCenter: text(w.centro_costo),
    recruiter: text(w.captador),
    amount: text(w.monto),
    activationDate: text(w.fecha_activacion),
    pesoEquivalent: text(w.equivalente_pesos),
    rejectionDate: text(w.fecha_rechazo),
    deletionDate: text(w.fecha_eliminacion),
    endDate: text(w.fecha_fin),
    cancellationReason: text(w.razon_baja),
    status: textOr(w.estado, ""),
    lastPaidDate: text(w.last_paid_date),
    secondaryStatus: textOr(w.secondary_status, ""),
    createdAt: text(w.created_at),
    updatedAt: text(w.updated_at),
  };
}

export function adaptTchTransaction(wire: TchTransactionWire | null | undefined): TchTransaction {
  const w = wire ?? {};
  return {
    id: textOr(w.id, ""),
    fileNumber: count(w.numero_ficha, 0),
    period: text(w.periodo),
    installmentNumber: text(w.numero_cuota),
    totalInstallments: text(w.total_cuotas),
    amount: text(w.monto),
    chargeDate: text(w.fecha_cargo),
    transactionType: text(w.tipo_transaccion),
    status: textOr(w.estado, ""),
    collectingEntity: text(w.entidad_recaudadora),
    rejectionReason: text(w.razon_rechazo),
    sourceFile: text(w.archivo_origen),
  };
}

export function adaptTchClient(wire: TchClientWire | null | undefined): TchClient {
  const w = wire ?? {};
  return {
    id: textOr(w.id, ""),
    rut: textOr(w.rut, ""),
    firstName: text(w.nombre),
    lastName: text(w.apellido),
    birthDate: text(w.fecha_nacimiento),
    profession: text(w.profesion),
    personType: text(w.tipo_persona),
    memberType: text(w.tipo_socio),
    phone: text(w.telefono),
    email: text(w.email),
    address: text(w.direccion),
    commune: text(w.comuna),
    city: text(w.ciudad),
  };
}

export function adaptTchSubscriptionDetail(wire: TchSubscriptionWire | null | undefined): TchSubscriptionDetail {
  return { ...adaptTchSubscription(wire), transactions: list(wire?.transacciones).map(adaptTchTransaction) };
}

export function adaptTchTransactionDetail(wire: TchTransactionWire | null | undefined): TchTransactionDetail {
  return { ...adaptTchTransaction(wire), subscription: wire?.suscripcion ? adaptTchSubscription(wire.suscripcion) : null };
}

export function adaptTchClientDetail(wire: TchClientWire | null | undefined): TchClientDetail {
  return { ...adaptTchClient(wire), subscriptions: list(wire?.suscripciones).map(adaptTchSubscription) };
}

function adaptPage<W, T>(wire: TchPageWire<W> | null | undefined, convert: (item: W) => T): TchPage<T> {
  const items = list(wire?.items).map(convert);
  return {
    total: count(wire?.total, items.length),
    page: count(wire?.page, 1),
    limit: count(wire?.limit, items.length),
    pages: count(wire?.pages, 1),
    items,
  };
}

export const adaptTchSubscriptionsPage = (wire: TchPageWire<TchSubscriptionWire> | null | undefined): TchSubscriptionsPage => adaptPage(wire, adaptTchSubscription);
export const adaptTchTransactionsPage = (wire: TchPageWire<TchTransactionWire> | null | undefined): TchTransactionsPage => adaptPage(wire, adaptTchTransaction);
export const adaptTchClientsPage = (wire: TchPageWire<TchClientWire> | null | undefined): TchClientsPage => adaptPage(wire, adaptTchClient);

const ZERO_KPIS: TchKpis = { mrr: 0, arpu: 0, active_clients: 0, active_subscribers: 0, churn_rate: 0, ltv: 0 };

/** Resumen de TCH. Las partes ausentes toman valores neutros (ceros y listas vacías), como hacía `normalizeTchSummary`. */
export function adaptTchSummary(wire: TchSummaryWire | null | undefined): TchSummary {
  const w = wire ?? {};
  const subs = w.suscripciones ?? {};
  const tx = w.transacciones ?? {};
  const etl = w.ultimo_etl ?? {};
  const k = w.kpis;
  const kpis: TchKpis = k
    ? {
        mrr: count(k.mrr, 0), arpu: countOrNull(k.arpu), active_clients: count(k.active_clients, 0),
        active_subscribers: count(k.active_subscribers, 0), churn_rate: countOrNull(k.churn_rate), ltv: countOrNull(k.ltv),
        churn_window_label: text(k.churn_window_label),
      }
    : ZERO_KPIS;
  return {
    subscriptions: {
      active: count(subs.vigentes, 0), deleted: count(subs.eliminadas, 0), total: count(subs.total, 0),
      activeAmount: count(subs.monto_vigentes, 0), deletedAmount: count(subs.monto_eliminadas, 0), totalAmount: count(subs.monto_total, 0),
    },
    transactions: {
      total: count(tx.total, 0), accepted: count(tx.aceptadas, 0), rejected: count(tx.rechazadas, 0),
      rejectionRatePct: countOrNull(tx.tasa_rechazo_pct), amount: count(tx.monto, 0),
    },
    kpis,
    churnWindowLabel: text(w.churn_window_label) ?? text(k?.churn_window_label),
    years: list(w.years),
    monthlyTransactions: list(w.transacciones_mensuales),
    transactionsSource: text(w.transacciones_fuente) ?? undefined,
    monthlyActivations: list(w.activaciones_mensuales),
    monthlyCancellations: list(w.bajas_mensuales),
    activeSubsMonthly: list(w.active_subs_monthly),
    churnRateMonthly: list(w.churn_rate_monthly),
    lastEtl: { id: text(etl.id), status: text(etl.status), startedAt: text(etl.started_at), recordsUpserted: countOrNull(etl.records_upserted) },
    alerts: list(w.alerts),
  };
}

// ---- Detalles provisionales (antes `{ ... } as XDetail`): solo la clave para pedir la ficha completa ----
export const provisionalTchSubscriptionDetail = (fileNumber: number): TchSubscriptionDetail =>
  adaptTchSubscriptionDetail({ numero_ficha: fileNumber });
export const provisionalTchTransactionDetail = (id: string): TchTransactionDetail => adaptTchTransactionDetail({ id });
export const provisionalTchClientDetail = (rut: string): TchClientDetail => adaptTchClientDetail({ rut });
