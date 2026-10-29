/**
 * Adaptador del contrato de `GET /api/v1/dashboard/general` (claves en español, docs/data/dashboard-general.md) a los
 * tipos internos en inglés de `summaryTypes.ts`. ES EL ÚNICO MÓDULO que conoce las claves del backend: cuando el
 * backend las renombre (D33) solo cambia este archivo.
 *
 * Reglas: `null` o ausente es `null` (nunca 0); un canal que no viene (sin permiso) no se agrega; un estado de meta
 * desconocido es «sin meta».
 */
import {
  SUMMARY_CHANNELS,
  type ChurnKpi,
  type MrrKpi,
  type RevenuePoint,
  type SeriesPoint,
  type SummaryChannel,
  type SummaryGoalStatus,
  type SummaryKpi,
  type SummaryKpis,
  type SummarySeries,
  type SummaryUnit,
  type TotalMembersKpi,
  type UnifiedSummary,
} from "./summaryTypes";

type Raw = Record<string, unknown>;

export const SUMMARY_FORMAT_ERROR = "La respuesta del servidor no tiene el formato esperado.";

const isRecord = (value: unknown): value is Raw => typeof value === "object" && value !== null && !Array.isArray(value);
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const rec = (value: unknown): Raw => (isRecord(value) ? value : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const GOAL_STATUS: Record<string, SummaryGoalStatus> = { sin_meta: "none", en_meta: "met", cerca: "near", lejos: "off" };
const UNITS: readonly SummaryUnit[] = ["count", "clp", "pct"];

function unitOf(value: unknown, fallback: SummaryUnit): SummaryUnit {
  return UNITS.includes(value as SummaryUnit) ? (value as SummaryUnit) : fallback;
}

function adaptKpi(raw: unknown, fallbackUnit: SummaryUnit): SummaryKpi {
  const k = rec(raw);
  return {
    value: num(k.valor),
    previousMonthValue: num(k.valor_mes_anterior),
    deltaVsPreviousMonth: num(k.delta_vs_mes_anterior),
    deltaVsPreviousMonthPct: num(k.delta_vs_mes_anterior_pct),
    goal: num(k.meta),
    goalStatus: GOAL_STATUS[String(k.estado_meta)] ?? "none",
    unit: unitOf(k.unidad, fallbackUnit),
  };
}

function adaptChannelMap<T>(raw: unknown, convert: (value: unknown) => T): Partial<Record<SummaryChannel, T>> {
  const source = rec(raw);
  const out: Partial<Record<SummaryChannel, T>> = {};
  for (const channel of SUMMARY_CHANNELS) {
    if (Object.prototype.hasOwnProperty.call(source, channel)) out[channel] = convert(source[channel]);
  }
  return out;
}

function adaptPoints(raw: unknown): SeriesPoint[] {
  return list(raw).map((point) => {
    const p = rec(point);
    return { month: str(p.month) ?? "", value: num(p.valor) };
  });
}

function adaptRevenue(raw: unknown): RevenuePoint[] {
  return list(raw).map((point) => {
    const p = rec(point);
    return { month: str(p.month) ?? "", total: num(p.total), channels: adaptChannelMap(p.canales, num) };
  });
}

function adaptSeries(raw: unknown): SummarySeries {
  const s = rec(raw);
  return {
    months: list(s.months).filter((m): m is string => typeof m === "string"),
    revenueByChannel: adaptRevenue(s.ingreso_por_canal),
    activations: adaptPoints(s.activaciones),
    cancellations: adaptPoints(s.bajas),
    totalMembers: adaptPoints(s.socios_totales),
  };
}

function adaptKpis(raw: unknown): SummaryKpis {
  const k = rec(raw);
  const members = rec(k.socios_totales);
  const churn = rec(k.churn);
  const mrr = rec(k.mrr);
  const totalMembers: TotalMembersKpi = {
    ...adaptKpi(members, "count"),
    note: str(members.socios_totales_nota),
    noteUnit: str(members.socios_totales_unidad),
  };
  const churnKpi: ChurnKpi = {
    ...adaptKpi(churn, "pct"),
    definition: str(churn.churn_definicion),
    windowLabel: str(churn.churn_window_label),
  };
  const mrrKpi: MrrKpi = { ...adaptKpi(mrr, "clp"), byChannel: adaptChannelMap(mrr.por_canal, num) };
  return {
    totalMembers,
    activations: adaptKpi(k.activaciones, "count"),
    cancellations: adaptKpi(k.bajas, "count"),
    netGrowth: adaptKpi(k.crecimiento_neto, "count"),
    churn: churnKpi,
    totalRevenue: adaptKpi(k.ingreso_total, "clp"),
    revenueByChannel: adaptChannelMap(k.ingreso_por_canal, (value) => adaptKpi(value, "clp")),
    yearToDate: adaptKpi(k.acumulado_anio, "clp"),
    collectability: adaptKpi(k.cobrabilidad, "pct"),
    uncollected: adaptKpi(k.no_cobrado, "clp"),
    receivable: adaptKpi(k.por_cobrar, "clp"),
    mrr: mrrKpi,
    arpu: adaptKpi(k.arpu, "clp"),
  };
}

/** Convierte la respuesta cruda del endpoint al modelo interno. Lanza un error en español si no es un objeto. */
export function adaptSummary(raw: unknown): UnifiedSummary {
  if (!isRecord(raw)) throw new Error(SUMMARY_FORMAT_ERROR);
  const quality = rec(raw.calidad_datos);
  const channelSet = new Set(list(raw.channels));
  return {
    month: str(raw.month) ?? "",
    timezone: str(raw.timezone) ?? "America/Santiago",
    generatedAt: str(raw.generated_at),
    isCurrentMonth: raw.is_current_month === true,
    channels: SUMMARY_CHANNELS.filter((channel) => channelSet.has(channel)),
    kpis: adaptKpis(raw.kpis),
    series: adaptSeries(raw.series),
    dataQuality: { activationsWithoutDate: num(quality.altas_sin_fecha) ?? 0, cancellationsWithoutDate: num(quality.bajas_sin_fecha) ?? 0 },
  };
}

/** ¿Hay al menos un KPI con valor (un 0 real cuenta)? Falso = mes sin datos. */
export function hasAnyData(summary: UnifiedSummary): boolean {
  const k = summary.kpis;
  const kpis: SummaryKpi[] = [
    k.totalMembers, k.activations, k.cancellations, k.netGrowth, k.churn, k.totalRevenue, k.yearToDate,
    k.collectability, k.uncollected, k.receivable, k.mrr, k.arpu, ...Object.values(k.revenueByChannel),
  ];
  return kpis.some((kpi) => kpi.value !== null);
}
