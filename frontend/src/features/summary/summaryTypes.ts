/**
 * Tipos INTERNOS del resumen unificado (nombres en inglés). El endpoint `GET /api/v1/dashboard/general` responde con
 * claves en español; solo `summaryAdapter.ts` las conoce. Cuando el backend las renombre (D33) cambia el adaptador y
 * nada más.
 */

export type SummaryChannel = "virtualpos" | "toku" | "payku" | "tch";

/** Orden fijo de los canales, el mismo que usa el backend. */
export const SUMMARY_CHANNELS: readonly SummaryChannel[] = ["virtualpos", "toku", "payku", "tch"];

export type SummaryUnit = "count" | "clp" | "pct";

/** `none` = sin meta (hoy siempre; D2 pendiente). Los otros tres están previstos para cuando existan las metas. */
export type SummaryGoalStatus = "none" | "met" | "near" | "off";

export type SummaryKpi = {
  /** `null` = sin dato (se muestra «—»; nunca se inventa un 0). */
  value: number | null;
  previousMonthValue: number | null;
  /** En KPI de unidad `pct` son puntos porcentuales. */
  deltaVsPreviousMonth: number | null;
  deltaVsPreviousMonthPct: number | null;
  goal: number | null;
  goalStatus: SummaryGoalStatus;
  unit: SummaryUnit;
};

export type TotalMembersKpi = SummaryKpi & {
  /** «suma por canal, no deduplicada». */
  note: string | null;
  /** Unidad contada: «suscripciones». */
  noteUnit: string | null;
};

export type ChurnKpi = SummaryKpi & {
  /** Definición propuesta (D31 pendiente de confirmación). */
  definition: string | null;
  windowLabel: string | null;
};

export type MrrKpi = SummaryKpi & {
  byChannel: Partial<Record<SummaryChannel, number | null>>;
};

export type SummaryKpis = {
  totalMembers: TotalMembersKpi;
  activations: SummaryKpi;
  cancellations: SummaryKpi;
  netGrowth: SummaryKpi;
  churn: ChurnKpi;
  totalRevenue: SummaryKpi;
  revenueByChannel: Partial<Record<SummaryChannel, SummaryKpi>>;
  yearToDate: SummaryKpi;
  collectability: SummaryKpi;
  uncollected: SummaryKpi;
  receivable: SummaryKpi;
  mrr: MrrKpi;
  arpu: SummaryKpi;
};

export type SeriesPoint = { month: string; value: number | null };

export type RevenuePoint = {
  month: string;
  total: number | null;
  channels: Partial<Record<SummaryChannel, number | null>>;
};

export type SummarySeries = {
  /** 12 meses ascendentes terminando en el mes pedido, formato `YYYY-MM`. */
  months: string[];
  revenueByChannel: RevenuePoint[];
  activations: SeriesPoint[];
  cancellations: SeriesPoint[];
  totalMembers: SeriesPoint[];
};

export type UnifiedSummary = {
  month: string;
  timezone: string;
  generatedAt: string | null;
  isCurrentMonth: boolean;
  /** Canales efectivos (pedidos y permitidos). Un canal sin permiso no aparece. */
  channels: SummaryChannel[];
  kpis: SummaryKpis;
  series: SummarySeries;
  dataQuality: { activationsWithoutDate: number; cancellationsWithoutDate: number };
};
