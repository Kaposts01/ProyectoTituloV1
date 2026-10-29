import { getJson } from "../../api";
import type { GeneralSubscriptions, StagingResponse } from "../shared/types";
import type { CancellationChannel } from "./types";

/** Campo por el que se busca: el ID de la suscripción o el RUT del cliente. */
export type SearchField = "id" | "rut";

export type SubscriptionOption = { id: string; status: string | null; clientName: string | null };

const LIMIT = 8;

/** Campo de filtro del listado de staging de cada canal para buscar por RUT del cliente. */
const STAGING_RUT_FIELD: Record<Exclude<CancellationChannel, "tch">, string> = {
  virtualpos1: "social_id", virtualpos2: "social_id", toku: "client_rut", payku: "rut",
};

/**
 * Ruta de búsqueda. Reutiliza los listados que ya existen: el de registros de staging para VirtualPOS, Toku y Payku
 * (`/api/v1/staging/records`) y el consolidado de suscripciones para TCH, que no tiene búsqueda propia.
 */
export function searchPath(channel: CancellationChannel, field: SearchField, query: string): string {
  const q = query.trim();
  if (channel === "tch") {
    return `/api/v1/staging/dashboard/general/subscriptions?${new URLSearchParams({ filter_field: field, query: q, limit: "50", offset: "0" })}`;
  }
  const params = new URLSearchParams({
    source: channel, resource_type: "subscription", filter_field: field === "id" ? "id" : STAGING_RUT_FIELD[channel],
    query: q, limit: String(LIMIT), offset: "0",
  });
  return `/api/v1/staging/records?${params}`;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

export async function searchSubscriptions(channel: CancellationChannel, field: SearchField, query: string, signal?: AbortSignal): Promise<SubscriptionOption[]> {
  if (!query.trim()) return [];
  if (channel === "tch") {
    const data = await getJson<GeneralSubscriptions>(searchPath(channel, field, query), signal);
    return data.items
      .filter((item) => item.platform === "TCH")
      .slice(0, LIMIT)
      .map((item) => ({ id: String(item.id), status: asText(item.status), clientName: asText(item.client) }));
  }
  const data = await getJson<StagingResponse>(searchPath(channel, field, query), signal);
  return data.items.map((record) => ({
    id: record.external_id,
    status: asText(record.payload?.status),
    clientName: asText(record.client_name),
  }));
}
