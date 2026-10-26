import { fillMonths, pivotByStatus, STATUS_PALETTE, type ChannelChartRow, type PivotSeries, type StatusEntry } from "../../components/chartRows";
import type { ChannelChartAnnotation } from "../../components/ChannelChart";
import { TCH_SOURCE_NOTE } from "../shared/kpis";

export type ChartMode = "count" | "amount";
export type ChartProps = { rows: ChannelChartRow[]; series: PivotSeries[] };
type MonthValue = { year: number; month: number; count?: number; amount?: number };
type StatusValue = MonthValue & { status?: string | null };

const ym = (y: number, m: number) => y * 12 + (m - 1);
const toYm = (id: number) => ({ year: Math.floor(id / 12), month: (id % 12) + 1 });
const ALTAS_COLOR = STATUS_PALETTE[0];
const BAJAS_COLOR = "#DC2626";
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
  const series = [{ key: "count", label: "Suscripciones activas", color: ALTAS_COLOR }];
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

/** Altas vs bajas por mes (suma todos los estados de cada serie). */
export function activationVsChurnChart(
  activations: MonthValue[] | undefined | null,
  churn: MonthValue[] | undefined | null,
  mode: ChartMode,
): ChartProps {
  const series = [
    { key: "altas", label: "Altas", color: ALTAS_COLOR },
    { key: "bajas", label: "Bajas", color: BAJAS_COLOR },
  ];
  const a = sumByMonth(activations, mode);
  const c = sumByMonth(churn, mode);
  const ids = [...new Set([...a.keys(), ...c.keys()])].sort((x, y) => x - y);
  if (!ids.length) return { rows: [], series };
  const rows = ids.map((id) => ({ ...toYm(id), altas: a.get(id) ?? 0, bajas: c.get(id) ?? 0 }));
  return { rows: fillMonths(rows), series };
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
export function tchSourceNote(fuente: string | null | undefined): string | null {
  if (fuente === "recaudacion_mensual") return TCH_SOURCE_NOTE;
  if (fuente === "transacciones") return "Fuente: respaldo desde transacciones individuales (sin reporte mensual oficial)";
  return null;
}
