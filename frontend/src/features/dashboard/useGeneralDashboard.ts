import { useState } from "react";
import { cleanParams, useUnifiedGet } from "../general/useUnifiedList";
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
  const { session } = ctx;
  const [generalView, setGeneralView] = useState<GeneralView>("summary");
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

  const clients = useUnifiedGet<GeneralClients>("/api/v1/staging/dashboard/general/clients", cleanParams({
    limit: 50, offset: generalClientOffset, filter_field: generalClientFilter, canal: generalClientChannel,
    status: generalClientStatus, query: debouncedGeneralClientQuery,
  }), Boolean(session) && generalView === "clients", session?.user);
  const generalClients = clients.data;
  const generalClientsLoading = clients.loading || generalClientQuery !== debouncedGeneralClientQuery;

  // UX-08: /central/suscripciones usa la vista unificada paginada en SQL (features/general/UnifiedSubscriptionsView);
  // ya no se pide la lista consolidada en memoria (/staging/dashboard/general/subscriptions).

  return {
    generalView,
    setGeneralView,
    generalClients,
    generalClientsLoading,
    generalClientsError: clients.error,
    generalClientsForbidden: clients.forbidden,
    reloadGeneralClients: clients.reload,
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
