import { statusColor } from "./statusColors";

export const CHART_PRIMARY = "#2563EB";

/** Colores de CANAL (no de estado). Los estados salen de statusColors.ts. */
const CHANNEL_COLORS: Record<string, string> = {
  VIRTUALPOS: "#2563EB",
  TOKU: "#7C3AED",
  PAYKU: "#CA8A04",
  TCH: "#0891B2",
};

/** Color de una serie cuyo nombre puede ser un canal o un estado: canal -> color de canal; si no, color de estado. */
export function chartStatusColor(status: string | null | undefined): string {
  return CHANNEL_COLORS[String(status ?? "").trim().toUpperCase()] ?? statusColor(status);
}
