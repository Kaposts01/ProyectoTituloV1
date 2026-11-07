import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { useDebouncedValue } from "../../hooks";
import type { GeneralClientDetail } from "./generalClientAdapter";
import type {
  AuthSession, GeneralClients, GeneralSubscriptions,
} from "../shared/types";

/** «summary» = Resumen unificado (features/summary). La vista anterior («classic») se retiró en UX-15. */
export type GeneralView = "summary" | "clients" | "subscriptions" | "charges" | "report";
export type GeneralClientFilter = "all" | "rut" | "name" | "last_name" | "platform" | "email" | "phone";
export type GeneralSubscriptionFilter = "all" | "id" | "rut" | "client" | "platform" | "status";

/** Lo que el dashboard general necesita del resto de AppCore: la sesión y cómo reportar errores. */
export type GeneralDashboardContext = {
  session: AuthSession | null | undefined;
  setError: (message: string | null) => void;
};

/**
 * Estado y carga de las vistas consolidadas (clientes y suscripciones). Se llama desde
 * AppCore para que modo, año, filtros y búsquedas sobrevivan a la navegación como antes de la extracción.
 */
export function useGeneralDashboard(ctx: GeneralDashboardContext) {
  const { session, setError } = ctx;
  const [generalView, setGeneralView] = useState<GeneralView>("summary");
  const [generalClients, setGeneralClients] = useState<GeneralClients | null>(null);
  const [generalClientQuery, setGeneralClientQuery] = useState("");
  const [generalClientFilter, setGeneralClientFilter] = useState<GeneralClientFilter>("all");
  const [generalClientOffset, setGeneralClientOffset] = useState(0);
  /** UX-10 (transitorio): filtros de canal y de estado (con o sin suscripción activa); «» = todos. */
  const [generalClientChannel, setGeneralClientChannel] = useState<"" | "virtualpos" | "toku" | "payku" | "tch">("");
  const [generalClientStatus, setGeneralClientStatus] = useState<"" | "active" | "inactive">("");
  const [generalClientDetail, setGeneralClientDetail] = useState<GeneralClientDetail | null>(null);
  const [generalSubscriptions, setGeneralSubscriptions] = useState<GeneralSubscriptions | null>(null);
  const [generalSubscriptionQuery, setGeneralSubscriptionQuery] = useState("");
  const [generalSubscriptionFilter, setGeneralSubscriptionFilter] = useState<GeneralSubscriptionFilter>("all");
  const [generalSubscriptionOffset, setGeneralSubscriptionOffset] = useState(0);
  const debouncedGeneralClientQuery = useDebouncedValue(generalClientQuery);

  useEffect(() => {
    if (!session || generalView !== "clients") return;
    const params = new URLSearchParams({ limit: "50", offset: String(generalClientOffset), filter_field: generalClientFilter });
    if (generalClientChannel) params.set("canal", generalClientChannel);
    if (generalClientStatus) params.set("status", generalClientStatus);
    if (debouncedGeneralClientQuery.trim()) params.set("query", debouncedGeneralClientQuery.trim());
    const controller = new AbortController();
    getJson<GeneralClients>(`/api/v1/staging/dashboard/general/clients?${params}`, controller.signal)
      .then(setGeneralClients)
      .catch((err: unknown) => { if (err instanceof DOMException && err.name === "AbortError") return; setError(friendlyError(err, "No se pudieron cargar los clientes consolidados.")); });
    return () => controller.abort();
  }, [session, generalView, debouncedGeneralClientQuery, generalClientFilter, generalClientOffset, generalClientChannel, generalClientStatus, setError]);

  // UX-08: /central/suscripciones usa la vista unificada paginada en SQL (features/general/UnifiedSubscriptionsView);
  // ya no se pide la lista consolidada en memoria (/staging/dashboard/general/subscriptions).

  return {
    generalView,
    setGeneralView,
    generalClients,
    setGeneralClients,
    generalClientQuery,
    setGeneralClientQuery,
    generalClientFilter,
    setGeneralClientFilter,
    generalClientOffset,
    generalClientChannel,
    setGeneralClientChannel,
    generalClientStatus,
    setGeneralClientStatus,
    setGeneralClientOffset,
    generalClientDetail,
    setGeneralClientDetail,
    generalSubscriptions,
    setGeneralSubscriptions,
    generalSubscriptionQuery,
    setGeneralSubscriptionQuery,
    generalSubscriptionFilter,
    setGeneralSubscriptionFilter,
    generalSubscriptionOffset,
    setGeneralSubscriptionOffset,
  };
}

export type GeneralState = ReturnType<typeof useGeneralDashboard>;
