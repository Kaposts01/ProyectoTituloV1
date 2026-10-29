/**
 * Filas para `ChannelChart` y miniaturas de las tarjetas, calculadas SOLO con las series de 12 meses del endpoint.
 * Un valor sin dato (`null`) no se escribe en la fila: el gráfico lo deja como hueco y la tabla como «—»; jamás es 0.
 */
import type { ChannelChartRow } from "../../components/ChannelChart";
import { parseMonth } from "./summaryFormat";
import type { RevenuePoint, SeriesPoint, SummaryChannel, SummarySeries } from "./summaryTypes";

export { parseMonth };

function baseRow(month: string): ChannelChartRow | null {
  const parts = parseMonth(month);
  return parts ? ({ year: parts.year, month: parts.month } as ChannelChartRow) : null;
}

/** Ingreso por canal apilado: una columna por canal efectivo. */
export function revenueRows(series: SummarySeries, channels: SummaryChannel[]): ChannelChartRow[] {
  const rows: ChannelChartRow[] = [];
  for (const point of series.revenueByChannel) {
    const row = baseRow(point.month);
    if (!row) continue;
    for (const channel of channels) {
      const value = (point as RevenuePoint).channels[channel];
      if (value !== null && value !== undefined) row[channel] = value;
    }
    rows.push(row);
  }
  return rows;
}

/** Socios totales (área): una sola columna `members`. */
export function membersRows(series: SummarySeries): ChannelChartRow[] {
  const rows: ChannelChartRow[] = [];
  for (const point of series.totalMembers) {
    const row = baseRow(point.month);
    if (!row) continue;
    if (point.value !== null) row.members = point.value;
    rows.push(row);
  }
  return rows;
}

/** Activaciones, bajas y crecimiento neto (activaciones - bajas) por mes. */
export function flowRows(series: SummarySeries): ChannelChartRow[] {
  const cancellations = new Map(series.cancellations.map((point) => [point.month, point.value]));
  const rows: ChannelChartRow[] = [];
  for (const point of series.activations) {
    const row = baseRow(point.month);
    if (!row) continue;
    const down = cancellations.get(point.month) ?? null;
    if (point.value !== null) row.activations = point.value;
    if (down !== null) row.cancellations = down;
    if (point.value !== null && down !== null) row.net = point.value - down;
    rows.push(row);
  }
  return rows;
}

/** Valores numéricos de una serie, sin los meses sin dato (para una miniatura). */
export function sparkValues(points: SeriesPoint[]): number[] {
  return points.flatMap((point) => (point.value === null ? [] : [point.value]));
}

/** Crecimiento neto mensual (activaciones - bajas) para la miniatura; omite los meses a los que les falta alguno. */
export function netGrowthHistory(series: SummarySeries): number[] {
  const cancellations = new Map(series.cancellations.map((point) => [point.month, point.value]));
  return series.activations.flatMap((point) => {
    const down = cancellations.get(point.month);
    return point.value !== null && down !== null && down !== undefined ? [point.value - down] : [];
  });
}

/**
 * Historia del churn para la miniatura: bajas del mes ÷ socios al cierre del mes anterior × 100 (la definición
 * D31 confirmada), calculada con las mismas series. Omite el primer mes y los meses sin base.
 */
export function churnHistory(series: SummarySeries): number[] {
  const cancellations = new Map(series.cancellations.map((point) => [point.month, point.value]));
  const out: number[] = [];
  for (let i = 1; i < series.totalMembers.length; i++) {
    const base = series.totalMembers[i - 1].value;
    const down = cancellations.get(series.totalMembers[i].month);
    if (base === null || base <= 0 || down === null || down === undefined) continue;
    out.push(Math.round((down / base) * 1000) / 10);
  }
  return out;
}
