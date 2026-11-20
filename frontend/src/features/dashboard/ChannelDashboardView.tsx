import { memo, useDeferredValue, useMemo, useState, type ReactNode } from "react";
import { getJson } from "../../api";
import type { MonthlyStatusEntry } from "../shared/monthly";
import { OperationalAlerts } from "./OperationalAlerts";
import { providerGroups } from "../../navigation";
import {
  virtualPosMetrics, tokuMetrics, paykuMetrics,
} from "../shared/constants";
import { title, defaultYear } from "../shared/utils";
import type { ChannelDashboard } from "../shared/types";
import { adaptAlertDetailItems, adaptAlerts, type AlertDetailItemWire } from "./alertAdapter";
import { Metric } from "./Metric";
import { ChannelHero } from "./ChannelHero";
import { ChannelKpiStrip } from "../../components/ChannelKpiStrip";
import { ChannelChart, type ChannelChartKind } from "../../components/ChannelChart";
import { RankingChart } from "../../components/RankingChart";
import { normalizeKpis, PAYKU_COVERAGE_NOTE, type Channel } from "../shared/kpis";
import {
  activationVsChurnChart, activeSubsLineChart, churnRateChart, coverageGapAnnotations, monthlyTrendChart, netGrowthChart,
  paymentMethodSnapshot, rankingByStatus, statusStackedChart, tokuCollectionsChart, type ChartProps,
} from "./channelCharts";
import { StatusBars } from "./StatusBars";
import { statusBarResources } from "./statusBarRows";
import { PaykuWalletWithdraw } from "../payku/PaykuWalletWithdraw";

const PAID_KW = ["pagad", "aceptad", "accepted", "paid", "success", "cobrad", "aprobad"];
const CHANNEL_NAMES: Record<string, string> = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku" };

