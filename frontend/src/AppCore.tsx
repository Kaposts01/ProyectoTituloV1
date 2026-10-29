import { Component, Suspense, useEffect, useEffectEvent, useRef, useState, type FormEvent, type ReactNode } from "react";
import { getCached, getCachedOrFetch, setCached, invalidateCache } from "./apiCache";
import { setCsrfToken, getJson, postJson, putJson, deleteJson, friendlyError } from "./api";
import { useDebouncedValue } from "./hooks";
import { useChannelHealth } from "./hooks/useChannelHealth";
import { Sidebar } from "./components/Sidebar";
import { providerGroups, resourcePermission } from "./navigation";
import type { ProviderSection } from "./routes";
import "./App.css";
import "./Staging.css";
import { ActivacionCaidaChart, ChannelKpiChart, ChurnMensualChart, CrecimientoMensualChart, IngresosMensualesChart, MonthlyStatusChart } from "./MonthlyStatusChart";
import type { ChannelRow, MonthlyEntry } from "./MonthlyStatusChart";
import { OperationalAlerts } from "./features/dashboard/OperationalAlerts";
import { GeneralKpis } from "./features/dashboard/GeneralKpis";
import { legacyRedirectPath, parseRoute, routePath, type AppRoute, type ProviderSource } from "./routes";
import { AutomaticReport } from "./AutomaticReport";
// Feature modules
import type {
  Summary, StagingRecord, StagingResponse, TableColumn,
  ChannelDashboard, VirtualPosClientDetail, VirtualPosPlanDetail,
  VirtualPosSubscriptionDetail, VirtualPosChargeDetail, VirtualPosPaymentDetail, ProviderRecordDetail,
  SortDirection, EtlRun, AuthSession, TchSummary,
  GeneralDashboard, GeneralClients, GeneralSubscriptions, GeneralClientDetail,
  TchSuscripcionesResp, TchTransaccionesResp, TchClientesResp, TchSuscripcionDetail, TchTransaccionDetail,
  TchClienteDetail,
} from "./features/shared/types";
import {
  RECORDS_PAGE_SIZE, normalizeTchSummary, aggregateChurn, defaultYear,
  refreshCsrfToken, text,
  documentType, normalizeRut, fieldLabel, providerRecordHeading,
  externalUrl, renewalText, cardTypeText, isActiveSubscription, isPendingCharge, isRejectedCharge,
  nested, objectEntries, title, resourceTitle,
} from "./features/shared/utils";
import {
  virtualPosClientFields, virtualPosClientFieldLabels, virtualPosDocumentTypes, recurringFieldLabels,
  virtualPosPlanFields, virtualPosSubscriptionFields, virtualPosClientEditFields,
  virtualPosPlanCreateFields, planDefaultValues, virtualPosSubscriptionCreateFields, subscriptionRequiredFields,
  providerEditFields, deletableResources, deleteEndpoint, stagingFilters, filterFieldForColumn, virtualPosFieldForColumn,
} from "./features/virtualpos/constants";
import { virtualPosColumns, tokuColumns, tokuRelatedColumns, paykuColumns, virtualPosClientName, vpClientRecordName } from "./features/virtualpos/columns";
import { VirtualPosDetailTable } from "./features/virtualpos/VirtualPosDetailTable";
import { TokuPaymentMethodProfile } from "./features/toku/TokuPaymentMethodProfile";
import { LoginScreen } from "./features/auth/LoginScreen";
import { ProfilePanel } from "./features/auth/ProfilePanel";
import { RecoveryPanel } from "./features/recovery/RecoveryPanel";
import { BillingInbox } from "./features/billing/BillingInbox";
import { AdminPanel } from "./features/admin/AdminPanel";
import { Metric } from "./features/dashboard/Metric";
import { KpiCard } from "./components/KpiCard";
import { ChannelKpiStrip } from "./components/ChannelKpiStrip";
import { ChannelChart } from "./components/ChannelChart";
import { activationVsChurnChart, statusStackedChart, tchSourceNote } from "./features/dashboard/channelCharts";
import { normalizeKpis } from "./features/shared/kpis";
import { useEnabledChannels } from "./features/shared/environment";
import { ChannelDashboardView } from "./features/dashboard/ChannelDashboardView";
import { ReportDialog } from "./features/dashboard/ReportDialog";
import { applyChargeFilter } from "./features/dashboard/applyChargeFilter";


class ContentErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-shell">
          <p className="error-message">No se pudo mostrar esta vista.</p>
          <button className="sync-btn" onClick={() => window.location.reload()}>Recargar aplicación</button>
        </main>
      );
    }
    return this.props.children;
  }
}


