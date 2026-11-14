import type { MonthlyStatusEntry } from "../shared/monthly";
import type { Alert } from "../dashboard/alertTypes";

/**
 * Tipos INTERNOS de TCH, en inglés. Las claves en español que entrega el backend (`numero_ficha`, `estado`,
 * `fecha_cargo`…) solo existen en `tchAdapter.ts` (decisión D33); el resto del frontend usa estos tipos.
 * `rut` se conserva a propósito: es el término del dominio chileno (D37).
 */
export type TchSubscription = {
  id: string;
  /** Número de ficha del mandato físico (`numero_ficha`). */
  fileNumber: number;
  mandateNumber: number | null;
  clientRut: string | null;
  bankName: string | null;
  mandateType: string | null;
  accountType: string | null;
  /** Cuenta bancaria ENMASCARADA por el backend (`••••1234`, d199 R1); nunca llega completa. */
  accountNumberMasked: string | null;
  origin: string | null;
  costCenter: string | null;
  recruiter: string | null;
  amount: string | null;
  activationDate: string | null;
  /** Monto equivalente en pesos (`equivalente_pesos`). */
  pesoEquivalent: string | null;
  rejectionDate: string | null;
  deletionDate: string | null;
  endDate: string | null;
  cancellationReason: string | null;
  /** Estado del proveedor (`VIGENTE`, `ELIMINADA`): valor crudo, se traduce con `label("tchStatus")`. */
  status: string;
  lastPaidDate: string | null;
  secondaryStatus: string;
  createdAt: string | null;
  updatedAt: string | null;
};

export type TchTransaction = {
  id: string;
  fileNumber: number;
  period: string | null;
  installmentNumber: string | null;
  totalInstallments: string | null;
  amount: string | null;
  chargeDate: string | null;
  transactionType: string | null;
  /** Estado del proveedor (`ACEPTADA`, `RECHAZADA`): valor crudo. */
  status: string;
  collectingEntity: string | null;
  rejectionReason: string | null;
  sourceFile: string | null;
};

export type TchClient = {
  id: string;
  rut: string;
  firstName: string | null;
  lastName: string | null;
  birthDate: string | null;
  profession: string | null;
  personType: string | null;
  memberType: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  commune: string | null;
  city: string | null;
};

export type TchPage<T> = { total: number; page: number; limit: number; pages: number; items: T[] };
export type TchSubscriptionsPage = TchPage<TchSubscription>;
export type TchTransactionsPage = TchPage<TchTransaction>;
export type TchClientsPage = TchPage<TchClient>;

export type TchSubscriptionDetail = TchSubscription & { transactions: TchTransaction[] };
export type TchTransactionDetail = TchTransaction & { subscription: TchSubscription | null };
export type TchClientDetail = TchClient & { subscriptions: TchSubscription[] };

export type TchKpis = {
  mrr: number;
  arpu: number | null;
  active_clients: number;
  active_subscribers: number;
  churn_rate: number | null;
  ltv: number | null;
  churn_window_label?: string | null;
};

export type TchSummary = {
  subscriptions: { active: number; deleted: number; total: number; activeAmount: number; deletedAmount: number; totalAmount: number };
  transactions: { total: number; accepted: number; rejected: number; rejectionRatePct: number | null; amount: number };
  /** El backend ya entrega estas claves en inglés; `normalizeKpis` las consume tal cual. */
  kpis: TchKpis;
  churnWindowLabel: string | null;
  years: number[];
  monthlyTransactions: MonthlyStatusEntry[];
  transactionsSource: "recaudacion_mensual" | "transacciones" | string | undefined;
  monthlyActivations: MonthlyStatusEntry[];
  monthlyCancellations: MonthlyStatusEntry[];
  activeSubsMonthly: { year: number; month: number; count: number }[];
  churnRateMonthly: { year: number; month: number; rate: number }[];
  lastEtl: { id: string | null; status: string | null; startedAt: string | null; recordsUpserted: number | null };
  alerts: Alert[];
};
