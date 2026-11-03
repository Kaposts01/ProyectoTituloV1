/** Subconjunto del payload del dashboard general que usan las tarjetas de KPI (todo opcional / nullable). */
export type GeneralKpiData = {
  pending_payments?: number | null;
  pending_payments_label?: string | null;
  sync_success_rate_pct?: number | null;
  churn_rate_pct?: number | null;
  churn_window_label?: string | null;
  /** Base de los cargos (p. ej. «hasta hoy, hora de Chile»), si el backend la informa. */
  /**
   * `rejection_rate_3m_pct`: tasa de rechazo de los últimos 3 meses, la MISMA ventana y definición que la alerta global
   * «Tasa de rechazo global elevada» (UI-31, d112). Ausente en backends viejos: se recalcula desde los conteos.
   */
  transactions?: { basis_label?: string | null; rejection_rate_3m_pct?: number | null } | null;
};

/** Rótulo de la ventana de la tarjeta de tasa de rechazo (igual al de la alerta global). */
export const REJECTION_WINDOW_CAPTION = "Últimos 3 meses · rechazados / (pagados + rechazados)";

/**
 * Tasa de la tarjeta: la de 3 meses del backend si la informa (aunque sea null = sin base); si no, la calculada con
 * los conteos que recibe la tarjeta (compatibilidad con payloads viejos).
 */
export function cardRejectionRate(data: GeneralKpiData, rejected: number, accepted: number): { value: number | null; windowed: boolean } {
  const tx = data.transactions;
  if (tx && "rejection_rate_3m_pct" in tx) {
    const v = tx.rejection_rate_3m_pct;
    return { value: typeof v === "number" && Number.isFinite(v) ? v : null, windowed: true };
  }
  return { value: rejectionRate(rejected, accepted), windowed: false };
}

/** Tasa de rechazo en % con un decimal; null si no hay transacciones (sin denominador no hay razón). */
export function rejectionRate(rejected: number, accepted: number): number | null {
  const total = rejected + accepted;
  return total > 0 ? Math.round((1000 * rejected) / total) / 10 : null;
}