function ChannelDashboardViewImpl({
  data,
  mode,
  year,
  syncing,
  refreshing,
  onMode,
  onYear,
  onOpenResource,
  onReport,
  onSync,
  syncUnavailable = false,
  canWithdrawWallet = false,
}: {
  data: ChannelDashboard;
  mode: "count" | "amount";
  year: number | null;
  syncing: boolean;
  refreshing?: boolean;
  onMode: (mode: "count" | "amount") => void;
  onYear: (year: number) => void;
  onOpenResource: (resource: string) => void;
  onReport: (scope: string) => void;
  onSync: (source: string) => void;
  syncUnavailable?: boolean;
  /** CRM-14F: permiso `payku.wallet.withdraw` (solo admin). */
  canWithdrawWallet?: boolean;
}) {
  const metrics = data.source === "virtualpos" ? virtualPosMetrics : data.source === "toku" ? tokuMetrics : paykuMetrics;
  const activeYear = year ?? defaultYear(data.years) ?? null;
  const [churnSource, setChurnSource] = useState<"all" | "vp1" | "vp2">("all");
  const alerts = useMemo(() => adaptAlerts(data.alerts), [data.alerts]);
  // PERF-03f: cálculo del año activo una sola vez por cambio de datos, año o canal (no en cada render del padre).
  const { resolvedResources, resolvedAmounts } = useMemo(() => {
    const isPaid = (s: string) => PAID_KW.some((k) => s.toLowerCase().includes(k));
    const resources = { ...data.resources };
    const amounts = { ...data.resource_amounts };
    if (data.source.startsWith("virtualpos") && activeYear !== null) {
      const paidCharges = (data.charges_monthly ?? []).filter((e) => e.year === activeYear && e.status != null && isPaid(e.status));
      resources["charge"] = paidCharges.reduce((s, e) => s + e.count, 0);
      amounts["charge"] = paidCharges.reduce((s, e) => s + e.amount, 0);
      const paidPayments = (data.payments_monthly ?? []).filter((e) => e.year === activeYear && e.status != null && isPaid(e.status));
      resources["payment"] = paidPayments.reduce((s, e) => s + e.count, 0);
      amounts["payment"] = paidPayments.reduce((s, e) => s + e.amount, 0);
    }
    if (data.source === "toku" && activeYear !== null) {
      const paidInvoices = ((data.invoices_monthly as MonthlyStatusEntry[] | undefined) ?? []).filter((e) => e.year === activeYear && e.status?.toUpperCase() === "PAID");
      resources["invoice"] = paidInvoices.reduce((s, e) => s + e.count, 0);
      amounts["invoice"] = paidInvoices.reduce((s, e) => s + e.amount, 0);
      const successfulTransactions = ((data.transactions_monthly as MonthlyStatusEntry[] | undefined) ?? []).filter((e) => e.year === activeYear && e.status?.toUpperCase() === "SUCCESS");
      resources["transaction"] = successfulTransactions.reduce((s, e) => s + e.count, 0);
      amounts["transaction"] = successfulTransactions.reduce((s, e) => s + e.amount, 0);
    }
    return { resolvedResources: resources, resolvedAmounts: amounts };
  }, [data, activeYear]);
  // PERF-03 (INP): los controles de la cabecera muestran de inmediato `mode`, `year` y `churnSource`; los gráficos
  // se alimentan de copias diferidas, de modo que recharts se redibuja en un turno de baja prioridad.
  const dMode = useDeferredValue(mode);
  const dYear = useDeferredValue(year);
  const dChurnSource = useDeferredValue(churnSource);
  const chartsStale = dMode !== mode || dYear !== year || dChurnSource !== churnSource;
  const activityTitle = "Tendencia de cobros";
  const isToku = data.source === "toku";
  const isPayku = data.source === "payku";
  const chartYear = (rows: { year: number }[]) => (rows.some((e) => e.year === dYear) ? dYear : null);
  // Sistema único (VIZ-08): todos los gráficos del canal son ChannelChart con tooltip único, teclado y «Ver datos».
  const chart = (props: ChartProps, kind: ChannelChartKind, opts: { legend?: boolean; mode?: "count" | "amount" | "percent"; ariaLabel: string; annotations?: ReturnType<typeof coverageGapAnnotations> }) => (
    <ChannelChart series={props.series} data={props.rows} kind={kind} mode={opts.mode ?? dMode} year={chartYear(props.rows)} legend={opts.legend} ariaLabel={opts.ariaLabel} annotations={opts.annotations} showDataToggle />
  );
  const panel = (props: ChartProps, eyebrow: string, heading: string, body: ReactNode, wide = false) =>
    props.rows.length ? (
      <article className={`panel${wide ? " chart-panel-wide" : ""}`}>
        <div className="panel-heading"><div><p className="eyebrow">{eyebrow}</p><h3>{heading}</h3></div></div>
        {body}
      </article>
    ) : null;
  // PERF-03f: los modelos de gráfico se calculan por cambio de datos/modo (no en cada render), para que
  // `ChannelChart` (memo) reciba las mismas referencias y no vuelva a pintar recharts.
  // Un memo por gráfico con sus propias dependencias: al cambiar el modo no se recalcula (ni se repinta) lo que no lo usa.
  const virtualPos = data.source === "virtualpos";
  const activeSubs = useMemo(() => activeSubsLineChart(data.active_subs_monthly), [data.active_subs_monthly]);
  const activationsVsCancellations = useMemo(() => activationVsChurnChart(data.activation_monthly, data.churn_monthly, dMode), [data.activation_monthly, data.churn_monthly, dMode]);
  const netGrowth = useMemo(() => netGrowthChart(data.activation_monthly, data.churn_monthly, dMode), [data.activation_monthly, data.churn_monthly, dMode]);
  const churnRates = useMemo(() => {
    const series = virtualPos && dChurnSource !== "all"
      ? (dChurnSource === "vp1" ? data.churn_rate_monthly_vp1 : data.churn_rate_monthly_vp2) ?? []
      : data.churn_rate_monthly ?? [];
    return churnRateChart(series);
  }, [data.churn_rate_monthly, data.churn_rate_monthly_vp1, data.churn_rate_monthly_vp2, virtualPos, dChurnSource]);
  const rejectedRanking = useMemo(() => {
    const rejectedYear = (data.rejected_charges_monthly ?? []).some((e) => e.year === dYear) ? dYear : null;
    return rankingByStatus(data.rejected_charges_monthly, dMode, rejectedYear);
  }, [data.rejected_charges_monthly, dMode, dYear]);
  const gaps = useMemo(() => coverageGapAnnotations(data.coverage_gaps), [data.coverage_gaps]);
  const methodSnapshot = useMemo(() => paymentMethodSnapshot(data.statuses), [data.statuses]);
  const m = useMemo(() => ({
    tokuActivity: data.source === "toku" ? tokuCollectionsChart(data.activity, dMode) : null,
    paykuTx: data.source === "payku" ? statusStackedChart(data.transactions_monthly, dMode) : null,
    paykuFallback: data.source === "payku" ? monthlyTrendChart(data.activity, dMode, dMode === "amount" ? "Monto" : "Cobros") : null,
    charges: statusStackedChart(data.charges_monthly, dMode),
    payments: virtualPos ? statusStackedChart(data.payments_monthly, dMode) : null,
    invoices: statusStackedChart(data.invoices_monthly, dMode),
    tokuTransactions: data.source === "toku" ? statusStackedChart(data.transactions_monthly, dMode) : null,
  }), [data, dMode, virtualPos]);
  const kpis = useMemo(() => (data.kpis ? normalizeKpis(data.source as Channel, data.kpis, data.churn_window_label) : null), [data.kpis, data.source, data.churn_window_label]);
  const metricSections = providerGroups.find((group) => group.sections[0].source === data.source)?.sections ?? [];
  const isVirtualPos = data.source === "virtualpos";
  const channelName = CHANNEL_NAMES[data.source] ?? title(data.source);
  const unavailableReason = `${channelName} no está habilitado en este ambiente`;
  const reasonId = `sync-reason-${data.source}`;
  const emptyAction = syncUnavailable ? (
    <p className="empty-hint">{unavailableReason}</p>
  ) : (
    <div className="empty-action">
      <p className="empty-hint">Sincroniza el canal para ver datos.</p>
      <button className="sync-btn sync-btn-secondary" disabled={syncing} onClick={() => onSync(data.source)}>{syncing ? "Sincronizando…" : "Sincronizar ahora"}</button>
    </div>
  );
  const statusEmpty = statusBarResources(data.source, data.statuses, data.resources).length === 0;
  return (
    <main className="app-shell channel-dashboard-page">
      <ChannelHero
        source={data.source}
        years={data.years}
        lastSyncStatus={data.last_sync?.status ?? null}
        mode={mode}
        year={year}
        syncing={syncing}
        refreshing={refreshing}
        syncUnavailable={syncUnavailable}
        unavailableReason={unavailableReason}
        reasonId={reasonId}
        onMode={onMode}
        onYear={onYear}
        onSync={onSync}
        onReport={onReport}
      />
      <section className="channel-resources channel-resources-quick" aria-label="Explorar recursos">
        <div><p className="eyebrow">EXPLORAR</p><h3>Ir a un recurso</h3></div>
        <div>
          {metricSections.map((section) => (
            <button key={section.resource} onClick={() => onOpenResource(section.resource)}>
              {section.label}<span>{data.resources[section.resource] ?? 0}</span>
            </button>
          ))}
        </div>
      </section>
      <div className="dashboard-section-heading"><div><p className="eyebrow">OPERACIÓN DEL PERÍODO</p><h3>Indicadores clave</h3></div></div>
      <section className={`metrics provider-metrics${data.source === "payku" ? " payku-metrics" : ""}${data.source.startsWith("virtualpos") ? " vp-metrics" : ""}`} aria-label={`Métricas ${title(data.source)}`}>
        {metrics.map((metric) => (
          <Metric
            key={metric.resource}
            label={metric.label}
            value={resolvedResources[metric.resource] ?? 0}
            tone={metric.tone}
            amount={"amount" in metric && metric.amount ? (resolvedAmounts[metric.resource] ?? 0) : undefined}
            mode={mode}
          />
        ))}
      </section>
      {isPayku && canWithdrawWallet ? <PaykuWalletWithdraw /> : null}
      {data.kpis ? (
        <>
          <div className="dashboard-section-heading dashboard-section-heading-compact"><div><p className="eyebrow">CARTERA</p><h3>Salud de suscripciones</h3></div></div>
          <ChannelKpiStrip kpis={kpis} churnHistory={data.churn_rate_monthly} ariaLabel="KPIs de suscripciones" />
        </>
      ) : null}
      <section className={`channel-workspace${isVirtualPos ? " channel-workspace-status" : ""}`}>
        {isToku ? (
          <article className={`panel chart-panel${data.activity.length ? "" : " panel-compact"}`}>
            <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Cobros mensuales (transacciones)</h3></div></div>
            {data.activity.length ? chart(m.tokuActivity!, "bar", { ariaLabel: "Gráfico de cobros mensuales de Toku (transacciones)" }) : <div className="empty-state"><p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>{emptyAction}</div>}
          </article>
        ) : null}
        {isPayku ? (() => {
          const tx = m.paykuTx!;
          const fallback = m.paykuFallback!;
          const body = tx.rows.length
            ? chart(tx, "stacked", { legend: true, annotations: gaps, ariaLabel: "Gráfico de transacciones mensuales de Payku por estado" })
            : fallback.rows.length
              ? chart(fallback, "bar", { annotations: gaps, ariaLabel: "Gráfico de cobros mensuales de Payku" })
              : <div className="empty-state"><p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>{emptyAction}</div>;
          const noData = !tx.rows.length && !fallback.rows.length;
          return (
            <article className={`panel chart-panel${noData ? " panel-compact" : ""}`}>
              <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Transacciones mensuales</h3></div></div>
              {body}
              <p className="muted-copy">{PAYKU_COVERAGE_NOTE}.{gaps.length ? " Las bandas grises marcan meses sin cobros." : ""}</p>
            </article>
          );
        })() : null}
        <article className={`panel status-panel${statusEmpty ? " panel-compact" : ""}`}>
          <p className="eyebrow">ESTADOS</p><h3>Estados de la operación</h3>
          <StatusBars source={data.source} statuses={data.statuses} resources={data.resources} emptyAction={emptyAction} />
        </article>
      </section>
      <div className="dashboard-section-heading dashboard-section-heading-charts"><div><p className="eyebrow">ACTIVIDAD Y TENDENCIAS</p><h3>Lectura mensual</h3></div></div>
      <section className="extended-charts" aria-busy={chartsStale || undefined} data-stale={chartsStale || undefined}>
        {panel(activeSubs, "SUSCRIPCIONES", "Suscripciones activas acumuladas", chart(activeSubs, "line", { mode: "count", ariaLabel: "Gráfico de suscripciones activas acumuladas" }), isVirtualPos)}
        {(() => { const p = m.charges; return panel(p, "CARGOS", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de cargos mensuales por estado" }), isVirtualPos); })()}
        {rejectedRanking.some((i) => (i.value ?? 0) > 0) ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Rechazados por motivo</h3></div></div>
            <RankingChart items={rejectedRanking} mode={dMode} valueLabel={dMode === "amount" ? "Monto rechazado" : "Cargos rechazados"} showDataToggle ariaLabel="Ranking de cargos rechazados por motivo" />
          </article>
        ) : null}
        {isVirtualPos ? (() => { const p = m.payments!; return panel(p, "TRANSACCIONES", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de transacciones mensuales por estado" })); })() : null}
        {(() => { const p = m.invoices; return panel(p, "FACTURAS", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de facturas mensuales por estado" })); })()}
        {isToku ? (() => { const p = m.tokuTransactions!; return panel(p, "TRANSACCIONES", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de transacciones mensuales por estado" })); })() : null}
        {panel(activationsVsCancellations, "SUSCRIPCIONES", "Altas vs bajas", chart(activationsVsCancellations, "diverging", { legend: true, ariaLabel: "Gráfico de altas (arriba) y bajas (abajo) mensuales de suscripciones" }))}
        {isToku && methodSnapshot.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">MÉTODOS DE PAGO</p><h3>Por estado (foto actual)</h3></div></div>
            <StatusBars source="toku" statuses={methodSnapshot} resources={{}} />
            <p className="muted-copy">Estado a la fecha de la última sincronización; no es una serie mensual.</p>
          </article>
        ) : null}
        {data.activation_monthly?.length && netGrowth.rows.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
            {chart(netGrowth, "waterfall", { legend: true, ariaLabel: "Waterfall del crecimiento neto mensual (altas menos bajas)" })}
            <p className="muted-copy">Cada barra es altas menos bajas del mes, desde el acumulado del mes anterior del período.</p>
          </article>
        ) : null}
        {isVirtualPos && data.churn_rate_monthly?.length ? (
          <article className="panel">
            <div className="panel-heading panel-heading-wrap">
              <div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div>
              <div className="mode-switch" style={{ fontSize: "0.8rem" }}>
                <button className={churnSource === "all" ? "active" : ""} onClick={() => setChurnSource("all")}>Todas</button>
                <button className={churnSource === "vp1" ? "active" : ""} onClick={() => setChurnSource("vp1")}>VirtualPOS 1</button>
                <button className={churnSource === "vp2" ? "active" : ""} onClick={() => setChurnSource("vp2")}>VirtualPOS 2</button>
              </div>
            </div>
            {churnRates.rows.length ? chart(churnRates, "line", { mode: "percent", ariaLabel: "Gráfico del churn mensual en porcentaje" }) : <p className="empty-chart">Sin datos para el período.</p>}
            <p className="muted-copy">Bajas del mes ÷ socios al inicio del mes (misma definición en todos los canales).</p>
          </article>
        ) : null}
        {!isVirtualPos && data.churn_rate_monthly?.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
            {chart(churnRates, "line", { mode: "percent", ariaLabel: "Gráfico del churn mensual en porcentaje" })}
            <p className="muted-copy">Bajas del mes ÷ socios al inicio del mes (misma definición en todos los canales).</p>
          </article>
        ) : null}
      </section>
      <OperationalAlerts
        alerts={alerts}
        loadDetail={(alertId) => getJson<{ items: AlertDetailItemWire[] }>(`/api/v1/staging/dashboard/${data.source}/alerts/${alertId}`).then((response) => adaptAlertDetailItems(response.items))}
      />
    </main>
  );
}

/** PERF-03f: memo; el padre pasa manejadores estables, así escribir en un buscador de otra vista no la repinta. */
export const ChannelDashboardView = memo(ChannelDashboardViewImpl);

export type { MonthlyStatusEntry };
