/** Cliente HTTP del resumen unificado: reutiliza `getJson` de api.ts y entrega el modelo interno ya adaptado. */
import { ApiError, getJson } from "../../api";
import { adaptSummary } from "./summaryAdapter";
import type { SummaryChannel, UnifiedSummary } from "./summaryTypes";

export const SUMMARY_ENDPOINT = "/api/v1/dashboard/general";

export type SummaryQuery = {
  /** `YYYY-MM`; sin valor, el servidor usa el mes actual (hora de Chile). */
  month?: string;
  /** Sin valor, todos los canales permitidos. Una lista vacía no se envía. */
  channels?: SummaryChannel[];
};

export function buildSummaryPath(query: SummaryQuery): string {
  const params = new URLSearchParams();
  if (query.month) params.set("month", query.month);
  if (query.channels && query.channels.length > 0) params.set("channels", query.channels.join(","));
  const search = params.toString();
  return search ? `${SUMMARY_ENDPOINT}?${search}` : SUMMARY_ENDPOINT;
}

/** Mensajes en español para los 422 con código del endpoint (el texto del backend no se muestra). */
const VALIDATION_MESSAGES: Record<string, string> = {
  invalid_month: "El mes no es válido. Usa el formato AAAA-MM, por ejemplo 2026-10.",
  invalid_channel: "Alguno de los canales pedidos no es válido.",
};
const VALIDATION_FALLBACK = "Los filtros del resumen no son válidos. Cambia el mes o los canales e inténtalo de nuevo.";

export async function fetchSummary(query: SummaryQuery, signal?: AbortSignal): Promise<UnifiedSummary> {
  try {
    return adaptSummary(await getJson<unknown>(buildSummaryPath(query), signal));
  } catch (error) {
    if (error instanceof ApiError && error.status === 422) {
      throw new ApiError((error.code && VALIDATION_MESSAGES[error.code]) || VALIDATION_FALLBACK, error.status, error.detail);
    }
    throw error;
  }
}
