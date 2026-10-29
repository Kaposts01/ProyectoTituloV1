/** Subconjunto del payload del dashboard general que usan las tarjetas de KPI (todo opcional / nullable). */
export type GeneralKpiData = {
  pending_payments?: number | null;
  pending_payments_label?: string | null;
  sync_success_rate_pct?: number | null;
  churn_rate_pct?: number | null;
  churn_window_label?: string | null;
  /** Base de los cargos (p. ej. «hasta hoy, hora de Chile»), si el backend la informa. */
  transactions?: { basis_label?: string | null } | null;
};

/** Tasa de rechazo en % con un decimal; null si no hay transacciones (sin denominador no hay razón). */
export function rejectionRate(rejected: number, accepted: number): number | null {
  const total = rejected + accepted;
  return total > 0 ? Math.round((1000 * rejected) / total) / 10 : null;
}
