import { useEffect, useState } from "react";
import { getJson, friendlyError } from "../../api";
import { getCachedOrFetch } from "../../apiCache";
import { useDebouncedValue } from "../../hooks";
import type { ProviderSection } from "../../routes";
import { defaultYear } from "../shared/utils";
import type { ChargeFilter } from "./applyChargeFilter";
import type { GeneralClientDetail } from "./generalClientAdapter";
import type {
  AuthSession, GeneralClients, GeneralDashboard, GeneralSubscriptions, Summary,
} from "../shared/types";

/** «summary» = Resumen unificado (features/summary); «classic» = vista anterior del dashboard general (transitoria, UX-15). */
export type GeneralView = "summary" | "classic" | "clients" | "subscriptions" | "charges" | "report";
export type GeneralClientFilter = "all" | "rut" | "name" | "last_name" | "platform" | "email" | "phone";
export type GeneralSubscriptionFilter = "all" | "id" | "rut" | "client" | "platform" | "status";

/** Lo que el dashboard general necesita saber del resto de AppCore (qué vista está activa y cómo reportar errores). */
export type GeneralDashboardContext = {
  session: AuthSession | null | undefined;
  channel: string | null;
  activeSection: ProviderSection | null;
  tchView: string | null;
  adminOpen: boolean;
  profileView: "summary" | "edit" | null;
  lastEtlFinishedAt: string | null | undefined;
  setError: (message: string | null) => void;
  setLoading: (loading: boolean) => void;
};

/**
 * Estado y carga del dashboard general (resumen, clientes y suscripciones consolidados). Se llama desde
 * AppCore para que modo, año, filtros y búsquedas sobrevivan a la navegación como antes de la extracción.
 */
export function useGeneralDashboard(ctx: GeneralDashboardContext) {
  const { session, channel, activeSection, tchView, adminOpen, profileView, lastEtlFinishedAt, setError, setLoading } = ctx;
  const [summary, setSummary] = useState<Summary>({ sources: [] });
  const [generalData, setGeneralData] = useState<GeneralDashboard | null>(null);
  const [generalView, setGeneralView] = useState<GeneralView>("summary");
  const [generalClients, setGeneralClients] = useState<GeneralClients | null>(null);
  const [generalClientQuery, setGeneralClientQuery] = useState("");
  const [generalClientFilter, setGeneralClientFilter] = useState<GeneralClientFilter>("all");
  const [generalClientOffset, setGeneralClientOffset] = useState(0);
  const [generalClientDetail, setGeneralClientDetail] = useState<GeneralClientDetail | null>(null);
  const [generalSubscriptions, setGeneralSubscriptions] = useState<GeneralSubscriptions | null>(null);
  const [generalSubscriptionQuery, setGeneralSubscriptionQuery] = useState("");
  const [generalSubscriptionFilter, setGeneralSubscriptionFilter] = useState<GeneralSubscriptionFilter>("all");
  const [generalSubscriptionOffset, setGeneralSubscriptionOffset] = useState(0);
  const [summaryRefreshing, setSummaryRefreshing] = useState(false);
  const [generalRefreshing, setGeneralRefreshing] = useState(false);
  const [generalMode, setGeneralMode] = useState<"count" | "amount">("count");
  const [generalYear, setGeneralYear] = useState<number | null>(null);
  const [debtFilter, setDebtFilter] = useState<ChargeFilter>("all");
  const [transactionFilter, setTransactionFilter] = useState<ChargeFilter>("all");
  const debouncedGeneralClientQuery = useDebouncedValue(generalClientQuery);

  useEffect(() => {
    if (!session || generalView !== "classic" || channel || activeSection || tchView || adminOpen || profileView) return;
    let mounted = true;
    getCachedOrFetch("staging:summary", 5 * 60 * 1000, () => getJson<Summary>("/api/v1/staging/summary"))
      .then((data) => {
        if (!mounted) return;
        setSummary(data);
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el resumen de staging."));
      })
      .finally(() => {
        if (mounted) { setLoading(false); setSummaryRefreshing(false); }
      });
    return () => {
      mounted = false;
    };
  }, [session, generalView, channel, activeSection, tchView, adminOpen, profileView, setError, setLoading]);

  useEffect(() => {
    if (!session || generalView !== "classic" || channel || activeSection || tchView || adminOpen || profileView) return;
    let mounted = true;
    getCachedOrFetch("dashboard:general", 5 * 60 * 1000, () => getJson<GeneralDashboard>("/api/v1/staging/dashboard/general"))
      .then((data) => {
        if (!mounted) return;
        setGeneralData(data);
        setGeneralYear((current) => current ?? defaultYear(data.years));
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el dashboard general."));
      })
      .finally(() => { if (mounted) setGeneralRefreshing(false); });
    return () => {
      mounted = false;
    };
  }, [session, generalView, channel, activeSection, tchView, adminOpen, profileView, lastEtlFinishedAt, setError]);

  useEffect(() => {
    if (!session || generalView !== "clients") return;
    const params = new URLSearchParams({ limit: "100", offset: String(generalClientOffset), filter_field: generalClientFilter });
    if (debouncedGeneralClientQuery.trim()) params.set("query", debouncedGeneralClientQuery.trim());
    const controller = new AbortController();
    getJson<GeneralClients>(`/api/v1/staging/dashboard/general/clients?${params}`, controller.signal)
      .then(setGeneralClients)
      .catch((err: unknown) => { if (err instanceof DOMException && err.name === "AbortError") return; setError(friendlyError(err, "No se pudieron cargar los clientes consolidados.")); });
    return () => controller.abort();
  }, [session, generalView, debouncedGeneralClientQuery, generalClientFilter, generalClientOffset, setError]);

  // UX-08: /central/suscripciones usa la vista unificada paginada en SQL (features/general/UnifiedSubscriptionsView);
  // ya no se pide la lista consolidada en memoria (/staging/dashboard/general/subscriptions).

  return {
    summary,
    setSummary,
    generalData,
    setGeneralData,
    generalView,
    setGeneralView,
    generalClients,
    setGeneralClients,
    generalClientQuery,
    setGeneralClientQuery,
    generalClientFilter,
    setGeneralClientFilter,
    generalClientOffset,
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
    summaryRefreshing,
    setSummaryRefreshing,
    generalRefreshing,
    setGeneralRefreshing,
    generalMode,
    setGeneralMode,
    generalYear,
    setGeneralYear,
    debtFilter,
    setDebtFilter,
    transactionFilter,
    setTransactionFilter,
  };
}

export type GeneralState = ReturnType<typeof useGeneralDashboard>;
