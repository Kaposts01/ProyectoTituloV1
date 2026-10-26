import { useState, type ReactNode } from "react";
import { getJson } from "../../api";
import {
  ChurnMensualChart,
  CrecimientoMensualChart,
  type MonthlyStatusEntry,
} from "../../MonthlyStatusChart";
import { OperationalAlerts } from "./OperationalAlerts";
import { providerGroups } from "../../navigation";
import {
  virtualPosMetrics, tokuMetrics, paykuMetrics,
} from "../shared/constants";
import { title, defaultYear, aggregateChurn } from "../shared/utils";
import type { AlertDetailItem, ChannelDashboard } from "../shared/types";
import { Metric } from "./Metric";
import { ChannelKpiStrip } from "../../components/ChannelKpiStrip";
import { ChannelChart } from "../../components/ChannelChart";
import { normalizeKpis, PAYKU_COVERAGE_NOTE, type Channel } from "../shared/kpis";
import {
  activationVsChurnChart, activeSubsLineChart, coverageGapAnnotations, monthlyTrendChart,
  paymentMethodSnapshot, statusStackedChart, tokuCollectionsChart, type ChartProps,
} from "./channelCharts";
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
  const activityTitle = "Tendencia de cobros";
  const isToku = data.source === "toku";
  const isPayku = data.source === "payku";
  const chartYear = (rows: { year: number }[]) => (rows.some((e) => e.year === year) ? year : null);
  const chart = (props: ChartProps, kind: "bar" | "stacked" | "line" | "grouped", opts: { legend?: boolean; mode?: "count" | "amount"; ariaLabel: string; annotations?: ReturnType<typeof coverageGapAnnotations> }) => (
    <ChannelChart series={props.series} data={props.rows} kind={kind} mode={opts.mode ?? mode} year={chartYear(props.rows)} legend={opts.legend} ariaLabel={opts.ariaLabel} annotations={opts.annotations} />
  );
  const panel = (props: ChartProps, eyebrow: string, heading: string, body: ReactNode, wide = false) =>
    props.rows.length ? (
      <article className={`panel${wide ? " chart-panel-wide" : ""}`}>
        <div className="panel-heading"><div><p className="eyebrow">{eyebrow}</p><h3>{heading}</h3></div></div>
        {body}
      </article>
    ) : null;
  const activeSubs = activeSubsLineChart(data.active_subs_monthly);
  const altasBajas = activationVsChurnChart(data.activation_monthly, data.churn_monthly, mode);
  const gaps = coverageGapAnnotations(data.coverage_gaps);
  const methodSnapshot = paymentMethodSnapshot(data.statuses);
  const metricSections = providerGroups.find((group) => group.sections[0].source === data.source)?.sections ?? [];
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
        {isToku ? (
          <article className="panel chart-panel">
            <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Cobros mensuales (transacciones)</h3></div></div>
            {data.activity.length ? chart(tokuCollectionsChart(data.activity, mode), "bar", { ariaLabel: "Gráfico de cobros mensuales de Toku (transacciones)" }) : <p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>}
          </article>
        ) : null}
        {isPayku ? (() => {
          const tx = statusStackedChart(data.transactions_monthly, mode);
          const fallback = monthlyTrendChart(data.activity, mode, mode === "amount" ? "Monto" : "Cobros");
          const body = tx.rows.length
            ? chart(tx, "stacked", { legend: true, annotations: gaps, ariaLabel: "Gráfico de transacciones mensuales de Payku por estado" })
            : fallback.rows.length
              ? chart(fallback, "bar", { annotations: gaps, ariaLabel: "Gráfico de cobros mensuales de Payku" })
              : <p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>;
          return (
            <article className="panel chart-panel">
              <div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Transacciones mensuales</h3></div></div>
              {body}
              <p className="muted-copy">{PAYKU_COVERAGE_NOTE}.{gaps.length ? " Las bandas grises marcan meses sin cobros." : ""}</p>
            </article>
          );
        })() : null}
        <article className="panel status-panel">
          <p className="eyebrow">ESTADOS</p><h3>Estados de la operación</h3>
          <StatusBars source={data.source} statuses={data.statuses} resources={data.resources} />
        </article>
      </section>
      <div className="dashboard-section-heading dashboard-section-heading-charts"><div><p className="eyebrow">ACTIVIDAD Y TENDENCIAS</p><h3>Lectura mensual</h3></div></div>
      <section className="extended-charts">
        {panel(activeSubs, "SUSCRIPCIONES", "Suscripciones activas acumuladas", chart(activeSubs, "line", { mode: "count", ariaLabel: "Gráfico de suscripciones activas acumuladas" }), isVirtualPos)}
        {(() => { const p = statusStackedChart(data.charges_monthly, mode); return panel(p, "CARGOS", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de cargos mensuales por estado" }), isVirtualPos); })()}
        {(() => { const p = statusStackedChart(data.rejected_charges_monthly, mode); return panel(p, "CARGOS", "Rechazados por motivo", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de cargos rechazados por motivo" })); })()}
        {isVirtualPos ? (() => { const p = statusStackedChart(data.payments_monthly, mode); return panel(p, "TRANSACCIONES", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de transacciones mensuales por estado" })); })() : null}
        {(() => { const p = statusStackedChart(data.invoices_monthly, mode); return panel(p, "FACTURAS", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de facturas mensuales por estado" })); })()}
        {isToku ? (() => { const p = statusStackedChart(data.transactions_monthly, mode); return panel(p, "TRANSACCIONES", "Estado mensual", chart(p, "stacked", { legend: true, ariaLabel: "Gráfico de transacciones mensuales por estado" })); })() : null}
        {panel(altasBajas, "SUSCRIPCIONES", "Altas vs bajas", chart(altasBajas, "grouped", { legend: true, ariaLabel: "Gráfico de altas y bajas mensuales de suscripciones" }))}
        {isToku && methodSnapshot.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">MÉTODOS DE PAGO</p><h3>Por estado (foto actual)</h3></div></div>
            <StatusBars source="toku" statuses={methodSnapshot} resources={{}} />
            <p className="muted-copy">Estado a la fecha de la última sincronización; no es una serie mensual.</p>
          </article>
        ) : null}
        {data.activation_monthly?.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
            <CrecimientoMensualChart activaciones={data.activation_monthly} caidas={aggregateChurn(data.churn_monthly ?? [])} year={year} mode={mode} />
          </article>
        ) : null}
        {isVirtualPos && data.churn_rate_monthly?.length ? (
          <article className="panel">
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
        {!isVirtualPos && data.churn_rate_monthly?.length ? (
          <article className="panel">
            <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
            <ChurnMensualChart data={data.churn_rate_monthly} year={year} />
          </article>
        ) : null}
      </section>
      <OperationalAlerts
        alerts={data.alerts ?? []}
        loadDetail={(alertId) => getJson<{ items: AlertDetailItem[] }>(`/api/v1/staging/dashboard/${data.source}/alerts/${alertId}`).then((response) => response.items)}
      />
    </main>
  );
}

export type { MonthlyStatusEntry };
