import { Component, lazy, Suspense, useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import { getCached } from "./apiCache";
import { setCsrfToken, getJson, postJson } from "./api";
import { useChannelHealth } from "./hooks/useChannelHealth";
import { Sidebar } from "./components/Sidebar";
import { canOpenBilling, canOpenCharges, canOpenMembers, canOpenRecovery, canOpenSubscriptions, providerGroups, resourcePermission } from "./navigation";
import type { ProviderSection } from "./routes";
import "./App.css";
import "./Staging.css";
import { legacyRedirectPath, parseRoute, routePath, tchPermissionSegment, type AppRoute, type ProviderSource, type TchRouteView } from "./routes";
// Feature modules
import type { ChannelDashboard, AuthSession } from "./features/shared/types";
import { stagingFilters } from "./features/virtualpos/constants";
import { LoginScreen } from "./features/auth/LoginScreen";
import { ProfilePanel } from "./features/auth/ProfilePanel";
import { DirectCancelContext } from "./features/cancellations/directCancel";
import { PERM_CANCELLATION_VIEW } from "./features/cancellations/types";
import { useEnabledChannels } from "./features/shared/environment";
import { ReportDialog } from "./features/dashboard/ReportDialog";
import { useEtl } from "./features/dashboard/useEtl";
import { useGeneralDashboard } from "./features/dashboard/useGeneralDashboard";
import { useChannelDashboard } from "./features/dashboard/useChannelDashboard";
import { ClientDetailView } from "./features/virtualpos/ClientDetailView";
import { PlanDetailView } from "./features/virtualpos/PlanDetailView";
import { SubscriptionDetailView } from "./features/virtualpos/SubscriptionDetailView";
import { ChargeDetailView } from "./features/virtualpos/ChargeDetailView";
import { PaymentDetailView } from "./features/virtualpos/PaymentDetailView";
import { ProviderRecordDetailView } from "./features/provider/ProviderRecordDetailView";
import { useStagingRecords } from "./features/provider/useStagingRecords";
import { StagingRecordsList } from "./features/provider/StagingRecordsList";
import { useRecordDetails } from "./features/shared/useRecordDetails";
import { useVirtualPosWrites } from "./features/virtualpos/useVirtualPosWrites";
import { VirtualPosWriteDialogs } from "./features/virtualpos/VirtualPosWriteDialogs";
import { useProviderWrites } from "./features/provider/useProviderWrites";
import { ProviderWriteDialogs } from "./features/provider/ProviderWriteDialogs";
import { useTch } from "./features/tch/useTch";
import { provisionalTchSubscriptionDetail } from "./features/tch/tchAdapter";

// VIZ-10: vistas pesadas (y recharts) en chunks aparte, cargadas bajo demanda.
const AutomaticReport = lazy(() => import("./AutomaticReport").then((m) => ({ default: m.AutomaticReport })));
const GeneralRecoveryPage = lazy(() => import("./features/recovery/GeneralRecoveryPage").then((m) => ({ default: m.GeneralRecoveryPage })));
const BillingInbox = lazy(() => import("./features/billing/BillingInbox").then((m) => ({ default: m.BillingInbox })));
const CancellationsInbox = lazy(() => import("./features/cancellations/CancellationsInbox").then((m) => ({ default: m.CancellationsInbox })));
const AdminPanel = lazy(() => import("./features/admin/AdminPanel").then((m) => ({ default: m.AdminPanel })));
const ChannelDashboardView = lazy(() => import("./features/dashboard/ChannelDashboardView").then((m) => ({ default: m.ChannelDashboardView })));
const GeneralDashboardView = lazy(() => import("./features/dashboard/GeneralDashboardView").then((m) => ({ default: m.GeneralDashboardView })));
const SummaryView = lazy(() => import("./features/summary/SummaryView").then((m) => ({ default: m.SummaryView })));
const TchContent = lazy(() => import("./features/tch/TchContent").then((m) => ({ default: m.TchContent })));
// Vistas unificadas de Cartera (UX-08, UX-09): paginadas en el servidor y cargadas bajo demanda.
const UnifiedChargesView = lazy(() => import("./features/charges/UnifiedChargesView").then((m) => ({ default: m.UnifiedChargesView })));


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
  const [adminTab, setAdminTab] = useState<"users" | "sync">("users");
  const [activeSection, setActiveSection] = useState<ProviderSection | null>(
    null,
  );
  // «Detalle por canal» (transitorio) del menú: se abre solo al entrar a una pantalla de canal.
  const [detailOpen, setDetailOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const {
    channel, setChannel, channelData, setChannelData, channelLoading, setChannelLoading, channelRefreshing, channelError, setChannelError, reloadChannel, syncing, mode, setMode, year, setYear, syncChannel,
  } = useChannelDashboard(session, setError);
  const stagingList = useStagingRecords({ session, activeSection, setError, setLoading });
  const {
    records, setRecords, recordsOffset, setRecordsOffset, filterField, setFilterField, filterQuery, setFilterQuery, setVpColumnFilters, sortColumn, setSortColumn, sortDirection, setSortDirection, vpPlatform, setVpPlatform,
  } = stagingList;
  const {
    clientDetail, setClientDetail, planDetail, subscriptionDetail, setSubscriptionDetail, chargeDetail, setChargeDetail, paymentDetail, providerRecordDetail, detailLoading, clearDetails, openVirtualPosClient, openVirtualPosPlan, openVirtualPosSubscription, openVirtualPosCharge, openVirtualPosPayment, openProviderRecord, openRecord,
  } = useRecordDetails({ navigate, setError });
  const vpWrites = useVirtualPosWrites({
    records, setRecords,
    details: { clientDetail, setClientDetail, subscriptionDetail, setSubscriptionDetail, chargeDetail, setChargeDetail },
  });
  const {
    setEditingClient, setCreatingClient, setClientVpPlatform, clientSaveNotice, setCreatingPlan, setPlanVpPlatform, setPlanFormError, setPlanFieldErrors, planSaveNotice, setPlanSaveNotice, setCreatingSubscription, setSubVpPlatform, setSubscriptionFormError, setSubscriptionFieldErrors, subscriptionSaveNotice, setSubscriptionSaveNotice, setCancelingSubscription, setCancelSubscriptionError, setCreatingCharge, setChargeFormError, setChargeFieldErrors, chargeSaveNotice, setChargeSaveNotice, setCancelingCharge, setCancelChargeError, setRetryingCharge, setRetryChargeError,
  } = vpWrites;
  const providerWrites = useProviderWrites({ setRecords });
  const {
    setEditingProviderRecord, setProviderEditError, setDeletingRecord, setProviderDeleteError, setManagingTokuSub, setTokuSubStatusError,
  } = providerWrites;
  const [reportScope, setReportScope] = useState<string | null>(null);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [billingOpen, setBillingOpen] = useState(false);
  const [cancellationsOpen, setCancellationsOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("crm-theme") as "light" | "dark") ?? "light";
  });
  const { isEnabled: isChannelEnabled } = useEnabledChannels();
  const vp2Enabled = isChannelEnabled("virtualpos2");
  useEffect(() => {
    if (vp2Enabled) return;
    setClientVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setPlanVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setSubVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
    setVpPlatform((p) => (p === "virtualpos2" ? "virtualpos1" : p));
  }, [vp2Enabled]);
  const tch = useTch(session);
  const { tchView, setTchView, setTchSubscriptionDetail, setTchTransactionDetail, setTchClientDetail } = tch;
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const burgerRef = useRef<HTMLButtonElement>(null);
  const channelHealth = useChannelHealth(Boolean(session));
  const closeSidebar = () => {
    setSidebarOpen(false);
    burgerRef.current?.focus();
  };
  const [profileView, setProfileView] = useState<"summary" | "edit" | null>(null);
  const etl = useEtl(isChannelEnabled);
  const general = useGeneralDashboard({
    session, channel, activeSection, tchView, adminOpen, profileView,
    lastEtlFinishedAt: etl.lastEtlRun?.finished_at, setError, setLoading,
  });
  const {
    generalView, setGeneralView, setGeneralClientQuery, generalClientFilter, setGeneralClientFilter, generalClientOffset, setGeneralClientOffset, setGeneralClientDetail, setGeneralSubscriptionQuery, generalSubscriptionFilter, setGeneralSubscriptionFilter, generalSubscriptionOffset, setGeneralSubscriptionOffset,
  } = general;

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
    if (route.kind === "central") {
      if (route.view === "charges") return canOpenCharges(can);
      if (route.view === "subscriptions") return canOpenSubscriptions(can);
      if (route.view === "clients") return canOpenMembers(can);
      return can("dashboard.view");
    }
    if (route.kind === "resource" || route.kind === "record") return can(resourcePermission(route.source, route.resource));
    if (route.kind === "channel") {
      return providerGroups.find((group) => group.sections[0].source === route.source)?.sections.some((section) => can(resourcePermission(section.source, section.resource))) ?? false;
    }
    if (route.kind === "recovery") return canOpenRecovery(can);
    if (route.kind === "billingChanges") return canOpenBilling(can);
    if (route.kind === "cancellations") return can(PERM_CANCELLATION_VIEW);
    if (route.kind === "tchSubscription") return can("tch.suscripciones.view");
    if (route.kind === "tch") return route.view === "summary"
      ? can("tch.dashboard.view")
      : can(`tch.${tchPermissionSegment(route.view)}.view`);
    if (route.kind === "admin") return route.view === "users"
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

  function showAdmin(view: "users" | "sync", updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(true);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
    setAdminTab(view);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "admin", view });
  }

  function showDashboard(updateUrl = true) {
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
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

  /** Vista anterior del dashboard general (TRANSITORIA, fuera del menú; se retira con UX-15). */
  function showClassicSummary(updateUrl = true) {
    showDashboard(false);
    setGeneralView("classic");
    if (updateUrl) navigate({ kind: "central", view: "classic" });
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

  function showGeneralCharges(updateUrl = true) {
    showDashboard(false);
    setGeneralView("charges");
    if (updateUrl) navigate({ kind: "central", view: "charges" });
  }

  /** Abre una ruta interna (p. ej. la ficha por canal desde una vista unificada) como si fuera un enlace. */
  function openPath(path: string) {
    window.history.pushState({}, "", path);
    setRouteLocation(path);
  }

  function showAutoReport(updateUrl = true) {
    showDashboard(false);
    setGeneralView("report");
    if (updateUrl) navigate({ kind: "central", view: "report" });
  }

  function showTch(view: TchRouteView, updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
    setError(null);
    setTchSubscriptionDetail(null);
    setTchTransactionDetail(null);
    setTchClientDetail(null);
    setTchView(view);
    setDetailOpen(true);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "tch", view });
  }

  function showTchSubscription(fileNumber: number, updateUrl = true) {
    if (updateUrl) {
      navigate({ kind: "tchSubscription", fileNumber });
      return;
    }
    showTch("subscriptions", false);
    setTchSubscriptionDetail(provisionalTchSubscriptionDetail(fileNumber));
    setTchView("subscription-detail");
  }


  function showChannel(source: ProviderSource, updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setActiveSection(null);
    setTchView(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
    setAdminOpen(false);
    const cached = getCached<ChannelDashboard>(`dashboard:${source}`, 5 * 60 * 1000);
    setChannelData(cached);
    setChannelLoading(!cached);
    setChannelError(null);
    setError(null);
    setYear(null);
    setChannel(source);
    setDetailOpen(true);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "channel", source });
  }
  function showSection(section: ProviderSection, updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
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
    setDetailOpen(true);
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
    setCancellationsOpen(false);
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
    setCancellationsOpen(false);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "billingChanges" });
  }

  function showCancellations(updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setAdminOpen(false);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(true);
    setProfileView(null);
    if (updateUrl) navigate({ kind: "cancellations" });
  }

  function showProfile(view: "summary" | "edit", updateUrl = true) {
    clearDetails();
    setGeneralView("summary");
    setChannel(null);
    setActiveSection(null);
    setTchView(null);
    setRecoveryOpen(false);
    setBillingOpen(false);
    setCancellationsOpen(false);
    setAdminOpen(false);
    setProfileView(view);
    if (updateUrl) navigate({ kind: "profile", view });
  }

  useEffect(() => {
    const onPopState = () => setRouteLocation(window.location.pathname + window.location.search);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

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
      else if (route.view === "classic") showClassicSummary(false);
      else if (route.view === "charges") showGeneralCharges(false);
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
      // UX-12: /virtualpos/recuperador-socios -> /general/recuperador (reemplaza el historial).
      if (legacyRedirectPath(location.pathname)) navigate(route, true);
    } else if (route.kind === "billingChanges") {
      showBillingChanges(false);
      if (legacyRedirectPath(location.pathname)) navigate(route, true);
    } else if (route.kind === "cancellations") {
      showCancellations(false);
    } else if (route.kind === "tch") {
      showTch(route.view, false);
    } else if (route.kind === "tchSubscription") {
      showTchSubscription(route.fileNumber, false);
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
    <ClientDetailView
      detail={clientDetail}
      showResourceList={showResourceList}
      openVirtualPosSubscription={openVirtualPosSubscription}
      openVirtualPosCharge={openVirtualPosCharge}
      openVirtualPosPayment={openVirtualPosPayment}
      onEdit={setEditingClient}
      onCancelSubscription={(record) => { setCancelSubscriptionError(null); setCancelingSubscription(record); }}
    />
  ) : null;
  const planDetailView = planDetail ? (
    <PlanDetailView
      detail={planDetail}
      showResourceList={showResourceList}
      openVirtualPosSubscription={openVirtualPosSubscription}
    />
  ) : null;
  const subscriptionDetailView = subscriptionDetail ? (
    <SubscriptionDetailView
      detail={subscriptionDetail}
      showResourceList={showResourceList}
      openVirtualPosPlan={openVirtualPosPlan}
      openVirtualPosCharge={openVirtualPosCharge}
      openVirtualPosPayment={openVirtualPosPayment}
      onCancelSubscription={setCancelingSubscription}
      onNewCharge={(record) => { setChargeFormError(null); setChargeFieldErrors({}); setCreatingCharge(record); }}
      onCancelCharge={(record) => { setCancelChargeError(null); setCancelingCharge(record); }}
      onRetryCharge={(record) => { setRetryChargeError(null); setRetryingCharge(record); }}
      can={can}
      chargeSaveNotice={chargeSaveNotice}
    />
  ) : null;
  const chargeDetailView = chargeDetail ? (
    <ChargeDetailView
      detail={chargeDetail}
      showResourceList={showResourceList}
      openVirtualPosClient={openVirtualPosClient}
      openVirtualPosSubscription={openVirtualPosSubscription}
      openVirtualPosPayment={openVirtualPosPayment}
      onCancelCharge={(record) => { setCancelChargeError(null); setCancelingCharge(record); }}
      onRetryCharge={(record) => { setRetryChargeError(null); setRetryingCharge(record); }}
      can={can}
    />
  ) : null;
  const paymentDetailView = paymentDetail ? (
    <PaymentDetailView
      detail={paymentDetail}
      showResourceList={showResourceList}
      openVirtualPosClient={openVirtualPosClient}
      openVirtualPosSubscription={openVirtualPosSubscription}
      openVirtualPosCharge={openVirtualPosCharge}
      onDelete={(record) => setDeletingRecord({ record, source: "virtualpos", resourceType: "payment" })}
    />
  ) : null;
  const providerRecordDetailView = providerRecordDetail ? (
    <ProviderRecordDetailView
      detail={providerRecordDetail}
      showResourceList={showResourceList}
      openProviderRecord={openProviderRecord}
      onEditRecord={(record, source, resourceType) => { setProviderEditError(null); setEditingProviderRecord({ record, source, resourceType }); }}
      onManageTokuSubscription={(record) => { setTokuSubStatusError(null); setManagingTokuSub(record); }}
      onDeleteRecord={(record, source, resourceType) => { setProviderDeleteError(null); setDeletingRecord({ record, source, resourceType }); }}
    />
  ) : null;
  const recoveryView = recoveryOpen ? <GeneralRecoveryPage can={can} /> : null;
  const billingView = billingOpen ? <BillingInbox can={can} currentUserId={session?.user.id} isAdmin={session?.user.roles.some((role) => role.name === "admin") ?? false} /> : null;

  const cancellationsView = cancellationsOpen ? (
    <CancellationsInbox can={can} currentUserId={session?.user.id} isAdmin={session?.user.roles.some((role) => role.name === "admin") ?? false} />
  ) : null;

  const providerDetail = activeSection ? (
    <StagingRecordsList
      activeSection={activeSection}
      list={stagingList}
      loading={loading}
      error={error}
      vp2Enabled={vp2Enabled}
      can={can}
      notices={{ client: clientSaveNotice, plan: planSaveNotice, subscription: subscriptionSaveNotice, charge: chargeSaveNotice }}
      showChannel={showChannel}
      openVirtualPosClient={openVirtualPosClient}
      openVirtualPosPlan={openVirtualPosPlan}
      openVirtualPosSubscription={openVirtualPosSubscription}
      openVirtualPosPayment={openVirtualPosPayment}
      openProviderRecord={openProviderRecord}
      onNewClient={() => setCreatingClient(true)}
      onNewPlan={() => { setPlanFormError(null); setPlanFieldErrors({}); setPlanSaveNotice(null); setCreatingPlan(true); }}
      onNewSubscription={() => { setSubscriptionFormError(null); setSubscriptionFieldErrors({}); setSubscriptionSaveNotice(null); setCreatingSubscription(true); }}
      onEditClient={setEditingClient}
      onCancelSubscription={setCancelingSubscription}
      onNewCharge={(record) => { setChargeFormError(null); setChargeFieldErrors({}); setChargeSaveNotice(null); setCreatingCharge(record); }}
      onCancelCharge={(record) => { setCancelChargeError(null); setCancelingCharge(record); }}
      onRetryCharge={(record) => { setRetryChargeError(null); setRetryingCharge(record); }}
      onEditRecord={(record, source, resourceType) => setEditingProviderRecord({ record, source, resourceType })}
      onDeleteRecord={(record, source, resourceType) => setDeletingRecord({ record, source, resourceType })}
    />
  ) : null;

  const globalDashboard = <GeneralDashboardView general={general} etl={etl} error={error} setError={setError} onReport={setReportScope} can={can} />;

  const tchContent = tch.tchView ? <TchContent tch={tch} showTch={showTch} showTchSubscription={showTchSubscription} onReport={setReportScope} can={can} /> : null;

  const summaryRoute = parseRoute(routeLocation.split("?")[0]);
  const onSummaryRoute = summaryRoute?.kind === "central" && summaryRoute.view === "summary";

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
    cancellationsView ??
    providerDetail ??
    tchContent ??
    (channel ? (
      channelError && !channelData ? (
        <main className="app-shell">
          <div className="error-message" role="alert">
            <p>{channelError}</p>
            <button type="button" className="secondary-button" onClick={reloadChannel}>Reintentar</button>
          </div>
        </main>
      ) : channelLoading || !channelData ? (
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
      generalView === "report" ? <AutomaticReport /> : generalView === "charges" ? <UnifiedChargesView can={can} onOpenPath={openPath} /> : generalView === "summary" ? (
        // El estado inicial es «summary» aunque el enlace profundo apunte a otra vista: solo se monta el Resumen
        // unificado si la URL es de verdad la suya (así un enlace a otra pantalla no dispara su petición).
        onSummaryRoute ? <SummaryView /> : <main className="app-shell"><p className="muted-copy">Cargando vista...</p></main>
      ) : globalDashboard
    )))
  );

  if (session === undefined) return <main className="app-shell"><p className="muted-copy">Verificando sesión...</p></main>;
  if (session === null) return <LoginScreen onLogin={setSession} />;

  // Botones directos de baja: solo admin (el backend lo exige); el resto pide la baja en «Bajas».
  const directCancelAccess = { isAdmin: session.user.roles.some((role) => role.name === "admin"), canOpenCancellations: can(PERM_CANCELLATION_VIEW) };

  return (
    <DirectCancelContext.Provider value={directCancelAccess}>
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
      <Sidebar
        activeSection={activeSection}
        channel={channel}
        tchView={tchView}
        detailOpen={detailOpen}
        onToggleDetail={() => setDetailOpen((open) => !open)}
        theme={theme}
        onDashboard={showDashboard}
        generalView={generalView}
        onGeneralClients={showGeneralClients}
        onGeneralSubscriptions={showGeneralSubscriptions}
        onGeneralCharges={showGeneralCharges}
        onAutoReport={showAutoReport}
        onChannel={showChannel}
        onSection={showSection}
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
        cancellationsOpen={cancellationsOpen}
        onCancellations={showCancellations}
        profileOpen={profileView !== null}
        health={channelHealth}
      />
      {adminOpen ? (
        <Suspense fallback={<main className="app-shell"><p className="muted-copy">Cargando vista...</p></main>}>
          <AdminPanel permissions={session.user.permissions} isAdmin={session.user.roles.some((role) => role.name === "admin")} tab={adminTab} />
        </Suspense>
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
      <VirtualPosWriteDialogs writes={vpWrites} vp2Enabled={vp2Enabled} />
      <ProviderWriteDialogs writes={providerWrites} />
      {reportScope ? <ReportDialog scope={reportScope} onClose={() => setReportScope(null)} /> : null}
    </div>
    </DirectCancelContext.Provider>
  );
}

export default AppCore;
