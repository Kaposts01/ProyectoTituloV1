/** Contratos de las vistas unificadas de Cartera (`/api/v1/general/...`, UX-08, UX-09, UX-10). */

export type UnifiedPage<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  /** Total por proveedor (virtualpos, toku, payku, tch) con los filtros activos. */
  by_channel: Record<string, number>;
  /** Canales (valor de `canal`) que el usuario puede ver en esta entidad. */
  canales: string[];
};

export type StatusFacet = { status: string; count: number };
export type StatusFacets = { statuses: StatusFacet[]; canales: string[] };

export type SubscriptionRow = {
  channel: string;
  subscription_id: string;
  status: string | null;
  secondary_status: string | null;
  start_date: string | null;
  end_date: string | null;
  amount: string | number | null;
  currency: string | null;
  last_charge: string | null;
  rut: string | null;
  name: string | null;
};

export type ChargeRow = {
  channel: string;
  charge_id: string;
  subscription_id: string | null;
  status: string | null;
  charge_date: string | null;
  period: string | null;
  amount: string | number | null;
  currency: string | null;
  rejection_reason: string | null;
  rut: string | null;
  name: string | null;
};

export type PaymentRow = {
  channel: string;
  payment_id: string;
  charge_id: string | null;
  status: string | null;
  payment_date: string | null;
  amount: string | number | null;
  currency: string | null;
  rut: string | null;
  name: string | null;
};

export type RejectionChannel = {
  channel: string;
  label: string;
  basis: "cargos" | "transacciones";
  basis_label: string;
  paid: number;
  rejected: number;
  evaluable: number;
  rate: number | null;
};

export type RejectionSummary = {
  today: string;
  channels: RejectionChannel[];
  total: { paid: number; rejected: number; evaluable: number; rate: number | null };
};

export type ChargeOutcome = "paid" | "rejected" | "pending" | "excluded" | "other";
export const CHARGE_OUTCOMES: ChargeOutcome[] = ["paid", "rejected", "pending", "excluded", "other"];

/** Permisos de vista por canal de cada entidad (los mismos que exige el backend; ver export_queries.ENTITY_SPECS). */
export const VIEW_PERMISSIONS = {
  subscriptions: ["virtualpos.subscriptions.view", "toku.subscriptions.view", "payku.subscriptions.view", "tch.suscripciones.view"],
  charges: ["virtualpos.charges.view", "toku.invoices.view", "tch.transacciones.view"],
  payments: ["virtualpos.payments.view", "toku.transactions.view", "payku.transactions.view"],
  members: ["virtualpos.clients.view", "toku.customers.view", "payku.clients.view", "tch.clientes.view"],
} as const;

export const canAny = (can: (permission: string) => boolean, permissions: readonly string[]): boolean =>
  permissions.some((permission) => can(permission));
