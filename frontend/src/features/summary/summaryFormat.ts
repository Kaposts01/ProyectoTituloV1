/** Utilidades puras de fecha del resumen unificado (meses `YYYY-MM`, hora de Chile). */

export type YearMonthParts = { year: number; month: number };

/** `YYYY-MM` a año y mes; null si no tiene esa forma o el mes no está entre 1 y 12. */
export function parseMonth(value: string): YearMonthParts | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return null;
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? { year: Number(match[1]), month } : null;
}

/** Suma `delta` meses a un `YYYY-MM` (negativo = hacia atrás). Un valor inválido se devuelve igual. */
export function shiftMonth(value: string, delta: number): string {
  const parts = parseMonth(value);
  if (!parts) return value;
  const index = parts.year * 12 + (parts.month - 1) + delta;
  const year = Math.floor(index / 12);
  return `${String(year).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** «octubre de 2026». Un valor inválido se devuelve tal cual. */
export function monthLabel(value: string): string {
  const parts = parseMonth(value);
  if (!parts) return value;
  return new Date(Date.UTC(parts.year, parts.month - 1, 1)).toLocaleDateString("es-CL", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** Fecha «15-10-2026» en hora de Chile a partir de un ISO 8601; null si falta o no es una fecha. */
export function formatDataDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return null;
  const parts = new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "America/Santiago" }).formatToParts(new Date(time));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("day")}-${pick("month")}-${pick("year")}`;
}

/** Fecha «dd-mm-aaaa» del último dato de TCH (llega por Excel) según la salud de sincronización; null si no se sabe. */
export function tchDataDate(health: { tch?: { last_finished_at: string | null } }): string | null {
  return formatDataDate(health.tch?.last_finished_at);
}

/** Día del mes de hoy en hora de Chile (1–31), a partir de un instante en milisegundos (por defecto, el del servidor). */
export function chileDayOfMonth(now: number): number {
  const day = new Intl.DateTimeFormat("es-CL", { day: "numeric", timeZone: "America/Santiago" }).format(new Date(now));
  return Number(day);
}
