/** Filas mensuales del backend que alimentan los gráficos (antes vivían en `MonthlyStatusChart.tsx`, borrado en VIZ-06/07). */
export type MonthlyStatusEntry = { year: number; month: number; status?: string | null; count: number; amount: number };
export type MonthlyEntry = { year: number; month: number; count: number; amount: number };
/** Fila por canal del dashboard general. */
export type ChannelRow = { source: string; clients: number; active_subscriptions: number; accepted: number; amount: number };
