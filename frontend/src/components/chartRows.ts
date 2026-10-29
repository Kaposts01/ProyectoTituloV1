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
