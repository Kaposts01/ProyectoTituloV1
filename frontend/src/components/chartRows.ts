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
