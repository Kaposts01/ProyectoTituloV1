import { fillMonths, pivotByStatus, STATUS_PALETTE, type ChannelChartRow, type PivotSeries, type StatusEntry } from "../../components/chartRows";
import type { ChannelChartAnnotation } from "../../components/ChannelChart";
import { TCH_SOURCE_NOTE } from "../shared/kpis";
import { chartStatusColor, FLOW_IN_COLOR, FLOW_OUT_COLOR } from "../../chartColors";
import { label as i18nLabel, normalizeKey } from "../../i18n/label";
import type { RankingItem } from "../../components/chartModel";

export type ChartMode = "count" | "amount";
export type ChartProps = { rows: ChannelChartRow[]; series: PivotSeries[] };
type MonthValue = { year: number; month: number; count?: number; amount?: number };
type StatusValue = MonthValue & { status?: string | null };

const ym = (y: number, m: number) => y * 12 + (m - 1);
const toYm = (id: number) => ({ year: Math.floor(id / 12), month: (id % 12) + 1 });
const ACTIVATIONS_COLOR = STATUS_PALETTE[0];
const NEUTRAL_COLOR = STATUS_PALETTE[1];

const valueOf = (entry: MonthValue, mode: ChartMode): number => Number(entry[mode] ?? 0) || 0;

/** Cargos/transacciones apilados por estado. Estados nulos se agrupan en "Sin estado". */
export function statusStackedChart(entries: StatusValue[] | undefined | null, mode: ChartMode): ChartProps {
  if (!entries?.length) return { rows: [], series: [] };
  const mapped: StatusEntry[] = entries.map((e) => ({
    year: e.year,
    month: e.month,
    status: String(e.status ?? "").trim() || "Sin estado",
    [mode]: valueOf(e, mode),
  }));
  const { rows, series } = pivotByStatus(mapped);
  return { rows: fillMonths(rows), series };
}

/** Suscripciones activas acumuladas: los meses sin movimiento arrastran el valor anterior. */
export function activeSubsLineChart(entries: { year: number; month: number; count: number }[] | undefined | null): ChartProps {
  const series = [{ key: "count", label: "Suscripciones activas", color: ACTIVATIONS_COLOR }];
  if (!entries?.length) return { rows: [], series };
  const sorted = [...entries].sort((a, b) => ym(a.year, a.month) - ym(b.year, b.month));
  const byMonth = new Map(sorted.map((e) => [ym(e.year, e.month), e.count]));
  const last = sorted[sorted.length - 1];
  const rows: ChannelChartRow[] = [];
  let carried = 0;
  for (let id = ym(sorted[0].year, sorted[0].month); id <= ym(last.year, last.month); id++) {
    carried = byMonth.get(id) ?? carried;
    rows.push({ ...toYm(id), count: carried });
  }
  return { rows, series };
}

const sumByMonth = (entries: MonthValue[] | undefined | null, mode: ChartMode): Map<number, number> => {
  const out = new Map<number, number>();
  for (const e of entries ?? []) out.set(ym(e.year, e.month), (out.get(ym(e.year, e.month)) ?? 0) + valueOf(e, mode));
  return out;
};

/** VirtualPOS: «SUSCRIPCION_FALLIDA» nunca fue una alta real (mismo criterio que el backend). */
const realActivations = (entries: StatusValue[] | undefined | null): StatusValue[] =>
  (entries ?? []).filter((e) => String(e.status ?? "").toUpperCase() !== "SUSCRIPCION_FALLIDA");

/** Altas vs bajas por mes (suma todos los estados de cada serie, sin suscripciones fallidas). */
export function activationVsChurnChart(
  activations: StatusValue[] | undefined | null,
  churn: MonthValue[] | undefined | null,
  mode: ChartMode,
): ChartProps {
  const series = [
    { key: "activations", label: "Altas", color: FLOW_IN_COLOR },
    { key: "cancellations", label: "Bajas", color: FLOW_OUT_COLOR },
  ];
  const a = sumByMonth(realActivations(activations), mode);
  const c = sumByMonth(churn, mode);
  const ids = [...new Set([...a.keys(), ...c.keys()])].sort((x, y) => x - y);
  if (!ids.length) return { rows: [], series };
  const rows = ids.map((id) => ({ ...toYm(id), activations: a.get(id) ?? 0, cancellations: c.get(id) ?? 0 }));
  return { rows: fillMonths(rows), series };
}

/** Línea de crecimiento neto (altas − bajas) que acompaña a las barras de altas y bajas. */
export const NET_GROWTH_SERIES = { key: "net", label: "Crecimiento neto", color: "var(--series-6)" };

/** Altas y bajas con la columna `net` (altas − bajas) para la línea superpuesta o el waterfall. */
export function activationVsChurnWithNet(
  activations: StatusValue[] | undefined | null,
  churn: MonthValue[] | undefined | null,
  mode: ChartMode,
): ChartProps {
  const base = activationVsChurnChart(activations, churn, mode);
  return { series: base.series, rows: base.rows.map((r) => ({ ...r, net: (r.activations ?? 0) - (r.cancellations ?? 0) })) };
}