function AppCore() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [routeLocation, setRouteLocation] = useState(() => window.location.pathname + window.location.search);
  const [adminOpen, setAdminOpen] = useState(false);
  const [adminTab, setAdminTab] = useState<"usuarios" | "sincronizacion">("usuarios");
  const [summary, setSummary] = useState<Summary>({ sources: [] });
  const [generalData, setGeneralData] = useState<GeneralDashboard | null>(null);
  const [generalView, setGeneralView] = useState<"summary" | "clients" | "subscriptions" | "report">("summary");
  const [generalClients, setGeneralClients] = useState<GeneralClients | null>(null);
  const [generalClientQuery, setGeneralClientQuery] = useState("");
  const [generalClientFilter, setGeneralClientFilter] = useState<"all" | "rut" | "name" | "last_name" | "platform" | "email" | "phone">("all");
  const [generalClientOffset, setGeneralClientOffset] = useState(0);
  const [generalClientDetail, setGeneralClientDetail] = useState<GeneralClientDetail | null>(null);
  const [generalSubscriptions, setGeneralSubscriptions] = useState<GeneralSubscriptions | null>(null);
  const [generalSubscriptionQuery, setGeneralSubscriptionQuery] = useState("");
  const [generalSubscriptionFilter, setGeneralSubscriptionFilter] = useState<"all" | "id" | "rut" | "client" | "platform" | "status">("all");
  const [generalSubscriptionOffset, setGeneralSubscriptionOffset] = useState(0);
  const [activeSection, setActiveSection] = useState<ProviderSection | null>(
    null,
  );
  const [channel, setChannel] = useState<string | null>(null);
  const [channelData, setChannelData] = useState<ChannelDashboard | null>(null);
  const [openProvider, setOpenProvider] = useState<string | null>("VirtualPOS");
  const [records, setRecords] = useState<StagingResponse>({
    items: [],
    total: 0,
    offset: 0,
    limit: RECORDS_PAGE_SIZE,
  });
  const [recordsOffset, setRecordsOffset] = useState(0);
  const [statusValues, setStatusValues] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [channelLoading, setChannelLoading] = useState(false);
  const [summaryRefreshing, setSummaryRefreshing] = useState(false);
  const [generalRefreshing, setGeneralRefreshing] = useState(false);
  const [channelRefreshing, setChannelRefreshing] = useState(false);
  const [tchRefreshing, setTchRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [clientDetail, setClientDetail] =
    useState<VirtualPosClientDetail | null>(null);
  const [planDetail, setPlanDetail] = useState<VirtualPosPlanDetail | null>(
    null,
  );
  const [subscriptionDetail, setSubscriptionDetail] =
    useState<VirtualPosSubscriptionDetail | null>(null);
  const [chargeDetail, setChargeDetail] = useState<VirtualPosChargeDetail | null>(null);
  const [paymentDetail, setPaymentDetail] = useState<VirtualPosPaymentDetail | null>(null);
  const [providerRecordDetail, setProviderRecordDetail] =
    useState<ProviderRecordDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editingClient, setEditingClient] = useState<StagingRecord | null>(null);
  const [creatingClient, setCreatingClient] = useState(false);
  const [clientVpPlatform, setClientVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingClient, setSavingClient] = useState(false);
  const [clientFormError, setClientFormError] = useState<string | null>(null);
  const [clientFieldErrors, setClientFieldErrors] = useState<Record<string, string>>({});
  const [clientSaveNotice, setClientSaveNotice] = useState<string | null>(null);
  const [creatingPlan, setCreatingPlan] = useState(false);
  const [planVpPlatform, setPlanVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingPlan, setSavingPlan] = useState(false);
  const [planFormError, setPlanFormError] = useState<string | null>(null);
  const [planFieldErrors, setPlanFieldErrors] = useState<Record<string, string>>({});
  const [planSaveNotice, setPlanSaveNotice] = useState<string | null>(null);
  const [creatingSubscription, setCreatingSubscription] = useState(false);
  const [subVpPlatform, setSubVpPlatform] = useState<"virtualpos1" | "virtualpos2">("virtualpos1");
  const [savingSubscription, setSavingSubscription] = useState(false);
  const [subscriptionFormError, setSubscriptionFormError] = useState<string | null>(null);
  const [subscriptionFieldErrors, setSubscriptionFieldErrors] = useState<Record<string, string>>({});
  const [subscriptionSaveNotice, setSubscriptionSaveNotice] = useState<string | null>(null);
  const [cancelingSubscription, setCancelingSubscription] = useState<StagingRecord | null>(null);
  const [savingCancelSubscription, setSavingCancelSubscription] = useState(false);
  const [cancelSubscriptionError, setCancelSubscriptionError] = useState<string | null>(null);
  const [creatingCharge, setCreatingCharge] = useState<StagingRecord | null>(null);
  const [savingCharge, setSavingCharge] = useState(false);
  const [chargeFormError, setChargeFormError] = useState<string | null>(null);
  const [chargeFieldErrors, setChargeFieldErrors] = useState<Record<string, string>>({});
  const [chargeSaveNotice, setChargeSaveNotice] = useState<string | null>(null);
  const [cancelingCharge, setCancelingCharge] = useState<StagingRecord | null>(null);
  const [savingCancelCharge, setSavingCancelCharge] = useState(false);
  const [cancelChargeError, setCancelChargeError] = useState<string | null>(null);
  const [retryingCharge, setRetryingCharge] = useState<StagingRecord | null>(null);
  const [savingRetryCharge, setSavingRetryCharge] = useState(false);
  const [retryChargeError, setRetryChargeError] = useState<string | null>(null);
  const [editingProviderRecord, setEditingProviderRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderEdit, setSavingProviderEdit] = useState(false);
  const [providerEditError, setProviderEditError] = useState<string | null>(null);
  const [deletingRecord, setDeletingRecord] = useState<{
    record: StagingRecord;
    source: string;
    resourceType: string;
  } | null>(null);
  const [savingProviderDelete, setSavingProviderDelete] = useState(false);
  const [providerDeleteError, setProviderDeleteError] = useState<string | null>(null);
  const [managingTokuSub, setManagingTokuSub] = useState<StagingRecord | null>(null);
  const [savingTokuSubStatus, setSavingTokuSubStatus] = useState(false);
  const [tokuSubStatusError, setTokuSubStatusError] = useState<string | null>(null);
  const [filterField, setFilterField] = useState("");
  const [filterQuery, setFilterQuery] = useState("");
  const [vpColumnFilters, setVpColumnFilters] = useState<Record<string, string>>({});
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"count" | "amount">("count");
  const [year, setYear] = useState<number | null>(null);
  const [generalMode, setGeneralMode] = useState<"count" | "amount">("count");
  const [generalYear, setGeneralYear] = useState<number | null>(null);
  const [reportScope, setReportScope] = useState<string | null>(null);
  const [debtFilter, setDebtFilter] = useState<"todas" | "pagada" | "rechazada">("todas");
  const [transFilter, setTransFilter] = useState<"todas" | "pagada" | "rechazada">("todas");
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [billingOpen, setBillingOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("crm-theme") as "light" | "dark") ?? "light";
  });
  const [etlRunning, setEtlRunning] = useState(false);
  const [lastEtlRun, setLastEtlRun] = useState<EtlRun | null>(null);
  const [etlError, setEtlError] = useState<string | null>(null);
  const [vpPlatform, setVpPlatform] = useState<"all" | "virtualpos1" | "virtualpos2">("all");
  const { isEnabled: isChannelEnabled } = useEnabledChannels();
  const vp2Enabled = isChannelEnabled("virtualpos2");
  useEffect(() => {
    if (vp2Enabled) return;
    setClientVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setPlanVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setSubVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
  }, [vp2Enabled]);
  const [tchView, setTchView] = useState<"summary" | "clientes" | "suscripciones" | "transacciones" | "cliente-detalle" | "suscripcion-detalle" | "transaccion-detalle" | null>(null);
  const [tchSummary, setTchSummary] = useState<TchSummary | null>(null);
  const [tchSuscripciones, setTchSuscripciones] = useState<TchSuscripcionesResp | null>(null);
  const [tchTransacciones, setTchTransacciones] = useState<TchTransaccionesResp | null>(null);
  const [tchClientes, setTchClientes] = useState<TchClientesResp | null>(null);
  const [tchLoading, setTchLoading] = useState(false);
  const [tchError, setTchError] = useState<string | null>(null);
  const [tchSusPage, setTchSusPage] = useState(1);
  const [tchTransPage, setTchTransPage] = useState(1);
  const [tchSusFiltroEstado, setTchSusFiltroEstado] = useState("");
  const [tchClienteFiltro, setTchClienteFiltro] = useState("");
  const [tchClientesPage, setTchClientesPage] = useState(1);
  const [tchTransFiltroPeriodo, setTchTransFiltroPeriodo] = useState("");
  const [tchMode, setTchMode] = useState<"count" | "amount">("count");
  const [tchYear, setTchYear] = useState<number | null>(null);
  const [tchSuscripcionDetail, setTchSuscripcionDetail] = useState<TchSuscripcionDetail | null>(null);
  const [tchTransaccionDetail, setTchTransaccionDetail] = useState<TchTransaccionDetail | null>(null);
  const [tchClienteDetail, setTchClienteDetail] = useState<TchClienteDetail | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const burgerRef = useRef<HTMLButtonElement>(null);
  const channelHealth = useChannelHealth(Boolean(session));
  const closeSidebar = () => {
    setSidebarOpen(false);
    burgerRef.current?.focus();
  };
  const [profileView, setProfileView] = useState<"summary" | "edit" | null>(null);
  const debouncedGeneralClientQuery = useDebouncedValue(generalClientQuery);
  const debouncedGeneralSubscriptionQuery = useDebouncedValue(generalSubscriptionQuery);
  const debouncedFilterQuery = useDebouncedValue(filterQuery);
  const debouncedVpColumnFilters = useDebouncedValue(vpColumnFilters);

  const can = (permission: string) => (session?.user?.permissions ?? []).includes(permission);

  useEffect(() => {
    getJson<AuthSession>("/api/v1/auth/me")
      .then((current) => { setCsrfToken(current.csrf_token); setSession(current); })
      .catch(() => setSession(null));
  }, []);

  useEffect(() => {
    if (!session) return;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("crm-theme", theme);
  }, [theme, session]);

  const toggleTheme = () => setTheme(t => t === "light" ? "dark" : "light");

  useEffect(() => {
    if (!session || generalView !== "summary" || channel || activeSection || tchView || adminOpen || profileView) return;
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
  }, [session, generalView, channel, activeSection, tchView, adminOpen, profileView]);

  useEffect(() => {
    if (!session || generalView !== "summary" || channel || activeSection || tchView || adminOpen || profileView) return;
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
  }, [session, generalView, channel, activeSection, tchView, adminOpen, profileView, lastEtlRun?.finished_at]);

  useEffect(() => {
    if (!session || generalView !== "clients") return;
    const params = new URLSearchParams({ limit: "100", offset: String(generalClientOffset), filter_field: generalClientFilter });
    if (debouncedGeneralClientQuery.trim()) params.set("query", debouncedGeneralClientQuery.trim());
    const controller = new AbortController();
    getJson<GeneralClients>(`/api/v1/staging/dashboard/general/clients?${params}`, controller.signal)
      .then(setGeneralClients)
      .catch((err: unknown) => { if (err instanceof DOMException && err.name === "AbortError") return; setError(friendlyError(err, "No se pudieron cargar los clientes consolidados.")); });
    return () => controller.abort();
  }, [session, generalView, debouncedGeneralClientQuery, generalClientFilter, generalClientOffset]);

  useEffect(() => {
    if (!session || generalView !== "subscriptions") return;
    const params = new URLSearchParams({ limit: "100", offset: String(generalSubscriptionOffset), filter_field: generalSubscriptionFilter });
    if (debouncedGeneralSubscriptionQuery.trim()) params.set("query", debouncedGeneralSubscriptionQuery.trim());
    const controller = new AbortController();
    getJson<GeneralSubscriptions>(`/api/v1/staging/dashboard/general/subscriptions?${params}`, controller.signal)
      .then(setGeneralSubscriptions)
      .catch((err: unknown) => { if (err instanceof DOMException && err.name === "AbortError") return; setError(friendlyError(err, "No se pudieron cargar las suscripciones consolidadas.")); });
    return () => controller.abort();
  }, [session, generalView, debouncedGeneralSubscriptionQuery, generalSubscriptionFilter, generalSubscriptionOffset]);

  useEffect(() => {
    if (!session || !activeSection) return;
    if (filterQuery !== debouncedFilterQuery) return;
    let mounted = true;
    const controller = new AbortController();
    const effectiveSource =
      activeSection.source === "virtualpos" && vpPlatform !== "all"
        ? vpPlatform
        : activeSection.source;
    const params = new URLSearchParams({
      source: effectiveSource,
      resource_type: activeSection.resource,
      offset: String(recordsOffset),
      limit: String(RECORDS_PAGE_SIZE),
    });
    const effectiveFilterQuery = filterQuery ? debouncedFilterQuery : "";
    if (activeSection.source === "virtualpos") {
      for (const [field, value] of Object.entries(debouncedVpColumnFilters)) {
        if (!value.trim()) continue;
        if (field.endsWith("_min") || field.endsWith("_max") || field.endsWith("_from") || field.endsWith("_to")) {
          params.set(field, value.trim());
        } else {
          params.append("filters", `${field}:${value.trim()}`);
        }
      }
    } else if (filterField && effectiveFilterQuery.trim()) {
      params.set("filter_field", filterField);
      params.set("query", effectiveFilterQuery.trim());
    }
    const sortField = sortColumn
      ? filterFieldForColumn(activeSection.source, activeSection.resource, sortColumn)
      : null;
    if (sortField) {
      params.set("sort_field", sortField);
      params.set("sort_direction", sortDirection);
    }
    const path = `/api/v1/staging/records?${params}`;
    setLoading(true);
    getJson<StagingResponse>(path, controller.signal)
      .then((data) => {
        if (mounted) {
          setRecords((current) => recordsOffset === 0
            ? data
            : { ...data, items: [...current.items, ...data.items.filter((item) => !current.items.some((existing) => existing.id === item.id))] });
        }
      })
      .catch((err: unknown) => {
        if (mounted && !(err instanceof DOMException && err.name === "AbortError")) setError(friendlyError(err, "No se pudieron cargar los registros."));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [session, activeSection, filterField, filterQuery, debouncedFilterQuery, debouncedVpColumnFilters, sortColumn, sortDirection, vpPlatform, recordsOffset]);

  useEffect(() => {
    if (!session || !activeSection || !["status", "secondary_status"].includes(filterField)) {
      setStatusValues([]);
      return;
    }
    const source = activeSection.source === "virtualpos" && vpPlatform !== "all"
      ? vpPlatform
      : activeSection.source;
    const params = new URLSearchParams({
      source,
      resource_type: activeSection.resource,
      filter_field: filterField,
    });
    getJson<{ values: string[] }>(`/api/v1/staging/records/filter-values?${params}`)
      .then((data) => setStatusValues(data.values))
      .catch((err: unknown) => setError(friendlyError(err, "No se pudieron cargar los estados.")));
  }, [session, activeSection, filterField, vpPlatform]);

  useEffect(() => {
    if (!session || !channel) return;
    const cacheKey = `dashboard:${channel}`;
    let mounted = true;
    getCachedOrFetch(cacheKey, 5 * 60 * 1000, () => getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${channel}`))
      .then((data) => {
        if (!mounted) return;
        setChannelData(data);
        setYear(defaultYear(data.years));
      })
      .catch((err: unknown) => {
        if (mounted) setError(friendlyError(err, "No se pudo cargar el dashboard del canal."));
      })
      .finally(() => {
        if (mounted) { setChannelLoading(false); setChannelRefreshing(false); }
      });
    return () => {
      mounted = false;
    };
  }, [session, channel]);

  useEffect(() => {
    if (!session || !tchView) return;
    let mounted = true;
    setTchError(null);
    if (tchView === "summary") {
      const cached = getCached<TchSummary>("tch:summary", 10 * 60 * 1000);
      if (cached) {
        const summary = normalizeTchSummary(cached);
        setTchSummary(summary);
        setTchYear((current) => current ?? defaultYear(summary.years));
        setTchLoading(false);
        return () => { mounted = false; };
      }
      setTchLoading(true);
      getJson<TchSummary>("/api/v1/tch/summary")
        .then((d) => {
          if (!mounted) return;
          const summary = normalizeTchSummary(d);
          setCached("tch:summary", summary);
          setTchSummary(summary);
          setTchYear((current) => current ?? defaultYear(summary.years));
        })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar el resumen TCH.")); })
        .finally(() => { if (mounted) { setTchLoading(false); setTchRefreshing(false); } });
    } else if (tchView === "clientes") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchClientesPage) });
      if (tchClienteFiltro) params.set("nombre", tchClienteFiltro);
      getJson<TchClientesResp>(`/api/v1/tch/clientes?${params}`)
        .then((d) => { if (mounted) setTchClientes(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar los clientes TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "50", page: String(tchSusPage) });
      if (tchSusFiltroEstado) params.set("estado", tchSusFiltroEstado);
      getJson<TchSuscripcionesResp>(`/api/v1/tch/suscripciones?${params}`)
        .then((d) => { if (mounted) setTchSuscripciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las suscripciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transacciones") {
      setTchLoading(true);
      const params = new URLSearchParams({ limit: "100", page: String(tchTransPage) });
      if (tchTransFiltroPeriodo) params.set("periodo", tchTransFiltroPeriodo);
      getJson<TchTransaccionesResp>(`/api/v1/tch/transacciones?${params}`)
        .then((d) => { if (mounted) setTchTransacciones(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudieron cargar las transacciones TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "suscripcion-detalle" && tchSuscripcionDetail) {
      setTchLoading(true);
      getJson<TchSuscripcionDetail>(`/api/v1/tch/suscripciones/${tchSuscripcionDetail.numero_ficha}`)
        .then((d) => { if (mounted) setTchSuscripcionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "transaccion-detalle" && tchTransaccionDetail) {
      setTchLoading(true);
      getJson<TchTransaccionDetail>(`/api/v1/tch/transacciones/${tchTransaccionDetail.id}`)
        .then((d) => { if (mounted) setTchTransaccionDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    } else if (tchView === "cliente-detalle" && tchClienteDetail) {
      setTchLoading(true);
      getJson<TchClienteDetail>(`/api/v1/tch/clientes/${encodeURIComponent(tchClienteDetail.rut)}`)
        .then((d) => { if (mounted) setTchClienteDetail(d); })
        .catch((err: unknown) => { if (mounted) setTchError(friendlyError(err, "No se pudo cargar la ficha del cliente TCH.")); })
        .finally(() => { if (mounted) setTchLoading(false); });
    }
    return () => { mounted = false; };
  }, [session, tchView, tchClientesPage, tchClienteFiltro, tchSusPage, tchSusFiltroEstado, tchTransPage, tchTransFiltroPeriodo, tchSuscripcionDetail?.numero_ficha, tchTransaccionDetail?.id, tchClienteDetail?.rut]);

  useEffect(() => {
    setClientFormError(null);
    setClientFieldErrors({});
    setClientSaveNotice(null);
  }, [editingClient?.id, creatingClient]);

  function clearDetails() {
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setProviderRecordDetail(null);
  }

  async function saveVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingClient || savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const changes: Record<string, string> = {};
    for (const field of virtualPosClientEditFields) {
      const rawValue = String(formData.get(field.name) ?? "").trim();
      const value = field.name === "social_id_type" ? documentType(rawValue) : rawValue;
      const current = field.name === "social_id_type"
        ? documentType(editingClient.payload[field.name])
        : text(editingClient.payload[field.name], "");
      if (value !== current) changes[field.name] = value;
    }
    const selectedDocumentType = documentType(formData.get("social_id_type"));
    if (selectedDocumentType === "1" && (changes.social_id || changes.social_id_type)) {
      const rut = normalizeRut(String(formData.get("social_id") ?? ""));
      if (!rut) {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados.");
        return;
      }
      if (changes.social_id) changes.social_id = rut;
    }
    if (changes.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(changes.email)) {
      setClientFieldErrors({ email: "Ingresa un correo electrónico válido." });
      setClientFormError("Revisa los campos marcados.");
      return;
    }
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote !== text(editingClient.payload.private_note, "")) changes.private_note = privateNote;
    if (!Object.keys(changes).length) {
      setClientFormError("No hay cambios para guardar.");
      return;
    }

    const clientId = text(editingClient.payload.uuid, editingClient.external_id);
    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const updated = await putJson<{ payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/clients/${encodeURIComponent(clientId)}`,
        changes,
      );
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) => (
          record.id === editingClient.id ? { ...record, payload: updated.payload } : record
        )),
      }));
      setClientDetail((current) => current && current.client.id === editingClient.id
        ? { ...current, client: { ...current.client, payload: updated.payload } }
        : current);
      setEditingClient(null);
      setClientSaveNotice("Cambios guardados correctamente.");
    } catch (saveError) {
      const message = friendlyError(saveError, "No se pudo guardar el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingClient) return;
    setClientFormError(null);
    setClientFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const fieldErrors: Record<string, string> = {};

    const rawValues = Object.fromEntries(
      virtualPosClientEditFields.map((field) => [field.name, String(formData.get(field.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.first_name) fieldErrors.first_name = "El nombre es obligatorio.";
    if (!rawValues.email) {
      fieldErrors.email = "El correo electrónico es obligatorio.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(rawValues.email)) {
      fieldErrors.email = "Ingresa un correo electrónico válido.";
    }
    if (!rawValues.social_id_type) {
      fieldErrors.social_id_type = "Selecciona el tipo de documento.";
    }
    if (!rawValues.social_id) {
      fieldErrors.social_id = "El número de documento es obligatorio.";
    }

    const socialIdType = documentType(rawValues.social_id_type);
    if (!fieldErrors.social_id && rawValues.social_id) {
      if (socialIdType === "1") {
        const rut = normalizeRut(rawValues.social_id);
        if (!rut) fieldErrors.social_id = "El RUT no es válido. Ejemplo: 12345678-9";
        else rawValues.social_id = rut;
      } else if (socialIdType === "2") {
        if (rawValues.social_id.length < 5) fieldErrors.social_id = "El DNI debe tener al menos 5 caracteres.";
      }
    }

    if (rawValues.phone_number && !/^\+?[\d\s\-()]{7,20}$/.test(rawValues.phone_number)) {
      fieldErrors.phone_number = "Ingresa un teléfono válido.";
    }

    if (Object.keys(fieldErrors).length) {
      setClientFieldErrors(fieldErrors);
      setClientFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const normalizedSocialId = socialIdType === "1" ? normalizeRut(rawValues.social_id) ?? rawValues.social_id : rawValues.social_id;
    const duplicate = records.items.find((item) => {
      const itemSocial = String(item.payload.social_id ?? "");
      return itemSocial && itemSocial === normalizedSocialId;
    });
    if (duplicate) {
      setClientFieldErrors({ social_id: "Ya existe un cliente con este documento en el listado actual." });
      setClientFormError("Ya existe un cliente con ese documento de identidad en VirtualPOS.");
      return;
    }

    const client: Record<string, string> = {};
    for (const [key, value] of Object.entries(rawValues)) {
      if (value !== "") client[key] = value;
    }
    if (client.social_id_type) client.social_id_type = socialIdType;
    const privateNote = String(formData.get("private_note") ?? "").trim();
    if (privateNote) client.private_note = privateNote;
    client.platform = clientVpPlatform;

    setSavingClient(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/clients",
        client,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "client", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingClient(false);
      setClientSaveNotice("Cliente creado correctamente.");
    } catch (createError) {
      const message = friendlyError(createError, "No se pudo crear el cliente.");
      if (message === "Invalid RUT") {
        setClientFieldErrors({ social_id: "El RUT no es válido." });
        setClientFormError("Revisa los campos marcados en rojo.");
      } else {
        setClientFormError(message);
      }
    } finally {
      setSavingClient(false);
    }
  }

  async function createVirtualPOSPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingPlan) return;
    setPlanFormError(null);
    setPlanFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const rawValues = Object.fromEntries(
      virtualPosPlanCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    if (!rawValues.name) errors.name = "El nombre del plan es obligatorio.";
    const amount = rawValues.amount === "" ? NaN : Number(rawValues.amount);
    if (rawValues.amount === "" || isNaN(amount) || amount < 0) errors.amount = "Ingresa un monto válido (número ≥ 0).";
    if (!rawValues.currency) errors.currency = "Selecciona una moneda.";
    if (!rawValues.frequency_type) errors.frequency_type = "Selecciona la frecuencia de cobro.";

    const trialDays = rawValues.trial_days ? Number(rawValues.trial_days) : undefined;
    if (rawValues.trial_days && (isNaN(trialDays!) || trialDays! < 0)) errors.trial_days = "Los días de prueba deben ser un número ≥ 0.";
    const numCharges = rawValues.num_charges ? Number(rawValues.num_charges) : undefined;
    if (rawValues.num_charges && (isNaN(numCharges!) || numCharges! < 0)) errors.num_charges = "El número de cobros debe ser ≥ 0.";
    const fixedDay = rawValues.fixed_amount_day_charge ? Number(rawValues.fixed_amount_day_charge) : undefined;
    if (rawValues.fixed_amount_day_charge && (isNaN(fixedDay!) || fixedDay! < 1 || fixedDay! > 28)) errors.fixed_amount_day_charge = "El día de cobro debe ser entre 1 y 28.";
    const activationAmount = rawValues.activation_amount ? Number(rawValues.activation_amount) : undefined;
    if (rawValues.activation_amount && (isNaN(activationAmount!) || activationAmount! < 0)) errors.activation_amount = "El monto de activación debe ser ≥ 0.";

    if (Object.keys(errors).length) {
      setPlanFieldErrors(errors);
      setPlanFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = { platform: planVpPlatform, name: rawValues.name, amount, currency: rawValues.currency, frequency_type: rawValues.frequency_type };
    if (rawValues.description) body.description = rawValues.description;
    if (trialDays !== undefined) body.trial_days = trialDays;
    if (numCharges !== undefined) body.num_charges = numCharges;
    if (fixedDay !== undefined) body.fixed_amount_day_charge = fixedDay;
    if (activationAmount !== undefined) body.activation_amount = activationAmount;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal === "true";
    if (rawValues.show_in_terminal) body.show_in_terminal = rawValues.show_in_terminal === "true";
    if (rawValues.is_active) body.is_active = rawValues.is_active === "true";
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.suscription_url) body.suscription_url = rawValues.suscription_url;
    if (rawValues.type) body.type = rawValues.type;

    setSavingPlan(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/plans",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "plan", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingPlan(false);
      setPlanSaveNotice("Plan creado correctamente.");
    } catch (err) {
      setPlanFormError(friendlyError(err, "No se pudo crear el plan."));
    } finally {
      setSavingPlan(false);
    }
  }

  async function createVirtualPOSSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingSubscription) return;
    setSubscriptionFormError(null);
    setSubscriptionFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const rawValues = Object.fromEntries(
      virtualPosSubscriptionCreateFields.map((f) => [f.name, String(formData.get(f.name) ?? "").trim()] as const),
    ) as Record<string, string>;

    const errors: Record<string, string> = {};
    if (!rawValues.plan_id) errors.plan_id = "El ID del plan es obligatorio.";
    if (!rawValues.email) errors.email = "El email es obligatorio.";
    if (!rawValues.first_name) errors.first_name = "El nombre es obligatorio.";
    if (!rawValues.last_name) errors.last_name = "El apellido es obligatorio.";
    if (!rawValues.social_id) errors.social_id = "El RUT es obligatorio.";

    if (Object.keys(errors).length) {
      setSubscriptionFieldErrors(errors);
      setSubscriptionFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const body: Record<string, unknown> = {
      platform: subVpPlatform,
      plan_id: rawValues.plan_id,
      email: rawValues.email,
      first_name: rawValues.first_name,
      last_name: rawValues.last_name,
      social_id: rawValues.social_id,
    };
    if (rawValues.phone_number) body.phone_number = rawValues.phone_number;
    if (rawValues.service_id) body.service_id = rawValues.service_id;
    if (rawValues.channel) body.channel = rawValues.channel;
    if (rawValues.automatic_renewal) body.automatic_renewal = rawValues.automatic_renewal;
    if (rawValues.return_url) body.return_url = rawValues.return_url;
    if (rawValues.callback_url) body.callback_url = rawValues.callback_url;

    setSavingSubscription(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        "/api/v1/writes/virtualpos/subscriptions",
        body,
      );
      setRecords((current) => ({
        ...current,
        total: current.total + 1,
        items: [{ id: created.id, source: created.source, resource_type: "subscription", external_id: created.external_id, payload: created.payload }, ...current.items],
      }));
      setCreatingSubscription(false);
      setSubscriptionSaveNotice("Suscripción creada correctamente.");
    } catch (err) {
      setSubscriptionFormError(friendlyError(err, "No se pudo crear la suscripción."));
    } finally {
      setSavingSubscription(false);
    }
  }

  async function createVirtualPOSCharge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingCharge || !creatingCharge) return;
    setChargeFormError(null);
    setChargeFieldErrors({});

    const formData = new FormData(event.currentTarget);
    const errors: Record<string, string> = {};
    const chargeDate = String(formData.get("charge_date") ?? "").trim();
    const amountRaw = String(formData.get("amount") ?? "").trim();
    const description = String(formData.get("description") ?? "").trim();
    const internalCode = String(formData.get("internal_code") ?? "").trim();

    if (!chargeDate) {
      errors.charge_date = "La fecha del cargo es obligatoria.";
    } else {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const selected = new Date(chargeDate);
      if (isNaN(selected.getTime())) {
        errors.charge_date = "Ingresa una fecha válida.";
      } else if (selected < today) {
        errors.charge_date = "La fecha del cargo no puede ser una fecha pasada.";
      }
    }
    const amount = amountRaw === "" ? NaN : Number(amountRaw);
    if (amountRaw === "" || isNaN(amount) || amount < 1) {
      errors.amount = "Ingresa un monto válido (número ≥ 1).";
    }

    if (Object.keys(errors).length) {
      setChargeFieldErrors(errors);
      setChargeFormError("Revisa los campos marcados en rojo.");
      return;
    }

    const subscriptionId = String(creatingCharge.payload.id ?? creatingCharge.external_id);
    const body: Record<string, unknown> = { charge_date: chargeDate, amount };
    if (description) body.description = description;
    if (internalCode) body.internal_code = internalCode;

    setSavingCharge(true);
    try {
      await refreshCsrfToken();
      const created = await postJson<{ id: string; external_id: string; source: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subscriptionId)}/charges`,
        body,
      );
      setCreatingCharge(null);
      setChargeSaveNotice(`Cargo creado correctamente (ID: ${created.external_id}).`);
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === creatingCharge.external_id) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: [{ id: created.id, source: created.source, resource_type: "charge", external_id: created.external_id, payload: created.payload }, ...prev.charges],
                charge_total: prev.charge_total + 1,
              }
            : prev,
        );
      }
    } catch (err) {
      setChargeFormError(friendlyError(err, "No se pudo crear el cargo."));
    } finally {
      setSavingCharge(false);
    }
  }

  async function cancelVirtualPOSSubscription() {
    if (savingCancelSubscription || !cancelingSubscription) return;
    setSavingCancelSubscription(true);
    setCancelSubscriptionError(null);
    const subExternalId = String(cancelingSubscription.payload.id ?? cancelingSubscription.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/subscriptions/${encodeURIComponent(subExternalId)}`,
      );
      const updatedStatus = result.status ?? "CANCELADA";
      setCancelingSubscription(null);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "subscription" && record.external_id === subExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail && subscriptionDetail.subscription.external_id === subExternalId) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                subscription: {
                  ...prev.subscription,
                  payload: { ...prev.subscription.payload, status: updatedStatus },
                },
              }
            : prev,
        );
      }
      if (clientDetail) {
        setClientDetail((prev) =>
          prev
            ? {
                ...prev,
                subscriptions: prev.subscriptions.map((s) =>
                  s.external_id === subExternalId
                    ? { ...s, payload: { ...s.payload, status: updatedStatus } }
                    : s,
                ),
              }
            : prev,
        );
      }
    } catch (err) {
      setCancelSubscriptionError(friendlyError(err, "No se pudo cancelar la suscripción."));
    } finally {
      setSavingCancelSubscription(false);
    }
  }

  async function cancelVirtualPOSCharge() {
    if (savingCancelCharge || !cancelingCharge) return;
    setSavingCancelCharge(true);
    setCancelChargeError(null);
    const chargeExternalId = String(cancelingCharge.payload.id ?? cancelingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await deleteJson<{ external_id: string; status: string }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}`,
      );
      const updatedStatus = result.status ?? "cancelado";
      setCancelingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} cancelado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setCancelChargeError(friendlyError(err, "No se pudo cancelar el cargo."));
    } finally {
      setSavingCancelCharge(false);
    }
  }

  async function retryVirtualPOSCharge() {
    if (savingRetryCharge || !retryingCharge) return;
    setSavingRetryCharge(true);
    setRetryChargeError(null);
    const chargeExternalId = String(retryingCharge.payload.id ?? retryingCharge.external_id);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/virtualpos/charges/${encodeURIComponent(chargeExternalId)}/retry`,
      );
      const rawStatus = result.status ?? "procesando";
      const updatedStatus = rawStatus.toLowerCase() === "rechazado" ? "procesando" : rawStatus;
      const updatedPayload = result.payload ?? retryingCharge.payload;
      setRetryingCharge(null);
      setChargeSaveNotice(`Cargo ${chargeExternalId} reintentado.`);
      setRecords((current) => ({
        ...current,
        items: current.items.map((record) =>
          record.resource_type === "charge" && record.external_id === chargeExternalId
            ? { ...record, payload: { ...record.payload, ...updatedPayload, status: updatedStatus } }
            : record,
        ),
      }));
      if (subscriptionDetail) {
        setSubscriptionDetail((prev) =>
          prev
            ? {
                ...prev,
                charges: prev.charges.map((c) =>
                  c.external_id === chargeExternalId
                    ? { ...c, payload: { ...c.payload, ...updatedPayload, status: updatedStatus } }
                    : c,
                ),
              }
            : prev,
        );
      }
      if (chargeDetail && chargeDetail.charge.external_id === chargeExternalId) {
        setChargeDetail((prev) =>
          prev
            ? { ...prev, charge: { ...prev.charge, payload: { ...prev.charge.payload, ...updatedPayload, status: updatedStatus } } }
            : prev,
        );
      }
    } catch (err) {
      setRetryChargeError(friendlyError(err, "No se pudo reintentar el cargo."));
    } finally {
      setSavingRetryCharge(false);
    }
  }

  async function saveProviderEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProviderRecord || savingProviderEdit) return;
    setProviderEditError(null);
    const { record, source, resourceType } = editingProviderRecord;
    const formData = new FormData(event.currentTarget);
    const fields = providerEditFields[source]?.[resourceType] ?? [];
    const changes: Record<string, unknown> = {};
    for (const field of fields) {
      const val = String(formData.get(field.name) ?? "").trim();
      const current = String(record.payload[field.name] ?? "").trim();
      if (val !== "" && val !== current) changes[field.name] = field.type === "number" ? Number(val) : val;
    }
    if (Object.keys(changes).length === 0) { setEditingProviderRecord(null); return; }
    setSavingProviderEdit(true);
    try {
      await refreshCsrfToken();
      let updatedPayload: Record<string, unknown> = record.payload;
      if (source === "toku" && resourceType === "customer") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      } else if (source === "payku" && resourceType === "client") {
        const result = await putJson<{ external_id: string; payload: Record<string, unknown> }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
          changes,
        );
        updatedPayload = result.payload;
      }
      setEditingProviderRecord(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === record.external_id && item.source === source
            ? { ...item, payload: updatedPayload }
            : item,
        ),
      }));
    } catch (err) {
      setProviderEditError(friendlyError(err, "No se pudo guardar el cambio."));
    } finally {
      setSavingProviderEdit(false);
    }
  }

  async function confirmProviderDelete() {
    if (!deletingRecord || savingProviderDelete) return;
    setProviderDeleteError(null);
    const { record, source, resourceType } = deletingRecord;
    setSavingProviderDelete(true);
    try {
      await refreshCsrfToken();
      if (source === "toku" && resourceType === "customer") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/toku/customers/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "client") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/clients/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "deleted" } }
              : item,
          ),
        }));
      } else if (source === "payku" && resourceType === "subscription") {
        await deleteJson<{ external_id: string; status: string }>(
          `/api/v1/writes/payku/subscriptions/${encodeURIComponent(record.external_id)}`,
        );
        setDeletingRecord(null);
        setRecords((prev) => ({
          ...prev,
          items: prev.items.map((item) =>
            item.external_id === record.external_id && item.source === source
              ? { ...item, payload: { ...item.payload, status: "cancelled" } }
              : item,
          ),
        }));
      }
    } catch (err) {
      setProviderDeleteError(friendlyError(err, "No se pudo eliminar el registro."));
    } finally {
      setSavingProviderDelete(false);
    }
  }

  async function changeTokuSubscriptionStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!managingTokuSub || savingTokuSubStatus) return;
    setTokuSubStatusError(null);
    const formData = new FormData(event.currentTarget);
    const status = String(formData.get("status") ?? "").trim();
    if (!status) { setTokuSubStatusError("Selecciona un estado."); return; }
    const subId = String(managingTokuSub.payload.id ?? managingTokuSub.external_id);
    setSavingTokuSubStatus(true);
    try {
      await refreshCsrfToken();
      const result = await postJson<{ external_id: string; status: string; payload: Record<string, unknown> }>(
        `/api/v1/writes/toku/subscriptions/${encodeURIComponent(subId)}/status`,
        { status },
      );
      const updatedPayload = result.payload;
      setManagingTokuSub(null);
      setRecords((prev) => ({
        ...prev,
        items: prev.items.map((item) =>
          item.external_id === managingTokuSub.external_id && item.source === "toku"
            ? { ...item, payload: { ...item.payload, ...updatedPayload, status: result.status } }
            : item,
        ),
      }));
    } catch (err) {
      setTokuSubStatusError(friendlyError(err, "No se pudo cambiar el estado."));
    } finally {
      setSavingTokuSubStatus(false);
    }
  }

  function navigate(route: AppRoute, replace = false) {
    const path = routePath(route);
    if (window.location.pathname !== path) {
      window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    }
    setRouteLocation(path);
  }

  function replaceListSearch(params: URLSearchParams) {
    const search = params.toString();
    const location = `${window.location.pathname}${search ? `?${search}` : ""}`;
    if (window.location.pathname + window.location.search !== location) {
      window.history.replaceState({}, "", location);
    }
  }

  function listOffset(params: URLSearchParams) {
    const value = Number(params.get("offset") ?? "0");
    return Number.isSafeInteger(value) && value >= 0 ? value : 0;
  }

  function canAccessRoute(route: AppRoute) {
    if (route.kind === "central") return can("dashboard.view");
    if (route.kind === "resource" || route.kind === "record") return can(resourcePermission(route.source, route.resource));
    if (route.kind === "channel") {
      return providerGroups.find((group) => group.sections[0].source === route.source)?.sections.some((section) => can(resourcePermission(section.source, section.resource))) ?? false;
    }
    if (route.kind === "recovery") return can("virtualpos.recovery.view");
    if (route.kind === "billingChanges") return can("virtualpos.billing_changes.view");
    if (route.kind === "tchSubscription") return can("tch.suscripciones.view");
    if (route.kind === "tch") return route.view === "summary"
      ? can("tch.dashboard.view")
      : can(`tch.${route.view}.view`);
    if (route.kind === "admin") return route.view === "usuarios"
      ? can("users.manage") || can("roles.manage")
      : can("sync_runs.view") || can("sync.run");
    return true;
  }

  function fallbackRoute() {
    if (can("dashboard.view")) return { kind: "central", view: "summary" } as const;
    const section = providerGroups.flatMap((group) => group.sections).find((entry) => can(resourcePermission(entry.source, entry.resource)));
    return section
      ? { kind: "resource", source: section.source, resource: section.resource } as const
      : { kind: "profile", view: "summary" } as const;
  }

  function showAdmin(view: "usuarios" | "sincronizacion", updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(true);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setAdminTab(view);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "admin", view });
  }

  function showDashboard(updateUrl = true) {
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(false);
    clearDetails();
    setActiveSection(null);
    setChannel(null);
    setTchView(null);
    setGeneralView("summary");
    setGeneralClientDetail(null);
    setError(null);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "central", view: "summary" });
  }

  function showGeneralClients(updateUrl = true) {
    showDashboard(false);
    setGeneralView("clients");
    if (updateUrl) navigate({ kind: "central", view: "clients" });
  }

  function showGeneralSubscriptions(updateUrl = true) {
    showDashboard(false);
    setGeneralView("subscriptions");
    if (updateUrl) navigate({ kind: "central", view: "subscriptions" });
  }

  function showAutoReport(updateUrl = true) {
    showDashboard(false);
    setGeneralView("report");
    if (updateUrl) navigate({ kind: "central", view: "report" });
  }

  function showTch(view: "summary" | "clientes" | "suscripciones" | "transacciones", updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setError(null);
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail(null);
    setTchClienteDetail(null);
    setTchView(view);
    setOpenProvider("TCH");
    setProfileView(null);
    if (updateUrl) navigate({ kind: "tch", view });
  }

  function showTchSuscripcion(numeroFicha: number, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "tchSubscription", numeroFicha });
      return;
    }
    showTch("suscripciones", false);
    setTchSuscripcionDetail({ numero_ficha: numeroFicha } as TchSuscripcionDetail);
    setTchView("suscripcion-detalle");
  }

  function showTchTransaccion(id: string) {
    setTchClienteDetail(null);
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail({ id } as TchTransaccionDetail);
    setTchView("transaccion-detalle");
  }

  function showTchCliente(rut: string) {
    setTchSuscripcionDetail(null);
    setTchTransaccionDetail(null);
    setTchClienteDetail({ rut, suscripciones: [] } as unknown as TchClienteDetail);
    setTchView("cliente-detalle");
  }

  function showChannel(source: ProviderSource, updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setActiveSection(null);
    setTchView(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setAdminOpen(false);
    const cached = getCached<ChannelDashboard>(`dashboard:${source}`, 5 * 60 * 1000);
    setChannelData(cached);
    setChannelLoading(!cached);
    setError(null);
    setYear(null);
    setChannel(source);
    setOpenProvider(title(source));
    setProfileView(null);
    if (updateUrl) navigate({ kind: "channel", source });
  }
  function _pollEtlRun(run_id: string) {
    const poll = setInterval(() => {
      getJson<EtlRun>(`/api/v1/etl/runs/${run_id}`)
        .then((run) => {
          setLastEtlRun(run);
          if (run.status !== "running") {
            clearInterval(poll);
            setEtlRunning(false);
          }
        })
        .catch((err: unknown) => {
          clearInterval(poll);
          setEtlRunning(false);
          setEtlError(friendlyError(err, "Error al consultar el estado del ETL."));
        });
    }, 3000);
  }
  function runFullSync() {
    if (etlRunning) return;
    setEtlRunning(true);
    setEtlError(null);
    postJson<{ run_id: string }>("/api/v1/etl/full-sync", {
      providers: (["virtualpos", "toku", "payku"] as const).filter((provider) => isChannelEnabled(provider === "virtualpos" ? "virtualpos1" : provider)),
    })
      .then(({ run_id }) => _pollEtlRun(run_id))
      .catch((err: unknown) => {
        setEtlRunning(false);
        setEtlError(friendlyError(err, "Error al iniciar el Sync completo."));
      });
  }
  function syncChannel(source: string) {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    postJson<{ status: string }>(`/api/v1/staging/sync/${source}`)
      .then(() => {
        invalidateCache();
        setChannelData(null);
        setChannelLoading(true);
        return getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${source}`);
      })
      .then((data) => {
        setCached(`dashboard:${source}`, data);
        setChannelData(data);
        setYear(defaultYear(data.years));
      })
      .catch((err: unknown) => setError(friendlyError(err, "Error al sincronizar el canal.")))
      .finally(() => setSyncing(false));
  }
  function showSection(section: ProviderSection, updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setAdminOpen(false);
    setLoading(true);
    setError(null);
    setFilterField(stagingFilters[section.source]?.[section.resource]?.[0]?.value ?? "");
    setFilterQuery("");
    setVpColumnFilters({});
    setRecordsOffset(0);
    setSortColumn(null);
    setSortDirection("asc");
    if (section.source === "virtualpos") setVpPlatform("all");
    setActiveSection(section);
    setOpenProvider(title(section.source));
    setProfileView(null);
    if (updateUrl) navigate({ kind: "resource", source: section.source, resource: section.resource });
  }
  function openChannelResource(resource: string) {
    const section = providerGroups
      .flatMap((group) => group.sections)
      .find((entry) => entry.source === channel && entry.resource === resource);
    if (section) showSection(section);
  }

  function showResourceList(source: ProviderSource, resource: string) {
    const section = providerGroups
      .flatMap((group) => group.sections)
      .find((entry) => entry.source === source && entry.resource === resource);
    if (section) showSection(section);
    else showDashboard();
  }

  function showRecovery(updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(false);
    setRecoveryOpen(true);
    setBillingOpen(false);
    setOpenProvider("VirtualPOS");
    setProfileView(null);
    if (updateUrl) navigate({ kind: "recovery" });
  }

  function showBillingChanges(updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(true);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "billingChanges" });
  }

  function showProfile(view: "summary" | "edit", updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setAdminOpen(false);
    setProfileView(view);
    if (updateUrl) navigate({ kind: "profile", view });
  }

  useEffect(() => {
    const onPopState = () => setRouteLocation(window.location.pathname + window.location.search);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  async function openVirtualPosClient(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "client", externalId: record.external_id });
      return;
    }
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setClientDetail(
        await getJson<VirtualPosClientDetail>(
          `/api/v1/staging/virtualpos/clients/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cliente."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPlan(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "plan", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPlanDetail(
        await getJson<VirtualPosPlanDetail>(
          `/api/v1/staging/virtualpos/plans/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del plan."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosSubscription(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "subscription", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setChargeDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setSubscriptionDetail(
        await getJson<VirtualPosSubscriptionDetail>(
          `/api/v1/staging/virtualpos/subscriptions/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha de la subscripción."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosCharge(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "charge", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setPaymentDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setChargeDetail(
        await getJson<VirtualPosChargeDetail>(
          `/api/v1/staging/virtualpos/charges/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del cargo."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openVirtualPosPayment(record: Pick<StagingRecord, "external_id">, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "record", source: "virtualpos", resource: "payment", externalId: record.external_id });
      return;
    }
    setClientDetail(null);
    setPlanDetail(null);
    setSubscriptionDetail(null);
    setChargeDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      setPaymentDetail(
        await getJson<VirtualPosPaymentDetail>(
          `/api/v1/staging/virtualpos/payments/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del pago."));
    } finally {
      setDetailLoading(false);
    }
  }
  async function openProviderRecord(
    source: ProviderSource,
    resource: string,
    record: Pick<StagingRecord, "external_id">,
    updateUrl = true,
  ) {
    if (updateUrl) {
      navigate({ kind: "record", source, resource, externalId: record.external_id });
      return;
    }
    clearDetails();
    setDetailLoading(true);
    setError(null);
    try {
      setProviderRecordDetail(
        await getJson<ProviderRecordDetail>(
          `/api/v1/staging/${source}/${resource}/${encodeURIComponent(record.external_id)}`,
        ),
      );
    } catch (err) {
      setError(friendlyError(err, "No se pudo cargar la ficha del registro."));
    } finally {
      setDetailLoading(false);
    }
  }

  function openRecord(source: ProviderSource, resource: string, externalId: string, updateUrl = true) {
    const record = { external_id: externalId };
    if (source === "virtualpos") {
      if (resource === "client") return openVirtualPosClient(record, updateUrl);
      if (resource === "plan") return openVirtualPosPlan(record, updateUrl);
      if (resource === "subscription") return openVirtualPosSubscription(record, updateUrl);
      if (resource === "charge") return openVirtualPosCharge(record, updateUrl);
      if (resource === "payment") return openVirtualPosPayment(record, updateUrl);
      return;
    }
    return openProviderRecord(source, resource, record, updateUrl);
  }

  const applyRoute = useEffectEvent(() => {
    if (!session) return;
    const location = new URL(routeLocation, window.location.origin);
    const route = parseRoute(location.pathname);
    if (!route || !canAccessRoute(route)) {
      navigate(fallbackRoute(), true);
      return;
    }
    if (route.kind === "central") {
      if (route.view === "report") showAutoReport(false);
      else if (route.view === "summary") showDashboard(false);
      else if (route.view === "clients") {
        showGeneralClients(false);
        const field = location.searchParams.get("campo");
        if (["all", "rut", "name", "last_name", "platform", "email", "phone"].includes(field ?? "")) {
          setGeneralClientFilter(field as typeof generalClientFilter);
        }
        setGeneralClientQuery("");
        setGeneralClientOffset(listOffset(location.searchParams));
      } else {
        showGeneralSubscriptions(false);
        const field = location.searchParams.get("campo");
        if (["all", "id", "rut", "client", "platform", "status"].includes(field ?? "")) {
          setGeneralSubscriptionFilter(field as typeof generalSubscriptionFilter);
        }
        setGeneralSubscriptionQuery("");
        setGeneralSubscriptionOffset(listOffset(location.searchParams));
      }
    } else if (route.kind === "channel") {
      showChannel(route.source, false);
    } else if (route.kind === "resource" || route.kind === "record") {
      const section = providerGroups
        .flatMap((group) => group.sections)
        .find((entry) => entry.source === route.source && entry.resource === route.resource);
      if (section) {
        showSection(section, false);
        const filter = location.searchParams.get("filtro");
        const status = location.searchParams.get("estado");
        if ((filter === "status" || filter === "secondary_status") && status) {
          setFilterField(filter);
          setFilterQuery(status);
        }
        const sort = location.searchParams.get("orden");
        const direction = location.searchParams.get("direccion");
        setSortColumn(sort || null);
        setSortDirection(direction === "desc" ? "desc" : "asc");
        setRecordsOffset(listOffset(location.searchParams));
        if (route.source === "virtualpos") {
          const platform = location.searchParams.get("cuenta");
          setVpPlatform(platform === "virtualpos1" || platform === "virtualpos2" ? platform : "all");
        }
        if (route.kind === "record") void openRecord(route.source, route.resource, route.externalId, false);
      } else navigate(fallbackRoute(), true);
    } else if (route.kind === "recovery") {
      showRecovery(false);
    } else if (route.kind === "billingChanges") {
      showBillingChanges(false);
      if (legacyRedirectPath(location.pathname)) navigate(route, true);
    } else if (route.kind === "tch") {
      showTch(route.view, false);
    } else if (route.kind === "tchSubscription") {
      showTchSuscripcion(route.numeroFicha, false);
    } else if (route.kind === "admin") {
      showAdmin(route.view, false);
    } else {
      showProfile(route.view, false);
    }
  });

  useEffect(() => {
    applyRoute();
  }, [session, routeLocation]);

  useEffect(() => {
    const route = parseRoute(window.location.pathname);
    if (!session || route?.kind !== "central" || route.view !== "clients") return;
    const params = new URLSearchParams();
    if (generalClientFilter !== "all") params.set("campo", generalClientFilter);
    if (generalClientOffset > 0) params.set("offset", String(generalClientOffset));
    replaceListSearch(params);
  }, [session, generalView, generalClientFilter, generalClientOffset]);

  useEffect(() => {
    const route = parseRoute(window.location.pathname);
    if (!session || route?.kind !== "central" || route.view !== "subscriptions") return;
    const params = new URLSearchParams();
    if (generalSubscriptionFilter !== "all") params.set("campo", generalSubscriptionFilter);
    if (generalSubscriptionOffset > 0) params.set("offset", String(generalSubscriptionOffset));
    replaceListSearch(params);
  }, [session, generalView, generalSubscriptionFilter, generalSubscriptionOffset]);

  useEffect(() => {
    const route = parseRoute(window.location.pathname);
    if (!session || !activeSection || route?.kind !== "resource") return;
    const params = new URLSearchParams();
    if ((filterField === "status" || filterField === "secondary_status") && filterQuery.trim()) {
      params.set("filtro", filterField);
      params.set("estado", filterQuery.trim());
    }
    if (sortColumn) {
      params.set("orden", sortColumn);
      params.set("direccion", sortDirection);
    }
    if (recordsOffset > 0) params.set("offset", String(recordsOffset));
    if (activeSection.source === "virtualpos" && vpPlatform !== "all") params.set("cuenta", vpPlatform);
    replaceListSearch(params);
  }, [session, activeSection, filterField, filterQuery, sortColumn, sortDirection, recordsOffset, vpPlatform]);

  const columns: TableColumn[] =
    activeSection?.source === "virtualpos"
      ? virtualPosColumns(activeSection.resource)
      : activeSection?.source === "toku"
        ? tokuColumns(activeSection.resource)
        : activeSection?.source === "payku"
          ? paykuColumns(activeSection.resource)
          : [];
  function toggleColumnSort(column: TableColumn) {
    if (!activeSection || !filterFieldForColumn(activeSection.source, activeSection.resource, column.label)) return;
    if (sortColumn === column.label) {
      setRecordsOffset(0);
      setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
      return;
    }
    setRecordsOffset(0);
    setSortColumn(column.label);
    setSortDirection("asc");
  }

  async function logout() {
    try { await postJson("/api/v1/auth/logout"); } finally {
      setCsrfToken("");
      setSession(null);
      setAdminOpen(false);
      setProfileView(null);
      navigate({ kind: "central", view: "summary" }, true);
    }
  }
  const clientDetailView = clientDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => showResourceList("virtualpos", "client")}>
        Volver a clientes VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / CLIENTE</p>
      <h2>
        {text(clientDetail.client.payload.first_name, "")}{" "}
        {text(clientDetail.client.payload.last_name, "")}
      </h2>
      <div className="client-detail-actions">
        <button className="edit-button" onClick={() => setEditingClient(clientDetail.client)}>
          Editar
        </button>
      </div>
      <section className="panel">
        <p className="eyebrow">FICHA DEL CLIENTE</p>
        <dl className="field-list">
          {virtualPosClientFields.map((field) => (
            <div key={field}>
              <dt>{virtualPosClientFieldLabels[field]}</dt>
              <dd>
                {field === "uuid"
                  ? text(
                      clientDetail.client.payload.uuid,
                      clientDetail.client.external_id,
                    )
                  : field === "social_id_type"
                    ? (virtualPosDocumentTypes[text(clientDetail.client.payload[field], "")] ?? text(clientDetail.client.payload[field]))
                  : text(clientDetail.client.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p>
            <h3>Relacionadas por RUT</h3>
          </div>
          <span>{clientDetail.subscription_total} total</span>
        </div>
        <VirtualPosDetailTable records={clientDetail.subscriptions} empty="Sin suscripciones asociadas por RUT." columns={[
          { label: "ID Sub", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosSubscription(record)}>{text(record.payload.id, record.external_id)}</button> },
          { label: "Status", value: (record) => text(record.payload.status) },
          { label: "Estado sec.", value: (record) => record.secondary_status ?? "—" },
          { label: "Último cobro", kind: "date", value: (record) => record.last_paid_date ? String(record.last_paid_date).slice(0, 10) : "" },
          { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
          { label: "F. Inicio", kind: "date", value: (record) => text(record.payload.suscription_date, "") },
          { label: "Acción", filterable: false, value: () => "", render: (record) => isActiveSubscription(record) ? <button className="cancel-subscription-button" onClick={() => { setCancelSubscriptionError(null); setCancelingSubscription(record); }}>Cancelar</button> : null },
        ]} />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CARGOS</p>
            <h3>Cobros generados por suscripción</h3>
          </div>
          <span>{clientDetail.charge_total} total{clientDetail.charge_total > 100 ? " · mostrando últimos 100" : ""}</span>
        </div>
        <VirtualPosDetailTable records={clientDetail.charges} empty="Sin cargos registrados para este cliente." columns={[
          { label: "Fecha", kind: "date", value: (record) => text(record.payload.charge_date, "") },
          { label: "ID Cargo", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosCharge(record)}>{text(record.payload.id, record.external_id)}</button> },
          { label: "Plan", value: (record) => record.plan_name ?? "", render: (record) => record.subscription_id ? <button className="record-link" onClick={() => void openVirtualPosSubscription({ external_id: record.subscription_id! })}>{record.plan_name ?? "Sin plan"}</button> : "Sin plan" },
          { label: "Estado", value: (record) => text(record.payload.status) },
          { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
        ]} />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">TRANSACCIONES</p>
            <h3>Pagos procesados</h3>
          </div>
          <span>{clientDetail.payment_total} total</span>
        </div>
        <VirtualPosDetailTable records={clientDetail.payments} empty="Sin transacciones procesadas para este cliente." columns={[
          { label: "Fecha autorización", kind: "date", value: (record) => text(nested(record.payload, "order", "authorized_at"), "") },
          { label: "ID Transacción", value: (record) => record.external_id, render: (record) => <button className="record-link" onClick={() => void openVirtualPosPayment(record)}>{record.external_id}</button> },
          { label: "Estado", value: (record) => text(nested(record.payload, "order", "status")) },
          { label: "Monto bruto", kind: "amount", value: (record) => text(nested(record.payload, "order", "amount"), "0") },
          { label: "Abono neto", kind: "amount", value: (record) => { const order = record.payload.order as Record<string, unknown> | undefined; const deposit = Array.isArray(order?.deposits) ? order.deposits[0] as Record<string, unknown> : undefined; return text(deposit?.payout_amount, "0"); } },
          { label: "Tipo", value: (record) => text(nested(record.payload, "order", "payment_type_code"), "") },
        ]} />
      </section>
    </main>
  ) : null;
  const planDetailView = planDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => showResourceList("virtualpos", "plan")}>
        Volver a planes VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / PLAN</p>
      <h2>{text(planDetail.plan.payload.name, planDetail.plan.external_id)}</h2>
      <section className="panel">
        <p className="eyebrow">FICHA DEL PLAN</p>
        <dl className="field-list">
          {virtualPosPlanFields.map((field) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>
                {field === "id"
                  ? text(
                      planDetail.plan.payload.id,
                      planDetail.plan.external_id,
                    )
                  : (field === "return_url" || field === "suscription_url") && externalUrl(planDetail.plan.payload[field])
                    ? <a className="record-link" href={externalUrl(planDetail.plan.payload[field]) ?? undefined} target="_blank" rel="noreferrer">Abrir enlace</a>
                    : text(planDetail.plan.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p>
            <h3>Asociadas al plan</h3>
          </div>
          <span>{planDetail.subscription_total} total</span>
        </div>
        <VirtualPosDetailTable records={planDetail.subscriptions} empty="Sin suscripciones asociadas al plan." columns={[
          { label: "ID Sub", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosSubscription(record)}>{text(record.payload.id, record.external_id)}</button> },
          { label: "Nombre cliente", value: virtualPosClientName },
          { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
          { label: "Status", value: (record) => text(record.payload.status) },
        ]} />
      </section>
    </main>
  ) : null;
  const subscriptionDetailView = subscriptionDetail ? (
    <main className="app-shell detail-page">
      <button
        className="back-button"
        onClick={() => showResourceList("virtualpos", "subscription")}
      >
        Volver al listado VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / SUBSCRIPCIÓN</p>
      <h2>
        {text(
          subscriptionDetail.subscription.payload.plan_name,
          subscriptionDetail.subscription.external_id,
        )}
      </h2>
      {isActiveSubscription(subscriptionDetail.subscription) ? (
        <div className="client-detail-actions">
          <button
            className="cancel-subscription-button"
            onClick={() => setCancelingSubscription(subscriptionDetail.subscription)}
          >
            Cancelar Sub
          </button>
          <button
            className="create-charge-button"
            onClick={() => { setChargeFormError(null); setChargeFieldErrors({}); setCreatingCharge(subscriptionDetail.subscription); }}
          >
            + Nuevo cargo
          </button>
        </div>
      ) : null}
      {chargeSaveNotice ? <p className="save-notice">{chargeSaveNotice}</p> : null}
      <section className="panel">
        <p className="eyebrow">FICHA DE LA SUBSCRIPCIÓN</p>
        <dl className="field-list">
          {virtualPosSubscriptionFields.map((field) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>
                {field === "secondary_status"
                  ? <span className={`badge badge-${subscriptionDetail.subscription.secondary_status === "cobrable" ? "green" : subscriptionDetail.subscription.secondary_status === "incobrable" ? "orange" : subscriptionDetail.subscription.secondary_status === "inactiva" ? "gray" : "blue"}`}>{subscriptionDetail.subscription.secondary_status ?? "—"}</span>
                  : field === "last_paid_date"
                    ? (subscriptionDetail.subscription.last_paid_date ? String(subscriptionDetail.subscription.last_paid_date).slice(0, 10) : "—")
                  : field === "id"
                  ? text(
                      subscriptionDetail.subscription.payload.id,
                      subscriptionDetail.subscription.external_id,
                    )
                  : field === "plan_name" && subscriptionDetail.subscription.payload.plan_id
                    ? <button className="record-link" onClick={() => void openVirtualPosPlan({ external_id: String(subscriptionDetail.subscription.payload.plan_id) })}>{text(subscriptionDetail.subscription.payload[field])}</button>
                    : field === "renewal"
                      ? renewalText(subscriptionDetail.subscription.payload[field])
                      : text(subscriptionDetail.subscription.payload[field])}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel client-subscriptions">
        <p className="eyebrow">MÉTODO DE PAGO</p>
        {objectEntries(subscriptionDetail.payment_method).length ? (
          <dl className="field-list">
            {objectEntries(subscriptionDetail.payment_method).filter(([field]) => !["bin", "last4carddigit", "last4"].includes(field.toLowerCase())).map(
              ([field, value]) => (
                <div key={field}>
                  <dt>{fieldLabel(field)}</dt>
                  <dd>{field === "card_type" ? cardTypeText(value) : text(value)}</dd>
                </div>
              ),
            )}
          </dl>
        ) : (
          <p>Sin método de pago disponible en staging.</p>
        )}
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CARGOS</p>
            <h3>Asociados a la subscripción</h3>
          </div>
          <span>{subscriptionDetail.charge_total} total</span>
        </div>
        <VirtualPosDetailTable records={subscriptionDetail.charges} empty="Sin cargos asociados a la subscripción." columns={[
          { label: "Fecha de cargo", kind: "date", value: (record) => text(record.payload.charge_date, "") },
          { label: "ID Cargo", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosCharge(record)}>{text(record.payload.id, record.external_id)}</button> },
          { label: "Estado", value: (record) => text(record.payload.status) },
          { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
          { label: "Acción", filterable: false, value: () => "", render: (record) => isPendingCharge(record) && can("virtualpos.charges.cancel") ? <button className="cancel-charge-button" onClick={() => { setCancelChargeError(null); setCancelingCharge(record); }}>Cancelar</button> : isRejectedCharge(record) && can("virtualpos.charges.retry") ? <button className="retry-charge-button" onClick={() => { setRetryChargeError(null); setRetryingCharge(record); }}>Reintentar</button> : null },
        ]} />
      </section>
      <section className="panel client-subscriptions">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">TRANSACCIONES DEL CLIENTE</p>
            <h3>Disponibles por RUT en la misma cuenta</h3>
          </div>
          <span>{subscriptionDetail.payment_total} total</span>
        </div>
        <p className="field-hint">VirtualPOS no entrega un identificador de subscripción en las transacciones, por lo que esta tabla no las asigna individualmente.</p>
        <VirtualPosDetailTable records={subscriptionDetail.payments} empty="Sin transacciones disponibles para este cliente." columns={[
          { label: "Fecha autorización", kind: "date", value: (record) => text(nested(record.payload, "order", "authorized_at"), "") },
          { label: "ID Transacción", value: (record) => record.external_id, render: (record) => <button className="record-link" onClick={() => void openVirtualPosPayment(record)}>{record.external_id}</button> },
          { label: "Estado", value: (record) => text(nested(record.payload, "order", "status")) },
          { label: "Monto", kind: "amount", value: (record) => text(nested(record.payload, "order", "amount"), "0") },
        ]} />
      </section>
    </main>
  ) : null;
  const chargeDetailView = chargeDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => showResourceList("virtualpos", "charge")}>
        Volver a cargos VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / CARGO</p>
      <h2>{text(chargeDetail.charge.payload.id, chargeDetail.charge.external_id)}</h2>
      <div className="client-detail-actions">
        {isPendingCharge(chargeDetail.charge) ? (
          <button
            className="cancel-charge-button"
            onClick={() => { setCancelChargeError(null); setCancelingCharge(chargeDetail.charge); }}
          >
            Cancelar en VP
          </button>
        ) : null}
        {isRejectedCharge(chargeDetail.charge) && can("virtualpos.charges.retry") ? (
          <button
            className="retry-charge-button"
            onClick={() => { setRetryChargeError(null); setRetryingCharge(chargeDetail.charge); }}
          >
            Reintentar en VP
          </button>
        ) : null}
      </div>
      <section className="panel">
        <p className="eyebrow">FICHA DEL CARGO</p>
        <dl className="field-list">
          {Object.entries(chargeDetail.charge.payload).map(([field, value]) => (
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>{text(value)}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="panel">
        <p className="eyebrow">RELACIONES</p>
        <dl className="field-list">
          <div><dt>Cliente</dt><dd>{chargeDetail.client ? <button className="record-link" onClick={() => void openVirtualPosClient(chargeDetail.client!)}>{vpClientRecordName(chargeDetail.client)}</button> : "Sin cliente relacionado"}</dd></div>
          <div><dt>RUT cliente</dt><dd>{chargeDetail.client ? text(chargeDetail.client.payload.social_id) : "—"}</dd></div>
          <div><dt>Subscripción</dt><dd>{chargeDetail.subscription ? <button className="record-link" onClick={() => void openVirtualPosSubscription(chargeDetail.subscription!)}>{chargeDetail.subscription.plan_name ?? chargeDetail.subscription.external_id}</button> : "Sin subscripción relacionada"}</dd></div>
          <div><dt>Transacción</dt><dd>{chargeDetail.payment ? <button className="record-link" onClick={() => void openVirtualPosPayment(chargeDetail.payment!)}>{chargeDetail.payment.external_id}</button> : "Sin transacción relacionada"}</dd></div>
        </dl>
      </section>
    </main>
  ) : null;
  const paymentDetailView = paymentDetail ? (
    <main className="app-shell detail-page">
      <button className="back-button" onClick={() => showResourceList("virtualpos", "payment")}>
        Volver a transacciones VirtualPOS
      </button>
      <p className="eyebrow">VIRTUALPOS / TRANSACCIÓN</p>
      <h2>{text(nested(paymentDetail.payment.payload, "order", "uuid"), paymentDetail.payment.external_id)}</h2>
      <div className="client-detail-actions">
        <button
          className="delete-button"
          onClick={() => setDeletingRecord({ record: paymentDetail.payment, source: "virtualpos", resourceType: "payment" })}
        >
          Eliminar
        </button>
      </div>
      <section className="panel">
        <p className="eyebrow">FICHA DE LA TRANSACCIÓN</p>
        <dl className="field-list">
          {Object.entries(paymentDetail.payment.payload).flatMap(([field, value]) => {
            if ((field === "order" || field === "client") && objectEntries(value).length) {
              return objectEntries(value).map(([nestedField, nestedValue]) => (
                <div key={`${field}-${nestedField}`}>
                  <dt>{fieldLabel(field)} {fieldLabel(nestedField)}</dt>
                  <dd>{text(nestedValue)}</dd>
                </div>
              ));
            }
            return [
              <div key={field}>
                <dt>{fieldLabel(field)}</dt>
                <dd>{text(value)}</dd>
              </div>,
            ];
          })}
        </dl>
      </section>
      <section className="panel">
        <p className="eyebrow">RELACIONES</p>
        <dl className="field-list">
          <div><dt>Cliente</dt><dd>{paymentDetail.client ? <button className="record-link" onClick={() => void openVirtualPosClient(paymentDetail.client!)}>{vpClientRecordName(paymentDetail.client)}</button> : "Sin cliente relacionado"}</dd></div>
          <div><dt>RUT cliente</dt><dd>{paymentDetail.client ? text(paymentDetail.client.payload.social_id) : "—"}</dd></div>
          <div><dt>Subscripción</dt><dd>{paymentDetail.subscription ? <button className="record-link" onClick={() => void openVirtualPosSubscription(paymentDetail.subscription!)}>{paymentDetail.subscription.plan_name ?? paymentDetail.subscription.external_id}</button> : "Sin subscripción relacionada"}</dd></div>
          <div><dt>Cargo</dt><dd>{paymentDetail.charge ? <button className="record-link" onClick={() => void openVirtualPosCharge(paymentDetail.charge!)}>{text(paymentDetail.charge.payload.id, paymentDetail.charge.external_id)}</button> : "Sin cargo relacionado"}</dd></div>
        </dl>
      </section>
    </main>
  ) : null;
  const providerRecordDetailView = providerRecordDetail ? (
    <main className="app-shell detail-page">
      <button
        className="back-button"
        onClick={() => showResourceList(providerRecordDetail.record.source as ProviderSource, providerRecordDetail.record.resource_type)}
      >
        Volver al listado {title(providerRecordDetail.record.source)}
      </button>
      <p className="eyebrow">
        {title(providerRecordDetail.record.source).toUpperCase()} /{" "}
        {resourceTitle(providerRecordDetail.record.resource_type).toUpperCase()}
      </p>
      <h2>{providerRecordHeading(providerRecordDetail.record)}</h2>
      <div className="client-detail-actions">
        {(providerEditFields[providerRecordDetail.record.source]?.[providerRecordDetail.record.resource_type] ?? []).length > 0 ? (
          <button
            className="edit-button"
            onClick={() => { setProviderEditError(null); setEditingProviderRecord({
              record: providerRecordDetail.record,
              source: providerRecordDetail.record.source,
              resourceType: providerRecordDetail.record.resource_type,
            }); }}
          >
            Editar
          </button>
        ) : null}
        {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "subscription" ? (
          <button
            className="edit-button"
            onClick={() => { setTokuSubStatusError(null); setManagingTokuSub(providerRecordDetail.record); }}
          >
            Gestionar estado
          </button>
        ) : null}
        {(deletableResources[providerRecordDetail.record.source] ?? []).includes(providerRecordDetail.record.resource_type) ? (
          <button
            className="delete-button"
            onClick={() => { setProviderDeleteError(null); setDeletingRecord({
              record: providerRecordDetail.record,
              source: providerRecordDetail.record.source,
              resourceType: providerRecordDetail.record.resource_type,
            }); }}
          >
            Eliminar
          </button>
        ) : null}
      </div>
      {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "payment_method" ? (
        <TokuPaymentMethodProfile payload={providerRecordDetail.record.payload} />
      ) : (
        <section className="panel">
          <p className="eyebrow">FICHA COMPLETA</p>
          <dl className="field-list">
            {Object.entries(providerRecordDetail.record.payload).flatMap(
              ([field, value]) => {
                const entries = objectEntries(value);
                if (entries.length) {
                  return entries.map(([subField, subValue]) => (
                    <div key={`${field}-${subField}`}>
                      <dt>
                        {field === "recurring"
                          ? `Recurrencia ${recurringFieldLabels[subField] ?? fieldLabel(subField)}`
                          : `${fieldLabel(field)} — ${fieldLabel(subField)}`}
                      </dt>
                      <dd>{text(subValue)}</dd>
                    </div>
                  ));
                }
                return [
                  <div key={field}>
                    <dt>{fieldLabel(field)}</dt>
                    <dd>{text(value)}</dd>
                  </div>,
                ];
              },
            )}
          </dl>
        </section>
      )}
      {providerRecordDetail.related.map((group) => (
        <section
          className="panel client-subscriptions"
          key={group.resource_type}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{group.label.toUpperCase()}</p>
              <h3>Registros relacionados</h3>
            </div>
            <span>{group.items.length} total</span>
          </div>
          {group.items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    {tokuRelatedColumns(group.resource_type).map((column) => (
                      <th key={column.label}>{column.label}</th>
                    ))}
                    <th>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {group.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <button
                          className="record-link"
                          onClick={() =>
                            void openProviderRecord(
                              item.source as ProviderSource,
                              group.resource_type,
                              item,
                            )
                          }
                        >
                          {text(item.payload.id, item.external_id)}
                        </button>
                      </td>
                      {tokuRelatedColumns(group.resource_type).map((column) => (
                        <td key={column.label}>{column.value(item)}</td>
                      ))}
                      <td className="action-cell">
                        {item.source === "toku" && group.resource_type === "subscription" ? (
                          <button
                            className="edit-button"
                            onClick={() => { setTokuSubStatusError(null); setManagingTokuSub(item); }}
                          >
                            Gestionar estado
                          </button>
                        ) : null}
                        {(providerEditFields[item.source]?.[group.resource_type] ?? []).length > 0 && !(item.source === "toku" && group.resource_type === "subscription") ? (
                          <button
                            className="edit-button"
                            onClick={() => { setProviderEditError(null); setEditingProviderRecord({ record: item, source: item.source, resourceType: group.resource_type }); }}
                          >
                            Editar
                          </button>
                        ) : null}
                        {(deletableResources[item.source] ?? []).includes(group.resource_type) && !(item.source === "toku" && group.resource_type === "subscription") ? (
                          <button
                            className="delete-button"
                            onClick={() => { setProviderDeleteError(null); setDeletingRecord({ record: item, source: item.source, resourceType: group.resource_type }); }}
                          >
                            Eliminar
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>Sin registros relacionados.</p>
          )}
        </section>
      ))}
    </main>
  ) : null;
  const filterOptions = activeSection
    ? (stagingFilters[activeSection.source]?.[activeSection.resource] ?? [])
    : [];
  const availableStatuses = ["status", "secondary_status"].includes(filterField) ? statusValues : [];
  const isStatusFilter = ["status", "secondary_status"].includes(filterField);
  const filterControls = activeSection?.source === "virtualpos" ? null : filterOptions.length ? (
    <section
      className="record-filters"
      aria-label={`Filtros ${activeSection?.label}`}
    >
      <div className="record-filters-copy">
        <p className="eyebrow">BÚSQUEDA</p>
        <strong>Filtrar registros</strong>
      </div>
      <label>
        Campo
        <select
          value={filterField}
          onChange={(event) => {
            setFilterField(event.target.value);
            setFilterQuery("");
            setRecordsOffset(0);
          }}
        >
          {filterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="record-filter-query">
        {isStatusFilter ? (filterField === "secondary_status" ? "Estado secundario" : "Estado") : "Buscar"}
        {isStatusFilter ? (
          <select
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
          >
            <option value="">Todos los estados</option>
            {availableStatuses.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        ) : (
          <input
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
            placeholder={`Buscar por ${filterOptions.find((option) => option.value === filterField)?.label ?? "campo"}`}
          />
        )}
      </label>
      <button
        className="clear-filter-button"
        disabled={!filterQuery && filterField === filterOptions[0]?.value}
        onClick={() => {
          setFilterField(filterOptions[0]?.value ?? "");
          setFilterQuery("");
          setRecordsOffset(0);
        }}
      >
        Restablecer
      </button>
    </section>
  ) : null;
  const recoveryView = recoveryOpen ? <RecoveryPanel channel="virtualpos" can={can} /> : null;
  const billingView = billingOpen ? <BillingInbox can={can} currentUserId={session?.user.id} isAdmin={session?.user.roles.some((role) => role.name === "admin") ?? false} /> : null;

  const providerDetail = activeSection ? (
    <main className="app-shell detail-page provider-page">
      <button
        className="back-button"
        onClick={() => showChannel(activeSection.source)}
      >
        Volver al resumen {title(activeSection.source)}
      </button>
      <p className="eyebrow">
        {title(activeSection.source).toUpperCase()} / STAGING
      </p>
      <h2>{activeSection.label}</h2>
      {filterControls}
      {activeSection.source === "virtualpos" ? (
        <div className="vp-platform-filter">
          {(["all", "virtualpos1", "virtualpos2"] as const).filter((p) => p !== "virtualpos2" || vp2Enabled).map((p) => (
            <button
              key={p}
              className={`vp-platform-btn${vpPlatform === p ? " active" : ""}`}
              onClick={() => { setVpPlatform(p); setRecordsOffset(0); }}
            >
              {p === "all" ? "Todas" : p === "virtualpos1" ? "VP 1" : "VP 2"}
            </button>
          ))}
          <button
            className="clear-filter-button"
            disabled={!Object.values(vpColumnFilters).some((value) => value.trim())}
            onClick={() => { setVpColumnFilters({}); setRecordsOffset(0); }}
          >
            Limpiar filtros
          </button>
        </div>
      ) : null}
      <section className="panel provider-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SOURCE RECORDS</p>
            <h3>Payloads saneados almacenados localmente</h3>
          </div>
          <span aria-live="polite">{loading ? "Cargando" : `${records.total} registros`}</span>
        </div>
        {activeSection.source === "virtualpos" && activeSection.resource === "client" ? (
          <button className="new-client-button" onClick={() => setCreatingClient(true)}>+ Nuevo cliente</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "plan" ? (
          <button className="new-client-button" onClick={() => { setPlanFormError(null); setPlanFieldErrors({}); setPlanSaveNotice(null); setCreatingPlan(true); }}>+ Nuevo plan</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "subscription" ? (
          <button className="new-client-button" onClick={() => { setSubscriptionFormError(null); setSubscriptionFieldErrors({}); setSubscriptionSaveNotice(null); setCreatingSubscription(true); }}>+ Nueva suscripción</button>
        ) : null}
        {clientSaveNotice ? <p className="success-message" role="status">{clientSaveNotice}</p> : null}
        {planSaveNotice ? <p className="success-message" role="status">{planSaveNotice}</p> : null}
        {subscriptionSaveNotice ? <p className="success-message" role="status">{subscriptionSaveNotice}</p> : null}
        {chargeSaveNotice ? <p className="success-message" role="status">{chargeSaveNotice}</p> : null}
        {error ? <p className="error-message">{error}</p> : null}
        {!loading && !error && records.items.length === 0 ? (
          <p>Sin registros sincronizados para este recurso.</p>
        ) : null}
        {records.items.length > 0 ? (
          <div className="table-wrap">
            <table>
                <thead>
                  <tr>
                  {columns.map((column) => {
                    const sortable = Boolean(activeSection && filterFieldForColumn(activeSection.source, activeSection.resource, column.label));
                    const activeSort = sortColumn === column.label;
                    return (
                      <th
                        key={column.label}
                        aria-sort={activeSort ? (sortDirection === "asc" ? "ascending" : "descending") : undefined}
                      >
                        {sortable ? (
                          <button
                            className={`table-sort-button${activeSort ? " active" : ""}`}
                            title={`Ordenar por ${column.label}${activeSort ? " en sentido inverso" : ""}`}
                            onClick={() => toggleColumnSort(column)}
                          >
                            {column.label}
                            <span className="table-sort-indicator" aria-hidden="true">
                              {activeSort ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
                            </span>
                          </button>
                        ) : column.label}
                      </th>
                    );
                  })}
                  </tr>
                  {activeSection.source === "virtualpos" ? (
                    <tr className="table-column-filters">
                      {columns.map((column) => {
                        const field = virtualPosFieldForColumn(activeSection.resource, column.label);
                        if (!field) return <th key={column.label} />;
                        const update = (key: string, value: string) => {
                          setVpColumnFilters((current) => ({ ...current, [key]: value }));
                          setRecordsOffset(0);
                        };
                        if (field === "amount") {
                          return <th key={column.label} className="range-filter"><input aria-label="Monto mínimo" type="number" value={vpColumnFilters.amount_min ?? ""} onChange={(event) => update("amount_min", event.target.value)} placeholder="Mín." /><input aria-label="Monto máximo" type="number" value={vpColumnFilters.amount_max ?? ""} onChange={(event) => update("amount_max", event.target.value)} placeholder="Máx." /></th>;
                        }
                        if (["suscription_date", "canceled_at", "charge_date", "authorized_at"].includes(field)) {
                          return <th key={column.label} className="range-filter"><input aria-label={`${column.label} desde`} type="date" value={vpColumnFilters.date_from ?? ""} onChange={(event) => update("date_from", event.target.value)} /><input aria-label={`${column.label} hasta`} type="date" value={vpColumnFilters.date_to ?? ""} onChange={(event) => update("date_to", event.target.value)} /></th>;
                        }
                        return <th key={column.label}><input aria-label={`Buscar por ${column.label}`} value={vpColumnFilters[field] ?? ""} onChange={(event) => update(field, event.target.value)} placeholder="Buscar" /></th>;
                      })}
                    </tr>
                  ) : null}
                </thead>
              <tbody>
                {records.items.map((record) => (
                  <tr key={record.id}>
                    {columns.map((column) => (
                      <td key={column.label}>
                        {activeSection.source === "virtualpos" &&
                        activeSection.resource === "subscription" &&
                        column.label === "Acciones" ? (
                          isActiveSubscription(record) ? (
                            <div className="table-actions-group">
                              <button
                                className="cancel-subscription-button cancel-subscription-button-table"
                                onClick={() => setCancelingSubscription(record)}
                              >
                                Cancelar Sub
                              </button>
                              <button
                                className="create-charge-button create-charge-button-table"
                                onClick={() => { setChargeFormError(null); setChargeFieldErrors({}); setChargeSaveNotice(null); setCreatingCharge(record); }}
                              >
                                + Cargo
                              </button>
                            </div>
                          ) : (
                            "-"
                          )
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "charge" &&
                          column.label === "ID subscripción" ? (
                          record.subscription_id ? (
                            <button
                              className="record-link"
                              aria-label={`Ver ficha de subscripción ${record.subscription_id}`}
                              onClick={() => void openVirtualPosSubscription({ external_id: record.subscription_id! })}
                            >
                              {record.subscription_id}
                            </button>
                          ) : (
                            <span>{column.value(record)}</span>
                          )
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "payment" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de transacción ${column.value(record)}`}
                            onClick={() => void openVirtualPosPayment(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "charge" &&
                          column.label === "Acciones" ? (
                          <div className="table-actions-group">
                            {isPendingCharge(record) ? (
                              <button
                                className="cancel-charge-button"
                                onClick={() => { setCancelChargeError(null); setCancelingCharge(record); }}
                              >
                                Cancelar
                              </button>
                            ) : isRejectedCharge(record) && can("virtualpos.charges.retry") ? (
                              <button
                                className="retry-charge-button"
                                onClick={() => { setRetryChargeError(null); setRetryingCharge(record); }}
                              >
                                Reintentar
                              </button>
                            ) : null}
                          </div>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "Acciones" ? (
                          <button
                            className="edit-button edit-button-table"
                            onClick={() => setEditingClient(record)}
                          >
                            Editar
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "RUT" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cliente ${column.value(record)}`}
                            onClick={() => void openVirtualPosClient(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "plan" &&
                          column.label === "Nombre" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de plan ${column.value(record)}`}
                            onClick={() => void openVirtualPosPlan(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "subscription" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de subscripción ${column.value(record)}`}
                            onClick={() =>
                              void openVirtualPosSubscription(record)
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "toku" &&
                          activeSection.resource === "customer" &&
                          column.label === "RUT" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cliente ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord("toku", "customer", record)
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "toku" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord(
                                "toku",
                                activeSection.resource,
                                record,
                              )
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : (activeSection.source === "toku" ||
                            activeSection.source === "payku") &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord(
                                activeSection.source,
                                activeSection.resource,
                                record,
                              )
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : column.label === "Acciones" ? (
                          <div className="table-actions">
                            {(providerEditFields[activeSection.source]?.[activeSection.resource] ?? []).length > 0 ? (
                              <button
                                className="edit-button edit-button-table"
                                onClick={() => setEditingProviderRecord({ record, source: activeSection.source, resourceType: activeSection.resource })}
                              >
                                Editar
                              </button>
                            ) : null}
                            <button
                              className="delete-button delete-button-table"
                              onClick={() => setDeletingRecord({ record, source: activeSection.source, resourceType: activeSection.resource })}
                            >
                              Eliminar
                            </button>
                          </div>
                        ) : column.label === "Estado sec." && record.resource_type === "subscription" ? (
                          <span className={`badge badge-${record.secondary_status === "cobrable" ? "green" : record.secondary_status === "incobrable" ? "orange" : record.secondary_status === "inactiva" ? "gray" : "blue"}`}>{record.secondary_status ?? "—"}</span>
                        ) : (
                          column.value(record)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {records.items.length < records.total ? (
          <div className="table-load-more">
            <span>Mostrando {records.items.length.toLocaleString("es-CL")} de {records.total.toLocaleString("es-CL")}</span>
            <button disabled={loading} onClick={() => setRecordsOffset((offset) => offset + RECORDS_PAGE_SIZE)}>
              {loading ? "Cargando..." : "Ver más"}
            </button>
          </div>
        ) : null}
      </section>
    </main>
  ) : null;
  // ── KPIs filtrados por año seleccionado ─────────────────────────────────────
  const selectedYear = generalData ? (generalYear ?? defaultYear(generalData.years) ?? generalData.years[0]) : null;
  const acceptedForYear = (generalData?.transactions_monthly ?? [])
    .filter(e => e.status === "Aceptadas" && (selectedYear == null || e.year === selectedYear))
    .reduce((acc, e) => ({ count: acc.count + e.count, amount: acc.amount + e.amount }), { count: 0, amount: 0 });
  const rejectedForYear = (generalData?.transactions_monthly ?? [])
    .filter(e => e.status === "Rechazadas" && (selectedYear == null || e.year === selectedYear))
    .reduce((acc, e) => ({ count: acc.count + e.count, amount: acc.amount + e.amount }), { count: 0, amount: 0 });
  const activationsForYear = (generalData?.activations_monthly ?? [])
    .filter(e => selectedYear == null || e.year === selectedYear)
    .reduce((acc, e) => ({ count: acc.count + e.count, amount: acc.amount + e.amount }), { count: 0, amount: 0 });
  const cancellationsAsEntries: MonthlyEntry[] = (() => {
    const map = new Map<string, MonthlyEntry>();
    for (const e of (generalData?.cancellations_monthly ?? [])) {
      const key = `${e.year}-${e.month}`;
      const ex = map.get(key);
      if (ex) { ex.count += e.count; ex.amount += e.amount; }
      else map.set(key, { year: e.year, month: e.month, count: e.count, amount: e.amount });
    }
    return [...map.values()];
  })();

  const globalDashboard = (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">Sx</span>
          <div>
            <p className="eyebrow">OPERACIONES RECURRENTES</p>
            <h1>SynkmetriX</h1>
          </div>
        </div>
        <div className="sync-state ready">
          <span />
          Staging local
        </div>
      </header>
      <section className="hero-panel">
        <div>
          <p className="eyebrow">RESUMEN OPERATIVO</p>
          <h2>
            Operación consolidada,
            <br />
            desde todos los canales.
            {(generalRefreshing || summaryRefreshing) && <span className="refreshing-badge">⟳ Actualizando</span>}
          </h2>
        </div>
        {generalData ? (
          <>
          <div className="dashboard-controls">
            <div className="mode-switch">
              <button className={generalMode === "count" ? "active" : ""} onClick={() => setGeneralMode("count")}>Cantidad</button>
              <button className={generalMode === "amount" ? "active" : ""} onClick={() => setGeneralMode("amount")}>Monto</button>
            </div>
            {generalData.years.length ? (
              <select aria-label="Año dashboard general" value={generalYear ?? defaultYear(generalData.years) ?? generalData.years[0]} onChange={(event) => setGeneralYear(Number(event.target.value))}>
                {generalData.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
              </select>
            ) : null}
            <button className="sync-btn sync-btn-secondary" onClick={() => setReportScope("general")}>Generar reporte</button>
          </div>
          </>
        ) : (
          <p className="sync-copy">KPIs y actividad mensual calculados desde las entidades centralizadas y TCH.</p>
        )}
      </section>
      {error ? <p className="error-message">{error}</p> : null}
      {generalView === "subscriptions" ? (
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES CONSOLIDADAS</p><h3>{generalSubscriptions?.total.toLocaleString("es-CL") ?? ""} suscripciones</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de suscripciones" value={generalSubscriptionFilter} onChange={(event) => { setGeneralSubscriptionFilter(event.target.value as typeof generalSubscriptionFilter); setGeneralSubscriptionOffset(0); }}><option value="all">Todos los campos</option><option value="id">ID</option><option value="rut">RUT</option><option value="client">Cliente</option><option value="platform">Plataforma</option><option value="status">Estado</option></select><input aria-label="Buscar suscripción consolidada" placeholder="Buscar suscripciones" value={generalSubscriptionQuery} onChange={(event) => { setGeneralSubscriptionQuery(event.target.value); setGeneralSubscriptionOffset(0); }} /></div></div>
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Cliente</th><th>RUT</th><th>Plataforma</th><th>Estado</th><th>Estado secundario</th><th>Último cobro</th><th>Inicio</th><th>Término</th><th>Monto</th></tr></thead><tbody>{(generalSubscriptions?.items ?? []).map((subscription) => <tr key={`${subscription.platform}-${subscription.id}`}><td>{subscription.id}</td><td>{subscription.client || "—"}</td><td>{subscription.rut || "—"}</td><td>{subscription.platform}</td><td>{subscription.status || "—"}</td><td><span className={`badge badge-${subscription.secondary_status === "cobrable" ? "green" : subscription.secondary_status === "incobrable" ? "orange" : subscription.secondary_status === "inactiva" ? "gray" : "blue"}`}>{subscription.secondary_status}</span></td><td>{subscription.last_paid_date ? subscription.last_paid_date.slice(0, 10) : "—"}</td><td>{subscription.started_at ?? "—"}</td><td>{subscription.ended_at ?? "—"}</td><td>{subscription.amount ? `${subscription.currency ?? ""} $${Number(subscription.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{(generalSubscriptions?.items ?? []).length === 0 ? <tr><td colSpan={10}>Sin suscripciones.</td></tr> : null}</tbody></table></div>{generalSubscriptions && generalSubscriptions.total > generalSubscriptions.limit ? <div className="pagination"><button disabled={generalSubscriptionOffset === 0} onClick={() => setGeneralSubscriptionOffset((offset) => Math.max(0, offset - generalSubscriptions.limit))}>← Anterior</button><span>{generalSubscriptionOffset + 1}-{Math.min(generalSubscriptionOffset + generalSubscriptions.items.length, generalSubscriptions.total)} de {generalSubscriptions.total.toLocaleString("es-CL")}</span><button disabled={generalSubscriptionOffset + generalSubscriptions.limit >= generalSubscriptions.total} onClick={() => setGeneralSubscriptionOffset((offset) => offset + generalSubscriptions.limit)}>Siguiente →</button></div> : null}
        </section>
      ) : generalView === "clients" ? (
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">CLIENTES CONSOLIDADOS</p><h3>{generalClients?.total.toLocaleString("es-CL") ?? ""} clientes por RUT</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de clientes" value={generalClientFilter} onChange={(event) => { setGeneralClientFilter(event.target.value as typeof generalClientFilter); setGeneralClientOffset(0); }}><option value="all">Todos los campos</option><option value="rut">RUT</option><option value="name">Nombre</option><option value="last_name">Apellido</option><option value="platform">Plataforma</option><option value="email">Correo</option><option value="phone">Teléfono</option></select><input aria-label="Buscar cliente consolidado" placeholder="Buscar clientes" value={generalClientQuery} onChange={(event) => { setGeneralClientQuery(event.target.value); setGeneralClientOffset(0); }} /></div></div>
          {generalClientDetail ? (
            <div className="record-detail"><button onClick={() => setGeneralClientDetail(null)}>← Volver a clientes</button><h3>Ficha general: {generalClientDetail.rut}</h3>{(["clients", "subscriptions", "charges", "transactions"] as const).map((section) => <div key={section}><h4>{section === "clients" ? "IDs de cliente" : section === "subscriptions" ? "Suscripciones" : section === "charges" ? "Cargos" : "Transacciones"}</h4><div className="table-wrap"><table><thead><tr><th>Portal</th><th>ID interno</th><th>ID origen</th><th>Estado</th><th>Monto</th></tr></thead><tbody>{generalClientDetail[section].map((item) => <tr key={`${item.portal}-${item.external_id}`}><td>{item.portal}</td><td>{("id_cliente" in item ? item.id_cliente : "id_subscription" in item ? item.id_subscription : "id_cargo" in item ? item.id_cargo : item.id_transaccion)}</td><td>{item.external_id}</td><td>{"status" in item ? item.status : "—"}</td><td>{"amount" in item && item.amount ? `$${Number(item.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{generalClientDetail[section].length === 0 ? <tr><td colSpan={5}>Sin registros relacionados.</td></tr> : null}</tbody></table></div></div>)}</div>
          ) : <><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre completo</th><th>Plataforma de origen</th><th>Suscripciones activas</th></tr></thead><tbody>{(generalClients?.items ?? []).map((client) => <tr key={client.rut}><td><button className="record-link" onClick={() => getJson<GeneralClientDetail>(`/api/v1/staging/dashboard/general/clients/${encodeURIComponent(client.rut)}`).then(setGeneralClientDetail).catch((err: unknown) => setError(friendlyError(err, "No se pudo cargar la ficha general.")))}>{client.rut}</button></td><td>{client.name || "—"}</td><td>{client.origins.join(" · ")}</td><td>{client.active_origins.join(" · ") || "—"}</td></tr>)}{(generalClients?.items ?? []).length === 0 ? <tr><td colSpan={4}>Sin clientes con RUT.</td></tr> : null}</tbody></table></div>{generalClients && generalClients.total > generalClients.limit ? <div className="pagination"><button disabled={generalClientOffset === 0} onClick={() => setGeneralClientOffset((offset) => Math.max(0, offset - generalClients.limit))}>← Anterior</button><span>{generalClientOffset + 1}-{Math.min(generalClientOffset + generalClients.items.length, generalClients.total)} de {generalClients.total.toLocaleString("es-CL")}</span><button disabled={generalClientOffset + generalClients.limit >= generalClients.total} onClick={() => setGeneralClientOffset((offset) => offset + generalClients.limit)}>Siguiente →</button></div> : null}</>}
        </section>
      ) : generalData ? (
        <>
          <section className="metrics provider-metrics" aria-label="Métricas generales">
            <Metric label="Clientes" value={generalData.clients} tone="blue" />
            <Metric label="Activaciones" value={activationsForYear.count} tone="green" amount={activationsForYear.amount} mode={generalMode} />
            <Metric label="Transacciones pagadas" value={acceptedForYear.count} tone="violet" amount={acceptedForYear.amount} mode={generalMode} />
          </section>
          <GeneralKpis data={generalData} rejectedCount={rejectedForYear.count} acceptedCount={acceptedForYear.count} selectedYear={selectedYear} />
          <section className="extended-charts">
            <article className="panel" style={{ gridColumn: "1 / -1" }}>
              <div className="panel-heading"><div><p className="eyebrow">INGRESOS</p><h3>Recaudación mensual por canal</h3></div></div>
              <IngresosMensualesChart data={generalData.transactions_effective_monthly} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas y bajas por mes</h3></div></div>
              <ActivacionCaidaChart activaciones={generalData.activations_monthly} caidas={cancellationsAsEntries} year={generalYear} mode={generalMode} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">CANALES</p><h3>Comparativa por canal</h3></div></div>
              <ChannelKpiChart channels={generalData.channels as ChannelRow[]} mode={generalMode} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">TRANSACCIONES</p><h3>Estado mensual consolidado</h3></div></div>
              <MonthlyStatusChart data={generalData.transactions_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Activaciones mensuales por canal</h3></div></div>
              <MonthlyStatusChart data={generalData.activations_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Bajas mensuales por canal</h3></div></div>
              <MonthlyStatusChart data={generalData.cancellations_monthly} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading">
                <div><p className="eyebrow">RECAUDACIÓN</p><h3>Deudas mensuales por canal</h3></div>
                <div className="mode-switch">
                  {(["todas", "pagada", "rechazada"] as const).map(f => (
                    <button key={f} className={debtFilter === f ? "active" : ""} onClick={() => setDebtFilter(f)}>
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <MonthlyStatusChart data={applyChargeFilter(generalData.debts_monthly, debtFilter)} mode={generalMode} year={generalYear} />
            </article>
            <article className="panel">
              <div className="panel-heading">
                <div><p className="eyebrow">RECAUDACIÓN</p><h3>Transacciones efectivas por canal</h3></div>
                <div className="mode-switch">
                  {(["todas", "pagada", "rechazada"] as const).map(f => (
                    <button key={f} className={transFilter === f ? "active" : ""} onClick={() => setTransFilter(f)}>
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <MonthlyStatusChart data={applyChargeFilter(generalData.transactions_effective_monthly, transFilter)} mode={generalMode} year={generalYear} />
            </article>
          </section>
          {(generalData.alerts ?? []).length > 0 && <OperationalAlerts alerts={generalData.alerts ?? []} />}
          <section className="source-summary">
            {generalData.channels.map((channel) => {
              const staging = summary.sources.find((source) => source.source === channel.source.toLowerCase());
              const lastSync = staging?.last_sync;
              return (
                <article className="panel channel-summary-card" key={channel.source}>
                  <div className="panel-heading">
                    <div><p className="eyebrow">{channel.source.toUpperCase()}</p><h3>{channel.active_subscriptions.toLocaleString("es-CL")} suscripciones vigentes</h3></div>
                    {lastSync ? <span className={`status-pill ${lastSync.status === "completed" ? "" : "status-attention"}`}>{lastSync.status}</span> : null}
                  </div>
                  <div className="channel-summary-details">
                    <div><span>Operación</span><strong>{channel.clients.toLocaleString("es-CL")} clientes · {channel.accepted.toLocaleString("es-CL")} aceptadas</strong></div>
                    <div><span>Recaudación</span><strong>${channel.amount.toLocaleString("es-CL")}</strong></div>
                    <div><span>{staging ? "Carga staging" : "Carga local"}</span><strong>{staging ? `${staging.records.toLocaleString("es-CL")} registros` : "Histórico TCH integrado"}</strong></div>
                    <div><span>Consolidación</span><strong>Entidades centralizadas disponibles</strong></div>
                  </div>
                  {staging ? <p className="resource-copy">{Object.entries(staging.resources).map(([resource, count]) => `${resource}: ${count}`).join(" · ")}</p> : null}
                  {lastSync?.finished_at ? <p className="channel-summary-sync">Última carga: {new Date(lastSync.finished_at).toLocaleString("es-CL")} · {lastSync.records_processed.toLocaleString("es-CL")} procesados</p> : null}
                </article>
              );
            })}
          </section>
        </>
      ) : (
        <p className="muted-copy">Cargando indicadores consolidados...</p>
      )}
      <section className="etl-panel">
        <div className="etl-panel-heading">
          <div>
            <p className="eyebrow">CONSOLIDACIÓN</p>
            <h3>Base de datos unificada</h3>
          </div>
          <button
            className={`sync-btn ${etlRunning ? "syncing" : ""}`}
            disabled={etlRunning}
            onClick={runFullSync}
          >
            {etlRunning
              ? lastEtlRun?.phase
                ? `Sincronizando ${lastEtlRun.phase.replace("sync_", "")}…`
                : "Procesando…"
              : "↻ Sync completo"}
          </button>
        </div>
        {etlError ? <p className="error-message">{etlError}</p> : null}
        {lastEtlRun ? (
          <div className="etl-status">
            <span className={`status-pill ${lastEtlRun.status === "completed" ? "" : lastEtlRun.status === "failed" ? "status-attention" : ""}`}>
              {lastEtlRun.status}
            </span>
            {lastEtlRun.phase && lastEtlRun.status === "running" ? (
              <span className="etl-phase-badge">{lastEtlRun.phase}</span>
            ) : null}
            <span className="muted-copy">
              {lastEtlRun.records_upserted.toLocaleString()} registros
              {lastEtlRun.finished_at
                ? ` · ${new Date(lastEtlRun.finished_at).toLocaleString("es-CL")}`
                : " · en progreso…"}
            </span>
            {lastEtlRun.error_message ? (
              <p className="error-message">{lastEtlRun.error_message}</p>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
  const createRequiredFields = new Set(["first_name", "email", "social_id", "social_id_type"]);
  const createDefaultValues: Record<string, string> = { status: "ACTIVO", type: "PERSONA", social_id_type: "1" };
  const clientEditDialog = editingClient || creatingClient ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form className="edit-dialog" aria-modal="true" aria-label={creatingClient ? "Crear cliente VirtualPOS" : "Editar cliente VirtualPOS"} noValidate onSubmit={creatingClient ? createVirtualPOSClient : saveVirtualPOSClient}>
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / {creatingClient ? "CREACIÓN" : "EDICIÓN"}</p>
            <h3>{creatingClient ? "Nuevo cliente" : "Editar cliente"}</h3>
          </div>
          {!creatingClient && editingClient ? <span>{text(editingClient.payload.uuid, editingClient.external_id)}</span> : null}
        </div>
        <p className="edit-dialog-note">
          {creatingClient
            ? "Los campos marcados con * son obligatorios. El cliente se creará en VirtualPOS y en la base de datos local."
            : "Los cambios se aplican mediante la API interna. VirtualPOS debe estar habilitado localmente para completar el guardado."}
        </p>
        {creatingClient && (
          <div className="vp-account-selector">
            <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
            <div className="vp-account-selector-buttons">
              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos1")}>
                Cuenta 1
              </button>
{vp2Enabled && (              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos2")}>
                Cuenta 2
              </button>)}
            </div>
          </div>
        )}
        <div className="edit-form-grid">
          {virtualPosClientEditFields.map((field) => {
            const isRequired = creatingClient && createRequiredFields.has(field.name);
            const hasError = Boolean(clientFieldErrors[field.name]);
            const defaultVal = creatingClient
              ? (createDefaultValues[field.name] ?? "")
              : (field.name === "social_id_type" ? documentType(editingClient!.payload[field.name]) : text(editingClient!.payload[field.name], ""));
            return (
              <label className={hasError ? "field-error" : ""} key={field.name}>
                {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                {field.options ? (
                  <select
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    name={field.name}
                    defaultValue={defaultVal}
                  >
                    {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                ) : (
                  <input
                    name={field.name}
                    type={field.type ?? "text"}
                    defaultValue={defaultVal}
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    placeholder={field.name === "social_id" ? (creatingClient ? "Ej: 12345678-9" : undefined) : undefined}
                  />
                )}
                {hasError ? <span className="field-error-message">{clientFieldErrors[field.name]}</span> : null}
              </label>
            );
          })}
          <label className="edit-form-wide">
            Nota privada
            <textarea name="private_note" defaultValue={creatingClient ? "" : text(editingClient!.payload.private_note, "")} />
          </label>
        </div>
        {clientFormError ? <p className="error-message form-error">{clientFormError}</p> : null}
        <div className="edit-dialog-actions">
          <button type="submit" className="save-button" disabled={savingClient}>
            {savingClient ? "Guardando..." : creatingClient ? "Crear cliente" : "Guardar cambios"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setEditingClient(null); setCreatingClient(false); }}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null;
  const subscriptionCancelDialog = cancelingSubscription ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar subscripción VirtualPOS">
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / CANCELACIÓN</p>
            <h3>¿Estás seguro de cancelar esta suscripción?</h3>
          </div>
          <span>{text(cancelingSubscription.payload.id, cancelingSubscription.external_id)}</span>
        </div>
        <p className="edit-dialog-note">
          Esta acción cancelará la suscripción en VirtualPOS (DELETE /v3/suscription/…). Los cargos futuros se detendrán y no se puede deshacer.
        </p>
        {cancelSubscriptionError && <p className="edit-dialog-error">{cancelSubscriptionError}</p>}
        <div className="edit-dialog-actions">
          <button
            type="button"
            className="cancel-subscription-button"
            disabled={savingCancelSubscription}
            onClick={() => void cancelVirtualPOSSubscription()}
          >
            {savingCancelSubscription ? "Cancelando..." : "Confirmar cancelación"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setCancelingSubscription(null); setCancelSubscriptionError(null); }}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null;
  const isTokuWritable = editingProviderRecord?.source === "toku" && editingProviderRecord?.resourceType === "customer";
  const isPaykuWritable = editingProviderRecord?.source === "payku" && editingProviderRecord?.resourceType === "client";
  const isProviderWritable = isTokuWritable || isPaykuWritable;
  const providerEditDialog = editingProviderRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form
        className="edit-dialog"
        aria-modal="true"
        aria-label={`Editar ${resourceTitle(editingProviderRecord.resourceType)}`}
        noValidate
        onSubmit={isProviderWritable ? saveProviderEdit : (e) => e.preventDefault()}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(editingProviderRecord.source).toUpperCase()} / EDICIÓN
            </p>
            <h3>Editar {resourceTitle(editingProviderRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(editingProviderRecord.record.payload.id, editingProviderRecord.record.external_id)}
          </span>
        </div>
        {!isProviderWritable ? (
          <p className="edit-dialog-note">
            Formulario visual. El guardado remoto permanece deshabilitado mientras{" "}
            {title(editingProviderRecord.source)} opere en modo solo lectura.
          </p>
        ) : null}
        <div className="edit-form-grid">
          {(providerEditFields[editingProviderRecord.source]?.[editingProviderRecord.resourceType] ?? []).map(
            (field) => (
              <label key={field.name}>
                {field.label}
                <input
                  name={field.name}
                  type={field.type ?? "text"}
                  defaultValue={text(editingProviderRecord.record.payload[field.name], "")}
                />
              </label>
            ),
          )}
        </div>
        {providerEditError ? <p className="error-message form-error">{providerEditError}</p> : null}
        <div className="edit-dialog-actions">
          {isProviderWritable ? (
            <button type="submit" className="save-button" disabled={savingProviderEdit}>
              {savingProviderEdit ? "Guardando..." : "Guardar cambios"}
            </button>
          ) : (
            <button type="button" className="save-button" disabled title="Guardado remoto no habilitado">
              Guardar cambios
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setEditingProviderRecord(null)}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null;
  const providerDeleteDialog = deletingRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section
        className="edit-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Eliminar ${resourceTitle(deletingRecord.resourceType)}`}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(deletingRecord.source).toUpperCase()} / ELIMINACIÓN
            </p>
            <h3>Eliminar {resourceTitle(deletingRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(deletingRecord.record.payload.id, deletingRecord.record.external_id)}
          </span>
        </div>
        <p className="edit-dialog-note">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription"))
            ? `Se enviará DELETE ${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)} a ${title(deletingRecord.source)}. Esta acción no se puede deshacer.`
            : `Esta acción utilizará DELETE \`${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)}\` cuando se habilite la escritura. Actualmente ${title(deletingRecord.source)} permanece en modo solo lectura.`}
        </p>
        {providerDeleteError ? <p className="error-message form-error">{providerDeleteError}</p> : null}
        <div className="edit-dialog-actions">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription")) ? (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled={savingProviderDelete}
              onClick={() => void confirmProviderDelete()}
            >
              {savingProviderDelete ? "Eliminando..." : "Confirmar eliminación"}
            </button>
          ) : (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled
              title="Eliminación remota no habilitada"
            >
              Confirmar eliminación
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setDeletingRecord(null)}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null;
  const tchContent = tchView ? (
    tchLoading ? (
      <main className="app-shell"><p className="muted-copy">Cargando datos TCH...</p></main>
    ) : tchError ? (
      <main className="app-shell"><p className="error-message">{tchError}</p></main>
    ) : tchView === "summary" && tchSummary ? (
      <main className="app-shell channel-dashboard-page">
        <p className="eyebrow">TCH / CANAL</p>
        <header className="channel-hero">
          <div>
            <h2>Resumen operativo {tchRefreshing && <span className="refreshing-badge">⟳ Actualizando</span>}</h2>
            <p>Datos cargados desde reportes Excel mensuales vía ETL.</p>
          </div>
          <div className="channel-hero-controls">
            <div className="dashboard-controls">
              <div className="mode-switch">
                <button className={tchMode === "count" ? "active" : ""} onClick={() => setTchMode("count")}>Cantidad</button>
                <button className={tchMode === "amount" ? "active" : ""} onClick={() => setTchMode("amount")}>Monto</button>
              </div>
              {tchSummary.years.length ? (
                <select aria-label="Año TCH" value={tchYear ?? defaultYear(tchSummary.years) ?? tchSummary.years[0]} onChange={(event) => setTchYear(Number(event.target.value))}>
                  {tchSummary.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
                </select>
              ) : null}
              <button className="sync-btn sync-btn-secondary" onClick={() => setReportScope("tch")}>Generar reporte</button>
            </div>
            {tchSummary.ultimo_etl.started_at ? (
              <>
              <div className={`sync-state ${tchSummary.ultimo_etl.status === "completed" ? "ready" : "attention"}`}>
                <span />{tchSummary.ultimo_etl.status ?? "Sin ETL"}
              </div>
              <p className="muted-copy" style={{ fontSize: "0.78rem" }}>
                Último ETL: {tchSummary.ultimo_etl.started_at?.slice(0, 10)} · {(tchSummary.ultimo_etl.records_upserted ?? 0).toLocaleString("es-CL")} registros
              </p>
              </>
            ) : null}
          </div>
        </header>
        <section className="metrics provider-metrics" aria-label="KPIs TCH">
          <Metric label="Suscripciones vigentes" value={tchSummary.suscripciones.vigentes} tone="green" amount={tchSummary.suscripciones.monto_vigentes} mode={tchMode} />
          <Metric label="Suscripciones eliminadas" value={tchSummary.suscripciones.eliminadas} tone="orange" amount={tchSummary.suscripciones.monto_eliminadas} mode={tchMode} />
          <Metric label="Total suscripciones" value={tchSummary.suscripciones.total} tone="blue" amount={tchSummary.suscripciones.monto_total} mode={tchMode} />
          <Metric label="Total transacciones" value={tchSummary.transacciones.total} tone="violet" amount={tchSummary.transacciones.monto} mode={tchMode} />
        </section>
        <ChannelKpiStrip kpis={normalizeKpis("tch", tchSummary.kpis, tchSummary.churn_window_label)} ariaLabel="KPIs financieros TCH" />
        <section className="metrics kpi-metrics" aria-label="KPIs transacciones TCH">
          <KpiCard label="Aceptadas" value={tchSummary.transacciones.aceptadas} format="count" caption="Transacciones cobradas" />
          <KpiCard label="Rechazadas" value={tchSummary.transacciones.rechazadas} format="count" caption="Transacciones fallidas" />
          <KpiCard label="Tasa de rechazo" value={tchSummary.transacciones.tasa_rechazo_pct} format="percent" caption="Rechazadas / total" emptyCaption="Sin base para calcular" />
        </section>
        <section className="extended-charts">
          {(() => {
            const tx = statusStackedChart(tchSummary.transacciones_mensuales, tchMode);
            const note = tchSourceNote(tchSummary.transacciones_fuente);
            return tx.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Transacciones mensuales</h3></div></div>
                <ChannelChart series={tx.series} data={tx.rows} kind="stacked" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de transacciones mensuales de TCH por estado" />
                {note ? <p className="muted-copy">{note}</p> : null}
              </article>
            ) : null;
          })()}
          {(() => {
            const ab = activationVsChurnChart(tchSummary.activaciones_mensuales, tchSummary.bajas_mensuales, tchMode);
            return ab.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas vs bajas</h3></div></div>
                <ChannelChart series={ab.series} data={ab.rows} kind="grouped" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de altas y bajas mensuales de suscripciones TCH" />
              </article>
            ) : null;
          })()}
          {tchSummary.activaciones_mensuales?.length && tchSummary.bajas_mensuales?.length ? (
            <>
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
                <CrecimientoMensualChart
                  activaciones={tchSummary.activaciones_mensuales}
                  caidas={aggregateChurn(tchSummary.bajas_mensuales)}
                  year={tchYear}
                  mode={tchMode}
                />
              </article>
            </>
          ) : null}
          {tchSummary.churn_rate_monthly.length ? (
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
              <ChurnMensualChart data={tchSummary.churn_rate_monthly} year={tchYear} />
            </article>
          ) : null}
        </section>
        <OperationalAlerts alerts={tchSummary.alerts ?? []} />
        <section className="panel channel-resources">
          <div><p className="eyebrow">EXPLORAR TCH</p><h3>Vistas disponibles</h3></div>
          <div>
            <button onClick={() => showTch("suscripciones")}>Suscripciones<span>{tchSummary.suscripciones.total}</span></button>
            <button onClick={() => showTch("transacciones")}>Transacciones<span>{tchSummary.transacciones.total}</span></button>
          </div>
        </section>
      </main>
    ) : tchView === "cliente-detalle" && tchClienteDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("clientes")}>← Clientes TCH</button>
        <p className="eyebrow">TCH / CLIENTE</p>
        <header className="detail-header"><div><h2>{[tchClienteDetail.nombre, tchClienteDetail.apellido].filter(Boolean).join(" ") || "Cliente TCH"}</h2><p>{tchClienteDetail.rut}</p></div></header>
        <section className="detail-grid"><article className="panel"><h3>Datos personales</h3><dl><dt>RUT</dt><dd>{tchClienteDetail.rut}</dd><dt>Fecha de nacimiento</dt><dd>{tchClienteDetail.fecha_nacimiento ?? "—"}</dd><dt>Profesión</dt><dd>{tchClienteDetail.profesion ?? "—"}</dd><dt>Tipo de socio</dt><dd>{tchClienteDetail.tipo_socio ?? "—"}</dd></dl></article><article className="panel"><h3>Contacto</h3><dl><dt>Email</dt><dd>{tchClienteDetail.email ?? "—"}</dd><dt>Teléfono</dt><dd>{tchClienteDetail.telefono ?? "—"}</dd><dt>Dirección</dt><dd>{tchClienteDetail.direccion ?? "—"}</dd><dt>Comuna</dt><dd>{tchClienteDetail.comuna ?? "—"}</dd><dt>Ciudad</dt><dd>{tchClienteDetail.ciudad ?? "—"}</dd></dl></article><article className="panel"><h3>Mandatos</h3><p className="metric-value">{(tchClienteDetail.suscripciones ?? []).length.toLocaleString("es-CL")}</p><p className="muted-copy">Suscripciones TCH asociadas</p></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Mandatos asociados</h3></div></div><div className="table-wrap"><table><thead><tr><th>Ficha</th><th>Inicio</th><th>Fin</th><th>Monto</th><th>Estado</th><th>Estado sec.</th><th>Último cobro</th></tr></thead><tbody>{(tchClienteDetail.suscripciones ?? []).map((s) => <tr key={s.id}><td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td><td>{s.fecha_activacion ?? "—"}</td><td>{s.fecha_fin ?? "—"}</td><td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td><td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td><td><span className={`badge badge-${s.secondary_status === "cobrable" ? "green" : s.secondary_status === "incobrable" ? "orange" : s.secondary_status === "inactiva" ? "gray" : "blue"}`}>{s.secondary_status}</span></td><td>{s.last_paid_date ? s.last_paid_date.slice(0, 10) : "—"}</td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "suscripcion-detalle" && tchSuscripcionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("suscripciones")}>← Suscripciones TCH</button>
        <p className="eyebrow">TCH / SUSCRIPCIÓN</p>
        <header className="detail-header"><div><h2>Ficha {tchSuscripcionDetail.numero_ficha}</h2><p>Mandato físico e historial de cargos.</p></div><span className={`status-pill${tchSuscripcionDetail.estado === "VIGENTE" ? "" : " status-attention"}`}>{tchSuscripcionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Mandato</h3><dl><dt>Inicio</dt><dd>{tchSuscripcionDetail.fecha_activacion ?? "—"}</dd><dt>Fin</dt><dd>{tchSuscripcionDetail.fecha_fin ?? "—"}</dd><dt>Motivo</dt><dd>{tchSuscripcionDetail.razon_baja ?? "—"}</dd><dt>Monto (CLP)</dt><dd>{(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto) ? `$${Number(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Banco</dt><dd>{tchSuscripcionDetail.banco_nombre ?? "—"}</dd><dt>RUT cliente</dt><dd>{tchSuscripcionDetail.cliente_rut ?? "—"}</dd><dt>Último cobro</dt><dd>{tchSuscripcionDetail.last_paid_date ? tchSuscripcionDetail.last_paid_date.slice(0, 10) : "—"}</dd><dt>Estado sec.</dt><dd><span className={`badge badge-${tchSuscripcionDetail.secondary_status === "cobrable" ? "green" : tchSuscripcionDetail.secondary_status === "incobrable" ? "orange" : tchSuscripcionDetail.secondary_status === "inactiva" ? "gray" : "blue"}`}>{tchSuscripcionDetail.secondary_status}</span></dd></dl></article><article className="panel"><h3>Captación</h3><dl><dt>Origen</dt><dd>{tchSuscripcionDetail.origen ?? "—"}</dd><dt>Centro de costo</dt><dd>{tchSuscripcionDetail.centro_costo ?? "—"}</dd><dt>Captador</dt><dd>{tchSuscripcionDetail.captador ?? "—"}</dd><dt>Mandato</dt><dd>{tchSuscripcionDetail.numero_mandato ?? "—"}</dd><dt>Tipo de cuenta</dt><dd>{tchSuscripcionDetail.tipo_cuenta ?? "—"}</dd></dl></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Historial</h3></div></div><div className="table-wrap"><table><thead><tr><th>Período</th><th>Monto</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{tchSuscripcionDetail.transacciones.map((t) => <tr key={t.id}><td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.periodo ?? "—"}</button></td><td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td><td>{t.fecha_cargo ?? "—"}</td><td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "transaccion-detalle" && tchTransaccionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("transacciones")}>← Transacciones TCH</button>
        <p className="eyebrow">TCH / TRANSACCIÓN</p>
        <header className="detail-header"><div><h2>Cargo {tchTransaccionDetail.periodo ?? "sin período"}</h2><p>Ficha {tchTransaccionDetail.numero_ficha}</p></div><span className={`status-pill${tchTransaccionDetail.estado === "ACEPTADA" ? "" : " status-attention"}`}>{tchTransaccionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Detalle del cargo</h3><dl><dt>Monto</dt><dd>{tchTransaccionDetail.monto ? `$${Number(tchTransaccionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Fecha de cargo</dt><dd>{tchTransaccionDetail.fecha_cargo ?? "—"}</dd><dt>Cuota</dt><dd>{tchTransaccionDetail.numero_cuota ?? "—"}</dd><dt>Entidad</dt><dd>{tchTransaccionDetail.entidad_recaudadora ?? "—"}</dd><dt>Motivo</dt><dd>{tchTransaccionDetail.razon_rechazo ?? "—"}</dd></dl></article><article className="panel"><h3>Suscripción</h3>{tchTransaccionDetail.suscripcion ? <dl><dt>Ficha</dt><dd><button className="record-link" onClick={() => showTchSuscripcion(tchTransaccionDetail.numero_ficha)}>{tchTransaccionDetail.numero_ficha}</button></dd><dt>RUT cliente</dt><dd>{tchTransaccionDetail.suscripcion.cliente_rut ?? "—"}</dd><dt>Banco</dt><dd>{tchTransaccionDetail.suscripcion.banco_nombre ?? "—"}</dd><dt>Inicio</dt><dd>{tchTransaccionDetail.suscripcion.fecha_activacion ?? "—"}</dd></dl> : <p className="muted-copy">No hay suscripción local asociada.</p>}</article></section>
      </main>
    ) : tchView === "clientes" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / CLIENTES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}><div><h2>Clientes TCH</h2><p>Socios asociados a mandatos físicos.</p></div><div className="dashboard-controls"><input aria-label="Buscar cliente" placeholder="Buscar por nombre" value={tchClienteFiltro} onChange={(event) => { setTchClienteFiltro(event.target.value); setTchClientesPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} /></div></header>
        <section className="panel"><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre</th><th>Fecha nacimiento</th><th>Profesión</th><th>Tipo socio</th></tr></thead><tbody>{(tchClientes?.items ?? []).map((c) => <tr key={c.id}><td><button className="record-link" onClick={() => showTchCliente(c.rut)}>{c.rut}</button></td><td>{[c.nombre, c.apellido].filter(Boolean).join(" ") || "—"}</td><td>{c.fecha_nacimiento ?? "—"}</td><td>{c.profesion ?? "—"}</td><td>{c.tipo_socio ?? "—"}</td></tr>)}{(tchClientes?.items ?? []).length === 0 ? <tr><td colSpan={5}>Sin registros.</td></tr> : null}</tbody></table></div>{tchClientes && tchClientes.pages > 1 ? <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}><button disabled={tchClientesPage <= 1} onClick={() => setTchClientesPage((page) => page - 1)}>← Anterior</button><span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchClientesPage} / {tchClientes.pages} ({tchClientes.total.toLocaleString("es-CL")} total)</span><button disabled={tchClientesPage >= tchClientes.pages} onClick={() => setTchClientesPage((page) => page + 1)}>Siguiente →</button></div> : null}</section>
      </main>
    ) : tchView === "suscripciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / SUSCRIPCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Suscripciones TCH</h2><p>Mandatos activos e históricos de débito físico.</p></div>
          <div className="dashboard-controls">
            <select aria-label="Filtrar por estado" value={tchSusFiltroEstado} onChange={(e) => { setTchSusFiltroEstado(e.target.value); setTchSusPage(1); }}>
              <option value="">Todos los estados</option>
              <option value="VIGENTE">Vigentes</option>
              <option value="ELIMINADA">Eliminadas</option>
            </select>
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>RUT cliente</th><th>Banco</th>
                <th>Tipo mandato</th><th>Origen</th><th>Centro costo</th>
                <th>Monto</th><th>F. Activación</th><th>Estado</th>
                <th>Estado sec.</th><th>Último cobro</th>
              </tr></thead>
              <tbody>
                {(tchSuscripciones?.items ?? []).map((s) => (
                  <tr key={s.id}>
                    <td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td>
                    <td>{s.cliente_rut ?? "—"}</td>
                    <td>{s.banco_nombre ?? "—"}</td>
                    <td>{s.tipo_mandato ?? "—"}</td>
                    <td>{s.origen ?? "—"}</td>
                    <td>{s.centro_costo ?? "—"}</td>
                    <td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{s.fecha_activacion ?? "—"}</td>
                    <td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td>
                    <td><span className={`badge badge-${s.secondary_status === "cobrable" ? "green" : s.secondary_status === "incobrable" ? "orange" : s.secondary_status === "inactiva" ? "gray" : "blue"}`}>{s.secondary_status}</span></td>
                    <td>{s.last_paid_date ? s.last_paid_date.slice(0, 10) : "—"}</td>
                  </tr>
                ))}
                {(tchSuscripciones?.items ?? []).length === 0 ? <tr><td colSpan={11}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchSuscripciones && tchSuscripciones.pages > 1 ? (
            <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchSusPage <= 1} onClick={() => setTchSusPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchSusPage} / {tchSuscripciones.pages} ({tchSuscripciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchSusPage >= tchSuscripciones.pages} onClick={() => setTchSusPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : tchView === "transacciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / TRANSACCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Transacciones TCH</h2><p>Historial de cargos aceptados y rechazados.</p></div>
          <div className="dashboard-controls">
            <input type="month" aria-label="Filtrar por período" value={tchTransFiltroPeriodo} onChange={(e) => { setTchTransFiltroPeriodo(e.target.value); setTchTransPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>Período</th><th>Entidad</th>
                <th>Monto</th><th>Fecha cargo</th><th>Cuota</th><th>Estado</th>
              </tr></thead>
              <tbody>
                {(tchTransacciones?.items ?? []).map((t) => (
                  <tr key={t.id}>
                    <td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.numero_ficha}</button></td>
                    <td>{t.periodo ?? "—"}</td>
                    <td>{t.entidad_recaudadora ?? "—"}</td>
                    <td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{t.fecha_cargo ?? "—"}</td>
                    <td>{t.numero_cuota && t.total_cuotas ? `${t.numero_cuota}/${t.total_cuotas}` : (t.numero_cuota ?? "—")}</td>
                    <td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td>
                  </tr>
                ))}
                {(tchTransacciones?.items ?? []).length === 0 ? <tr><td colSpan={7}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchTransacciones && tchTransacciones.pages > 1 ? (
            <div style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchTransPage <= 1} onClick={() => setTchTransPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchTransPage} / {tchTransacciones.pages} ({tchTransacciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchTransPage >= tchTransacciones.pages} onClick={() => setTchTransPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : <main className="app-shell"><p className="muted-copy">Cargando...</p></main>
  ) : null;

  const content = detailLoading ? (
    <main className="app-shell">
      <p className="muted-copy">Cargando ficha...</p>
    </main>
  ) : (
    (clientDetailView ??
    planDetailView ??
    subscriptionDetailView ??
    chargeDetailView ??
    paymentDetailView ??
    providerRecordDetailView ??
    recoveryView ??
    billingView ??
    providerDetail ??
    tchContent ??
    (channel ? (
      channelLoading || !channelData ? (
        <main className="app-shell">
          <p className="muted-copy">Cargando mini dashboard...</p>
        </main>
      ) : (
        <ChannelDashboardView
          data={channelData}
          mode={mode}
          year={year}
          syncing={syncing}
          refreshing={channelRefreshing}
          onMode={setMode}
          onYear={setYear}
          onOpenResource={openChannelResource}
          onReport={setReportScope}
          onSync={syncChannel}
          syncUnavailable={!isChannelEnabled(channelData.source === "virtualpos" ? "virtualpos1" : channelData.source)}
        />
      )
    ) : (
      generalView === "report" ? <AutomaticReport /> : globalDashboard
    )))
  );

  if (session === undefined) return <main className="app-shell"><p className="muted-copy">Verificando sesión...</p></main>;
  if (session === null) return <LoginScreen onLogin={setSession} />;

  return (
    <div className="app-layout">
      <button
        ref={burgerRef}
        className="burger-btn"
        aria-label="Abrir menú"
        aria-expanded={sidebarOpen}
        aria-controls="app-sidebar"
        onClick={() => setSidebarOpen(true)}
      >
        <span /><span /><span />
      </button>
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={closeSidebar} />
      )}
      <Sidebar
        activeSection={activeSection}
        channel={channel}
        tchView={tchView}
        openProvider={openProvider}
        theme={theme}
        onDashboard={showDashboard}
        generalView={generalView}
        onGeneralClients={showGeneralClients}
        onGeneralSubscriptions={showGeneralSubscriptions}
        onAutoReport={showAutoReport}
        onChannel={showChannel}
        onSection={showSection}
        onToggle={(provider) =>
          setOpenProvider((open) => (open === provider ? null : provider))
        }
        onTheme={toggleTheme}
        onTch={showTch}
        permissions={session.user.permissions}
        onAdmin={showAdmin}
        adminOpen={adminOpen}
        adminTab={adminTab}
        onProfile={() => showProfile("summary")}
        onLogout={logout}
        open={sidebarOpen}
        onClose={closeSidebar}
        recoveryOpen={recoveryOpen}
        onRecovery={showRecovery}
        billingOpen={billingOpen}
        onBilling={showBillingChanges}
        profileOpen={profileView !== null}
        health={channelHealth}
      />
      {adminOpen ? (
        <AdminPanel permissions={session.user.permissions} isAdmin={session.user.roles.some((role) => role.name === "admin")} tab={adminTab} />
      ) : profileView ? (
        <ProfilePanel
          user={session.user}
          editing={profileView === "edit"}
          onUpdated={(updated) => setSession((prev) => prev ? { ...prev, user: updated } : prev)}
          onClose={() => showDashboard()}
          onEdit={() => showProfile("edit")}
          onCancelEdit={() => showProfile("summary")}
        />
      ) : (
        <ContentErrorBoundary>
          <Suspense fallback={<main className="app-shell"><p className="muted-copy">Cargando vista...</p></main>}>{content}</Suspense>
        </ContentErrorBoundary>
      )}
      {clientEditDialog}
      {creatingPlan ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog edit-dialog-wide"
            aria-modal="true"
            aria-label="Crear plan VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSPlan}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / PLANES</p>
                <h3>Nuevo plan</h3>
              </div>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. El plan se creará en VirtualPOS y en la base de datos local.
            </p>
            <div className="vp-account-selector">
              <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
              <div className="vp-account-selector-buttons">
                <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos1")}>
                  Cuenta 1
                </button>
  {vp2Enabled && (              <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos2")}>
                  Cuenta 2
                </button>)}
              </div>
            </div>
            <div className="edit-form-grid">
              {virtualPosPlanCreateFields.map((field) => {
                const hasError = Boolean(planFieldErrors[field.name]);
                const defaultVal = planDefaultValues[field.name] ?? "";
                return (
                  <label className={hasError ? "field-error" : ""} key={field.name}>
                    {field.label}{field.required ? <span className="field-required" aria-hidden="true"> *</span> : null}
                    {field.options ? (
                      <select name={field.name} defaultValue={defaultVal} aria-invalid={hasError} aria-required={field.required}>
                        {!field.required && <option value="">Sin especificar</option>}
                        {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : (
                      <input
                        name={field.name}
                        type={field.type ?? "text"}
                        defaultValue={defaultVal}
                        aria-invalid={hasError}
                        aria-required={field.required}
                        placeholder={field.name === "amount" ? "Ej: 9990" : field.name === "num_charges" ? "0 = ilimitado" : undefined}
                      />
                    )}
                    {hasError ? <span className="field-error-message">{planFieldErrors[field.name]}</span> : null}
                  </label>
                );
              })}
            </div>
            {planFormError ? <p className="error-message form-error">{planFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingPlan}>
                {savingPlan ? "Creando..." : "Crear plan"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingPlan(false)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {creatingSubscription ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog edit-dialog-wide"
            aria-modal="true"
            aria-label="Crear suscripción VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSSubscription}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / SUSCRIPCIONES</p>
                <h3>Nueva suscripción</h3>
              </div>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. El RUT será validado. Las URLs de retorno y callback se codificarán en Base64 automáticamente.
            </p>
            <div className="vp-account-selector">
              <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
              <div className="vp-account-selector-buttons">
                <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos1")}>
                  Cuenta 1
                </button>
  {vp2Enabled && (              <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos2")}>
                  Cuenta 2
                </button>)}
              </div>
            </div>
            <div className="edit-form-grid">
              {virtualPosSubscriptionCreateFields.map((field) => {
                const hasError = Boolean(subscriptionFieldErrors[field.name]);
                const isRequired = subscriptionRequiredFields.has(field.name);
                return (
                  <label className={hasError ? "field-error" : ""} key={field.name}>
                    {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                    {field.options ? (
                      <select name={field.name} aria-invalid={hasError} aria-required={isRequired}>
                        <option value="">Sin especificar</option>
                        {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : (
                      <input
                        name={field.name}
                        type={field.type ?? "text"}
                        aria-invalid={hasError}
                        aria-required={isRequired}
                        placeholder={
                          field.name === "social_id" ? "Ej: 12345678-9"
                          : field.name === "plan_id" ? "ID exacto del plan en VirtualPOS"
                          : field.name === "phone_number" ? "Ej: 56912345678"
                          : undefined
                        }
                      />
                    )}
                    {hasError ? <span className="field-error-message">{subscriptionFieldErrors[field.name]}</span> : null}
                  </label>
                );
              })}
            </div>
            {subscriptionFormError ? <p className="error-message form-error">{subscriptionFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingSubscription}>
                {savingSubscription ? "Creando..." : "Crear suscripción"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingSubscription(false)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {subscriptionCancelDialog}
      {cancelingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar cargo VirtualPOS">
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Cancelar cargo</h3>
              </div>
              <span>{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará DELETE <code>/v3/charge/{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</code> a VirtualPOS.
              Solo cargos en estado <strong>pendiente</strong> pueden cancelarse. Esta acción no se puede deshacer.
            </p>
            {cancelChargeError ? <p className="error-message form-error">{cancelChargeError}</p> : null}
            <div className="edit-dialog-actions">
              <button
                type="button"
                className="cancel-subscription-button"
                disabled={savingCancelCharge}
                onClick={() => void cancelVirtualPOSCharge()}
              >
                {savingCancelCharge ? "Cancelando..." : "Confirmar cancelación"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCancelingCharge(null)}>
                Volver
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {retryingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Reintentar cargo VirtualPOS">
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Reintentar cargo</h3>
              </div>
              <span>{text(retryingCharge.payload.id, retryingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará GET <code>/v3/charge/{text(retryingCharge.payload.id, retryingCharge.external_id)}/retry</code> a VirtualPOS.
              Solo cargos en estado <strong>rechazado</strong> pueden reintentarse (máximo una vez diaria durante tres días consecutivos).
            </p>
            {retryChargeError ? <p className="error-message form-error">{retryChargeError}</p> : null}
            <div className="edit-dialog-actions">
              <button
                type="button"
                className="retry-charge-button"
                disabled={savingRetryCharge}
                onClick={() => void retryVirtualPOSCharge()}
              >
                {savingRetryCharge ? "Reintentando..." : "Confirmar reintento"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setRetryingCharge(null)}>
                Volver
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {creatingCharge ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog"
            aria-modal="true"
            aria-label="Crear cargo VirtualPOS"
            noValidate
            onSubmit={createVirtualPOSCharge}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">VIRTUALPOS / CARGO</p>
                <h3>Nuevo cargo</h3>
              </div>
              <span className="edit-dialog-subtitle">Sub: {text(creatingCharge.payload.id, creatingCharge.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Los campos marcados con * son obligatorios. La fecha del cargo no puede ser pasada.
            </p>
            <div className="edit-form-grid">
              <label className={chargeFieldErrors.charge_date ? "field-error" : ""}>
                Fecha del cargo<span className="field-required" aria-hidden="true"> *</span>
                <input
                  name="charge_date"
                  type="date"
                  aria-required="true"
                  aria-invalid={Boolean(chargeFieldErrors.charge_date)}
                  min={new Date().toISOString().split("T")[0]}
                />
                {chargeFieldErrors.charge_date ? <span className="field-error-message">{chargeFieldErrors.charge_date}</span> : null}
              </label>
              <label className={chargeFieldErrors.amount ? "field-error" : ""}>
                Monto<span className="field-required" aria-hidden="true"> *</span>
                <input
                  name="amount"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="Ej: 9990"
                  aria-required="true"
                  aria-invalid={Boolean(chargeFieldErrors.amount)}
                />
                {chargeFieldErrors.amount ? <span className="field-error-message">{chargeFieldErrors.amount}</span> : null}
              </label>
              <label>
                Descripción
                <input name="description" type="text" placeholder="Ej: Cuota agosto 2026" />
              </label>
              <label>
                Código interno
                <input name="internal_code" type="text" placeholder="Ej: AGO2026" />
              </label>
            </div>
            {chargeFormError ? <p className="error-message form-error">{chargeFormError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingCharge}>
                {savingCharge ? "Creando..." : "Crear cargo"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setCreatingCharge(null)}>
                Cancelar
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {managingTokuSub ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <form
            className="edit-dialog"
            aria-modal="true"
            aria-label="Gestionar estado suscripción Toku"
            noValidate
            onSubmit={changeTokuSubscriptionStatus}
          >
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">TOKU / SUSCRIPCIÓN</p>
                <h3>Cambiar estado</h3>
              </div>
              <span>{text(managingTokuSub.payload.id, managingTokuSub.external_id)}</span>
            </div>
            <p className="edit-dialog-note">
              Se enviará POST <code>/subscriptions/{text(managingTokuSub.payload.id, managingTokuSub.external_id)}/status</code> a Toku.
              Estado actual: <strong>{text(managingTokuSub.payload.status)}</strong>
            </p>
            <div className="edit-form-grid">
              <label>
                Nuevo estado<span className="field-required" aria-hidden="true"> *</span>
                <select name="status">
                  <option value="">Seleccionar...</option>
                  <option value="ACTIVE">ACTIVE — Activar</option>
                  <option value="PAUSED">PAUSED — Pausar</option>
                  <option value="CANCELLED">CANCELLED — Cancelar</option>
                </select>
              </label>
            </div>
            {tokuSubStatusError ? <p className="error-message form-error">{tokuSubStatusError}</p> : null}
            <div className="edit-dialog-actions">
              <button type="submit" className="save-button" disabled={savingTokuSubStatus}>
                {savingTokuSubStatus ? "Aplicando..." : "Confirmar cambio"}
              </button>
              <button type="button" className="cancel-button" onClick={() => setManagingTokuSub(null)}>
                Volver
              </button>
            </div>
          </form>
        </div>
      ) : null}
      {providerEditDialog}
      {providerDeleteDialog}
      {reportScope ? <ReportDialog scope={reportScope} onClose={() => setReportScope(null)} /> : null}
    </div>
  );
}

export default AppCore;
