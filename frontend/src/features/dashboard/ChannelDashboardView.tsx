import { Suspense, useState } from "react";
import { getJson } from "../../api";
import ChannelActivityChart from "../../ChannelActivityChart";
import {
  MonthlyStatusChart,
  MonthlySimpleChart,
  ActivacionCaidaChart,
  CrecimientoMensualChart,
  ChurnMensualChart,
  TransaccionesSuscripcionesChart,
  type MonthlyEntry,
  type MonthlyStatusEntry,
} from "../../MonthlyStatusChart";
import { OperationalAlerts } from "./OperationalAlerts";
import { providerGroups } from "../../navigation";
import {
  virtualPosMetrics, tokuMetrics, paykuMetrics,
  months, CHANNEL_COLORS,
} from "../shared/constants";
import { title, defaultYear, aggregateChurn } from "../shared/utils";
import type { AlertDetailItem, ChannelDashboard } from "../shared/types";
import { Metric } from "./Metric";
import { ChannelKpiStrip } from "../../components/ChannelKpiStrip";
import { ChannelChart } from "../../components/ChannelChart";
import { normalizeKpis, type Channel } from "../shared/kpis";
import { StatusBars } from "./StatusBars";

export function ChannelDashboardView({
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
}) {
  const metrics = data.source === "virtualpos" ? virtualPosMetrics : data.source === "toku" ? tokuMetrics : paykuMetrics;
  const activeYear = year ?? defaultYear(data.years) ?? null;
  const [churnSource, setChurnSource] = useState<"all" | "vp1" | "vp2">("all");
  const chartData = data.activity
    .filter((entry) => year === null || entry.year === year)
    .map((entry) => ({ ...entry, label: months[entry.month - 1] }));
  const PAID_KW = ["pagad", "aceptad", "accepted", "paid", "success", "cobrad", "aprobad"];
  const isPaid = (s: string) => PAID_KW.some((k) => s.toLowerCase().includes(k));
  const resolvedResources = { ...data.resources };
  const resolvedAmounts = { ...data.resource_amounts };
  if (data.source.startsWith("virtualpos") && activeYear !== null) {
    const paidCharges = (data.charges_monthly ?? []).filter((e) => e.year === activeYear && e.status != null && isPaid(e.status));
    resolvedResources["charge"] = paidCharges.reduce((s, e) => s + e.count, 0);
    resolvedAmounts["charge"] = paidCharges.reduce((s, e) => s + e.amount, 0);
    const paidPayments = (data.payments_monthly ?? []).filter((e) => e.year === activeYear && e.status != null && isPaid(e.status));
    resolvedResources["payment"] = paidPayments.reduce((s, e) => s + e.count, 0);
    resolvedAmounts["payment"] = paidPayments.reduce((s, e) => s + e.amount, 0);
  }
  if (data.source === "toku" && activeYear !== null) {
    const paidInvoices = ((data.invoices_monthly as MonthlyStatusEntry[] | undefined) ?? []).filter((e) => e.year === activeYear && e.status?.toUpperCase() === "PAID");
    resolvedResources["invoice"] = paidInvoices.reduce((s, e) => s + e.count, 0);
    resolvedAmounts["invoice"] = paidInvoices.reduce((s, e) => s + e.amount, 0);
    const successfulTransactions = ((data.transactions_monthly as MonthlyStatusEntry[] | undefined) ?? []).filter((e) => e.year === activeYear && e.status?.toUpperCase() === "SUCCESS");
    resolvedResources["transaction"] = successfulTransactions.reduce((s, e) => s + e.count, 0);
    resolvedAmounts["transaction"] = successfulTransactions.reduce((s, e) => s + e.amount, 0);
  }
  const dataKey = mode;
  const activityTitle = data.source === "toku" ? "Actividad de deudas" : "Actividad de cobros";
  const metricSections = providerGroups.find((group) => group.sections[0].source === data.source)?.sections ?? [];
  const transactionStatusSeries = (data.payments_monthly ?? data.transactions_monthly ?? []) as MonthlyStatusEntry[];
  const isVirtualPos = data.source === "virtualpos";
  const syncLabel = data.last_sync?.status === "completed" ? "Sincronización completada"
    : data.last_sync?.status === "running" ? "Sincronización en curso"
    : data.last_sync?.status === "failed" ? "Última sincronización con errores"
    : "Sin sincronizaciones registradas";
  return (
    <main className="app-shell channel-dashboard-page">
      <p className="eyebrow">{title(data.source).toUpperCase()}</p>
      <header className="channel-hero">
        <div>
          <h2>Resumen operativo {refreshing && <span className="refreshing-badge">⟳ Actualizando</span>}</h2>
          <p>Indicadores y actividad del período seleccionado.</p>
        </div>
        <div className="channel-hero-controls">
          <div className="dashboard-controls">
            <div className="mode-switch">
              <button className={mode === "count" ? "active" : ""} onClick={() => onMode("count")}>Cantidad</button>
              <button className={mode === "amount" ? "active" : ""} onClick={() => onMode("amount")}>Monto</button>
            </div>
            {data.years.length ? (
              <select aria-label="Año" value={year ?? defaultYear(data.years) ?? data.years[0]} onChange={(e) => onYear(Number(e.target.value))}>
                {data.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
              </select>
            ) : null}
          </div>
          <div className="channel-hero-bottom-row">
            <div className={`sync-state ${data.last_sync?.status === "completed" ? "ready" : "attention"}`}><span />{syncLabel}</div>
            <button className={`sync-btn ${syncing ? "syncing" : ""}`} disabled={syncing} onClick={() => onSync(data.source)}>{syncing ? "Sincronizando…" : "↻ Sincronizar"}</button>
            <button className="sync-btn sync-btn-secondary" onClick={() => onReport(data.source)}>Generar reporte</button>
          </div>
        </div>
      </header>
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
      <section className={`metrics provider-metrics${data.source === "payku" ? " payku-metrics" : ""}${data.source.startsWith("virtualpos") ? " vp-metrics" : ""}`} aria-label={`Metricas ${title(data.source)}`}>
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
      {data.kpis ? (
        <>
          <div className="dashboard-section-heading dashboard-section-heading-compact"><div><p className="eyebrow">CARTERA</p><h3>Salud de suscripciones</h3></div></div>
          <ChannelKpiStrip kpis={normalizeKpis(data.source as Channel, data.kpis)} ariaLabel="KPIs de suscripciones" />
        </>
      ) : null}
      <section className={`channel-workspace${isVirtualPos ? " channel-workspace-status" : ""}`}>
        {data.source !== "virtualpos" && (
          <article className="panel chart-panel">
            <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Serie mensual</h3></div></div>
            {data.source === "toku" && data.invoices_monthly?.length ? (
              <MonthlyStatusChart data={data.invoices_monthly} mode={dataKey} year={year} />
            ) : data.source === "payku" && (data.transactions_monthly as MonthlyStatusEntry[] | undefined)?.length ? (
              <MonthlyStatusChart data={data.transactions_monthly as MonthlyStatusEntry[]} mode={dataKey} year={year} />
            ) : chartData.length ? (
              <Suspense fallback={<p className="empty-chart">Cargando gráfico...</p>}>
                <ChannelActivityChart data={chartData} mode={dataKey} color={CHANNEL_COLORS[data.source]} />
              </Suspense>
            ) : (
              <p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>
            )}
          </article>
        )}
        <article className="panel status-panel">
          <p className="eyebrow">ESTADOS</p><h3>Estados de la operación</h3>
          <StatusBars source={data.source} statuses={data.statuses} resources={data.resources} />
        </article>
      </section>
      {(data.charges_monthly?.length || data.payments_monthly?.length || data.invoices_monthly?.length || (data.transactions_monthly as MonthlyEntry[] | undefined)?.length || data.activation_monthly?.length || data.churn_monthly?.length || data.churn_rate_monthly?.length || data.active_subs_monthly?.length || data.cobrable_subs_monthly?.length) ? (
        <>
          <div className="dashboard-section-heading dashboard-section-heading-charts"><div><p className="eyebrow">ACTIVIDAD Y TENDENCIAS</p><h3>Lectura mensual</h3></div></div>
          <section className="extended-charts">
            {isVirtualPos && data.activity.length ? (
              <article className="panel chart-panel-wide">
                <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Serie mensual</h3></div></div>
                <ChannelChart series={[{ key: mode, label: mode === "amount" ? "Monto" : "Cantidad", color: CHANNEL_COLORS[data.source] }]} data={data.activity} kind="bar" mode={mode} year={year} />
              </article>
            ) : null}
            {data.charges_monthly?.length ? (
              <article className={`panel${isVirtualPos ? " chart-order-charges" : ""}`}>
                <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Estado mensual</h3></div></div>
                <MonthlyStatusChart data={data.charges_monthly} mode={mode} year={year} />
              </article>
            ) : null}
            {data.rejected_charges_monthly?.length ? (
              <article className={`panel${isVirtualPos ? " chart-order-rejected" : ""}`}>
                <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Rechazados por motivo</h3></div></div>
                <MonthlyStatusChart data={data.rejected_charges_monthly} mode={mode} year={data.rejected_charges_monthly.some((e) => e.year === year) ? year : null} />
              </article>
            ) : null}
            {data.source === "virtualpos" && data.payments_monthly?.length ? (
              <article className="panel chart-order-transactions">
                <div className="panel-heading"><div><p className="eyebrow">TRANSACCIONES</p><h3>Estado mensual</h3></div></div>
                <MonthlyStatusChart data={data.payments_monthly} mode={mode} year={year} />
              </article>
            ) : null}
            {data.invoices_monthly?.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">FACTURAS</p><h3>Estado mensual</h3></div></div>
                <MonthlyStatusChart data={data.invoices_monthly} mode={mode} year={year} />
              </article>
            ) : null}
            {data.transactions_monthly && !("status" in (data.transactions_monthly[0] ?? {})) && (data.transactions_monthly as MonthlyEntry[]).length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">TRANSACCIONES</p><h3>Serie mensual</h3></div></div>
                <MonthlySimpleChart data={data.transactions_monthly as MonthlyEntry[]} color={CHANNEL_COLORS[data.source]} mode={mode} year={year} />
              </article>
            ) : data.transactions_monthly && "status" in ((data.transactions_monthly as MonthlyStatusEntry[])[0] ?? {}) && (data.transactions_monthly as MonthlyStatusEntry[]).length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">TRANSACCIONES</p><h3>Estado mensual</h3></div></div>
                <MonthlyStatusChart data={data.transactions_monthly as MonthlyStatusEntry[]} mode={mode} year={year} />
              </article>
            ) : null}
            {data.activation_monthly?.length && !isVirtualPos ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Activación mensual</h3></div></div>
                <MonthlyStatusChart data={data.activation_monthly} mode={mode} year={year} />
              </article>
            ) : null}
            {data.churn_monthly?.length && !isVirtualPos ? (
              <article className="panel chart-panel-wide">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Caída mensual</h3></div></div>
                {"status" in ((data.churn_monthly as MonthlyStatusEntry[])[0] ?? {}) ? (
                  <MonthlyStatusChart data={data.churn_monthly as MonthlyStatusEntry[]} mode={mode} year={year} />
                ) : (
                  <MonthlySimpleChart data={data.churn_monthly as MonthlyEntry[]} color={CHANNEL_COLORS[data.source]} mode={mode} year={year} />
                )}
              </article>
            ) : null}
            {data.activation_monthly?.length ? (
              <>
                <article className={`panel${isVirtualPos ? " chart-order-activation" : ""}`}>
                  <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Activación vs Caída</h3></div></div>
                  <ActivacionCaidaChart activaciones={data.activation_monthly} caidas={aggregateChurn(data.churn_monthly ?? [])} year={year} mode={mode} />
                </article>
                <article className={`panel${isVirtualPos ? " chart-order-growth" : ""}`}>
                  <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
                  <CrecimientoMensualChart activaciones={data.activation_monthly} caidas={aggregateChurn(data.churn_monthly ?? [])} year={year} mode={mode} />
                </article>
              </>
            ) : null}
            {data.source === "virtualpos" && data.churn_rate_monthly?.length ? (
              <article className="panel chart-order-churn">
                <div className="panel-heading">
                  <div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div>
                  <div className="mode-switch" style={{ fontSize: "0.8rem" }}>
                    <button className={churnSource === "all" ? "active" : ""} onClick={() => setChurnSource("all")}>Todas</button>
                    <button className={churnSource === "vp1" ? "active" : ""} onClick={() => setChurnSource("vp1")}>VirtualPOS 1</button>
                    <button className={churnSource === "vp2" ? "active" : ""} onClick={() => setChurnSource("vp2")}>VirtualPOS 2</button>
                  </div>
                </div>
                <ChurnMensualChart data={churnSource === "vp1" ? (data.churn_rate_monthly_vp1 ?? []) : churnSource === "vp2" ? (data.churn_rate_monthly_vp2 ?? []) : data.churn_rate_monthly} year={year} />
              </article>
            ) : null}
            {data.source !== "virtualpos" && data.churn_rate_monthly?.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
                <ChurnMensualChart data={data.churn_rate_monthly} year={year} />
              </article>
            ) : null}
            {transactionStatusSeries.length && (data.active_subs_monthly?.length || data.cobrable_subs_monthly?.length) ? (
              <article className={`panel chart-panel-wide${isVirtualPos ? " chart-order-comparison" : ""}`}>
                <div className="panel-heading"><div><p className="eyebrow">RECAUDACIÓN</p><h3>Transacciones vs Suscripciones</h3></div></div>
                <TransaccionesSuscripcionesChart payments={transactionStatusSeries} activeSubs={data.active_subs_monthly ?? []} cobrableSubs={data.cobrable_subs_monthly ?? []} year={year} mode={mode} />
              </article>
            ) : null}
          </section>
        </>
      ) : null}
      <OperationalAlerts
        alerts={data.alerts ?? []}
        loadDetail={(alertId) => getJson<{ items: AlertDetailItem[] }>(`/api/v1/staging/dashboard/${data.source}/alerts/${alertId}`).then((response) => response.items)}
      />
    </main>
  );
}

export type { MonthlyStatusEntry };
