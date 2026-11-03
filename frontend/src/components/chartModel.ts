import { FLOW_IN_COLOR, FLOW_OUT_COLOR } from "../chartColors";
import type { ChartRowWithLabel } from "./chartRows";

/** Modelo puro de los gráficos de la familia ChannelChart (formato, filas por variante y colores); sin React. */

/** Unidad de las series: conteo, monto en pesos o porcentaje (p. ej. churn mensual). */
export type ChannelChartMode = "count" | "amount" | "percent";

export const NEG = "__neg_";
export const PCT = "__pct_";
export const RANGE = "__range";
export const CUM = "__cum";

/** Formato de un valor según la unidad; `—` si no hay dato (nunca 0 inventado). */
export const fmt = (value: unknown, mode: ChannelChartMode) => {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  if (mode === "amount") return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("es-CL")}`;
  if (mode === "percent") return `${n.toLocaleString("es-CL", { maximumFractionDigits: 1 })} %`;
  return n.toLocaleString("es-CL");
};
export const signed = (value: number, mode: ChannelChartMode) => `${value > 0 ? "+" : ""}${fmt(value, mode)}`;

/** Color de una barra del waterfall: sube en azul (--flow-in), baja en naranja (--flow-out); DEC-36. */
export const waterfallFill = (delta: number) => (delta < 0 ? FLOW_OUT_COLOR : FLOW_IN_COLOR);

export type PlotRow = { year: number; month: number; label: string } & Record<string, unknown>;

export const has = (v: unknown) => v !== undefined && v !== null && Number.isFinite(Number(v));

/** Filas que dibuja Recharts para cada tipo (las originales siguen disponibles en la misma fila). */
export function plotRowsFor(kind: string, rows: ChartRowWithLabel[], series: { key: string }[], waterfallStart = 0): PlotRow[] {
  if (kind === "diverging") {
    return rows.map((r) => {
      const out: PlotRow = { ...r };
      series.slice(1).forEach((s) => { out[`${NEG}${s.key}`] = has(r[s.key]) ? -Math.abs(Number(r[s.key])) : null; });
      return out;
    });
  }
  if (kind === "stacked100") {
    return rows.map((r) => {
      const out: PlotRow = { ...r };
      const total = series.reduce((a, s) => a + (has(r[s.key]) ? Number(r[s.key]) : 0), 0);
      series.forEach((s) => { out[`${PCT}${s.key}`] = total > 0 && has(r[s.key]) ? Math.round((Number(r[s.key]) / total) * 1000) / 10 : null; });
      return out;
    });
  }
  if (kind === "waterfall") {
    const key = series[0]?.key;
    let acc = waterfallStart;
    return rows.map((r) => {
      const delta = key && has(r[key]) ? Number(r[key]) : 0;
      const prev = acc;
      acc += delta;
      return { ...r, __delta: delta, [CUM]: acc, [RANGE]: [Math.min(prev, acc), Math.max(prev, acc)] } as PlotRow;
    });
  }
  return rows.map((r) => ({ ...r }));
}


export type RankingItem = { key: string; label: string; value: number | null; color?: string };

/** Ítems con dato, ordenados de mayor a menor (empate: por etiqueta); los sin dato no se dibujan. */
export function rankItems(items: RankingItem[]): RankingItem[] {
  return items
    .filter((i) => i.value !== null && Number.isFinite(i.value))
    .sort((a, b) => (b.value as number) - (a.value as number) || a.label.localeCompare(b.label, "es"));
}


/** Definición del churn unificado (DEC-37, la misma D31 del resumen). */
export const CHANNEL_CHURN_HELP = "Bajas del mes ÷ socios al inicio del mes";
/** Meses de historia que dibuja la sparkline del churn. */
const CHURN_SPARK_MONTHS = 12;

/** Últimos N valores de la serie mensual del churn, en orden cronológico (sparkline decorativa de la tarjeta D20). */
export function churnSparkline(history: { year: number; month: number; rate: number | null }[] | null | undefined, months = CHURN_SPARK_MONTHS): number[] {
  return [...(history ?? [])]
    .filter((e) => e.rate !== null && Number.isFinite(e.rate))
    .sort((a, b) => a.year - b.year || a.month - b.month)
    .slice(-months)
    .map((e) => e.rate as number);
}

