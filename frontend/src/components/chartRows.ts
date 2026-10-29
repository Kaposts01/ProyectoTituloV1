export type ChannelChartRow = { year: number; month: number } & Record<string, number>;
export type ChartRowWithLabel = { year: number; month: number; label: string; [key: string]: number | string };

const MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

/** Filtra por año (null = todos), ordena por año/mes y agrega la etiqueta del eje X. */
export function buildChartRows(data: ChannelChartRow[], year: number | null): ChartRowWithLabel[] {
  return data
    .filter((row) => year === null || row.year === year)
    .sort((a, b) => a.year - b.year || a.month - b.month)
    .map((row) => ({ ...row, label: year === null ? `${MONTHS[row.month - 1]} ${String(row.year).slice(2)}` : MONTHS[row.month - 1] }));
}

export type YearMonth = { year: number; month: number };
export type StatusEntry = { year: number; month: number; status: string; count?: number; amount?: number };
export type PivotSeries = { key: string; label: string; color: string };

import { statusColor } from "../statusColors";

/** Paleta genérica para series que NO son un estado (altas, tendencia). El color de un estado sale de statusColors.ts. */
export const STATUS_PALETTE = ["#2a7a64", "#2563EB", "#D97706", "#7C3AED", "#DC2626", "#0891B2", "#DB2777", "#65A30D", "#94a3b8"];

const ym = (y: number, m: number) => y * 12 + (m - 1);

/** Convierte filas {year, month, status, count|amount} en filas anchas (una columna por estado) y series con color estable. */
export function pivotByStatus(entries: StatusEntry[]): { rows: ChannelChartRow[]; series: PivotSeries[] } {
  const statuses = [...new Set(entries.map((e) => e.status))].sort((a, b) => a.localeCompare(b, "es"));
  const byMonth = new Map<number, ChannelChartRow>();
  for (const e of entries) {
    const id = ym(e.year, e.month);
    let row = byMonth.get(id);
    if (!row) {
      row = { year: e.year, month: e.month } as ChannelChartRow;
      for (const s of statuses) row[s] = 0;
      byMonth.set(id, row);
    }
    row[e.status] += e.count ?? e.amount ?? 0;
  }
  const rows = [...byMonth.values()].sort((a, b) => a.year - b.year || a.month - b.month);
  const series = statuses.map((s) => ({ key: s, label: s, color: statusColor(s) }));
  return { rows, series };
}

/** Rellena con ceros los meses faltantes entre from y to (por defecto, el rango de los datos). */
export function fillMonths(rows: ChannelChartRow[], from?: YearMonth, to?: YearMonth): ChannelChartRow[] {
  if (rows.length === 0 && !(from && to)) return [];
  const ids = rows.map((r) => ym(r.year, r.month));
  const start = from ? ym(from.year, from.month) : Math.min(...ids);
  const end = to ? ym(to.year, to.month) : Math.max(...ids);
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => k !== "year" && k !== "month");
  const existing = new Map(rows.map((r) => [ym(r.year, r.month), r]));
  const out: ChannelChartRow[] = [];
  for (let id = start; id <= end; id++) {
    const found = existing.get(id);
    if (found) {
      out.push({ ...found });
      continue;
    }
    const row = { year: Math.floor(id / 12), month: (id % 12) + 1 } as ChannelChartRow;
    for (const k of keys) row[k] = 0;
    out.push(row);
  }
  return out;
}

/** Rango del selector de evolución. */
export type ChartRange = "12m" | "year" | "all";

/** % entero de `total` sobre `target`; null si no hay meta válida (>0) o el total no es finito. */
export function pctOfTarget(total: number, target: number | null | undefined): number | null {
  if (target === null || target === undefined || !Number.isFinite(target) || target <= 0 || !Number.isFinite(total)) return null;
  return Math.round((total / target) * 100);
}

/**
 * Recorta filas mensuales según el rango, tomando como «hoy» el último dato (determinista, sin reloj):
 * «12m» = 12 meses de calendario terminados en el último dato; «year» = año del último dato; «all» = todo.
 * Pensado para componer con `<ChannelChart year={null} />`.
 */
export function filterByRange(data: ChannelChartRow[], range: ChartRange): ChannelChartRow[] {
  const sorted = [...data].sort((a, b) => a.year - b.year || a.month - b.month);
  if (sorted.length === 0 || range === "all") return sorted;
  const last = sorted[sorted.length - 1];
  if (range === "year") return sorted.filter((r) => r.year === last.year);
  const end = last.year * 12 + (last.month - 1);
  return sorted.filter((r) => r.year * 12 + (r.month - 1) > end - 12);
}

export type CumulativeRow = { year: number; month: number; label: string; real: number | null; pace: number | null; projection: number | null };

/**
 * Serie acumulada del año contra el ritmo de la meta y la proyección.
 * - real: suma acumulada de `keys` hasta el último mes con dato (null después).
 * - pace: meta anual repartida en 12 meses (null sin meta).
 * - projection: promedio mensual real extrapolado desde el último mes con dato (null antes).
 * `year` null = último año con datos; un año sin datos devuelve [].
 */
export function buildCumulativeRows(data: ChannelChartRow[], keys: string[], opts: { year: number | null; annualTarget?: number | null }): CumulativeRow[] {
  if (data.length === 0) return [];
  const year = opts.year ?? Math.max(...data.map((r) => r.year));
  const inYear = data.filter((r) => r.year === year);
  if (inYear.length === 0) return [];
  const monthly = new Map<number, number>();
  for (const r of inYear) monthly.set(r.month, keys.reduce((acc, k) => acc + (Number.isFinite(r[k]) ? r[k] : 0), 0));
  const lastMonth = Math.max(...monthly.keys());
  const target = opts.annualTarget !== undefined && opts.annualTarget !== null && Number.isFinite(opts.annualTarget) ? opts.annualTarget : null;
  let acc = 0;
  let realAtLast = 0;
  const rows: CumulativeRow[] = [];
  for (let m = 1; m <= 12; m++) {
    acc += monthly.get(m) ?? 0;
    if (m === lastMonth) realAtLast = acc;
    rows.push({ year, month: m, label: MONTHS[m - 1], real: m <= lastMonth ? acc : null, pace: target === null ? null : (target / 12) * m, projection: null });
  }
  const avg = realAtLast / lastMonth;
  for (const row of rows) if (row.month >= lastMonth) row.projection = row.month === lastMonth ? realAtLast : avg * row.month;
  return rows;
}