/**
 * «Crecimiento real mensual» como waterfall (VIZ-06): cada mes sube o baja según altas − bajas, desde el acumulado
 * del mes anterior del período mostrado.
 */
export function netGrowthChart(
  activations: StatusValue[] | undefined | null,
  churn: MonthValue[] | undefined | null,
  mode: ChartMode,
): ChartProps {
  const series = [{ ...NET_GROWTH_SERIES, color: FLOW_IN_COLOR }];
  const withNet = activationVsChurnWithNet(activations, churn, mode);
  return { series, rows: withNet.rows.map((r) => ({ year: r.year, month: r.month, net: r.net })) };
}

/** «Churn mensual (%)» (VIZ-06): serie en porcentaje con la definición unificada (DEC-37, D31). */
export const CHURN_RATE_SERIES = { key: "rate", label: "Churn mensual", color: "var(--series-1)" };
export function churnRateChart(entries: { year: number; month: number; rate: number | null }[] | undefined | null): ChartProps {
  const rows = (entries ?? [])
    .filter((e) => e.rate !== null && Number.isFinite(e.rate))
    .map((e) => ({ year: e.year, month: e.month, rate: e.rate as number }))
    .sort((a, b) => ym(a.year, a.month) - ym(b.year, b.month));
  return { rows, series: [CHURN_RATE_SERIES] };
}

const CHANNEL_KEYS = new Set(["virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"]);
const isChannelKey = (raw: string) => CHANNEL_KEYS.has(normalizeKey(raw).replace(/ /g, ""));

/**
 * Filas `{year, month, status}` cuyo `status` puede ser un CANAL (dashboard general) o un estado, apiladas por mes.
 * Un canal toma su color y rótulo de canal; un estado, los del mapa único de estados.
 */
export function seriesStackedChart(entries: StatusValue[] | undefined | null, mode: ChartMode): ChartProps {
  const base = statusStackedChart(entries, mode);
  return {
    rows: base.rows,
    series: base.series.map((s) => (isChannelKey(s.key) ? { ...s, label: i18nLabel("channel", s.key), color: chartStatusColor(s.key) } : s)),
  };
}

/** Suma por categoría de un año (null = todo) para un ranking (p. ej. motivos de rechazo). */
export function rankingByStatus(entries: StatusValue[] | undefined | null, mode: ChartMode, year: number | null): RankingItem[] {
  const totals = new Map<string, number>();
  for (const e of entries ?? []) {
    if (year !== null && e.year !== year) continue;
    const key = String(e.status ?? "").trim() || "Sin estado";
    totals.set(key, (totals.get(key) ?? 0) + valueOf(e, mode));
  }
  return [...totals.entries()].map(([key, value]) => ({ key, label: key, value }));
}

/** Tendencia mensual simple (una serie) desde filas {year, month, count, amount}. */
export function monthlyTrendChart(entries: MonthValue[] | undefined | null, mode: ChartMode, label: string): ChartProps {
  const series = [{ key: mode, label, color: NEUTRAL_COLOR }];
  if (!entries?.length) return { rows: [], series };
  const rows = [...sumByMonth(entries, mode).entries()]
    .sort((x, y) => x[0] - y[0])
    .map(([id, v]) => ({ ...toYm(id), [mode]: v }));
  return { rows: fillMonths(rows), series };
}

/** Toku: tendencia de cobros (transacciones) desde `activity`. */
export const tokuCollectionsChart = (activity: MonthValue[] | undefined | null, mode: ChartMode): ChartProps =>
  monthlyTrendChart(activity, mode, mode === "amount" ? "Monto cobrado" : "Cobros");

/** Toku: foto actual de métodos de pago por estado (no es serie mensual). */
export function paymentMethodSnapshot(statuses: { resource: string; status: string; count: number }[] | undefined | null) {
  return (statuses ?? []).filter((s) => s.resource === "payment_method");
}

/** Agrupa meses sin cobros consecutivos en una sola banda. */
export function coverageGapAnnotations(
  gaps: { year: number; month: number }[] | undefined | null,
  label = "Sin cobros",
): ChannelChartAnnotation[] {
  const ids = [...new Set((gaps ?? []).map((g) => ym(g.year, g.month)))].sort((a, b) => a - b);
  const out: ChannelChartAnnotation[] = [];
  let start: number | null = null;
  let prev = 0;
  for (const id of ids) {
    if (start !== null && id === prev + 1) {
      prev = id;
      continue;
    }
    if (start !== null) out.push({ from: toYm(start), to: toYm(prev), label });
    start = id;
    prev = id;
  }
  if (start !== null) out.push({ from: toYm(start), to: toYm(prev), label });
  return out;
}

/** Nota de fuente de las transacciones de TCH. */
export function tchSourceNote(source: string | null | undefined): string | null {
  if (source === "recaudacion_mensual") return TCH_SOURCE_NOTE;
  if (source === "transacciones") return "Fuente: respaldo desde transacciones individuales (sin reporte mensual oficial)";
  return null;
}
