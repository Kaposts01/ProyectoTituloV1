import { statusColor } from "./statusColors";

/** Color principal de un gráfico de una sola serie (D19/D27: violeta de la paleta de series, claro y oscuro). */
export const CHART_PRIMARY = "var(--series-1)";

/**
 * Altas y bajas (DEC-36): azul y naranja neutros, nunca el verde/rojo de estado. Las bajas no se confunden con el rojo
 * de «rechazado» ni con el gris de «cancelado» (UI-33). También son los tramos positivo/negativo de waterfall y
 * barras divergentes.
 */
export const FLOW_IN_COLOR = "var(--flow-in)";
export const FLOW_OUT_COLOR = "var(--flow-out)";

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
