import { statusColor } from "./statusColors";

/** Color principal de un gráfico de una sola serie (D19/D27: violeta de la paleta de series, claro y oscuro). */
export const CHART_PRIMARY = "var(--series-1)";

/** Colores de CANAL (no de estado), como tokens `--series-N` (index.css). Los estados salen de statusColors.ts. */
const CHANNEL_COLORS: Record<string, string> = {
  VIRTUALPOS: "var(--series-1)",
  TOKU: "var(--series-2)",
  PAYKU: "var(--series-4)",
  TCH: "var(--series-3)",
};

/** Color de una serie cuyo nombre puede ser un canal o un estado: canal -> color de canal; si no, color de estado. */
export function chartStatusColor(status: string | null | undefined): string {
  return CHANNEL_COLORS[String(status ?? "").trim().toUpperCase()] ?? statusColor(status);
}
