import { label } from "../../i18n/label";
import { ActivationsVsChurnChart, ChannelKpiChart, MonthlyRevenueChart, MonthlyStatusChart } from "../../MonthlyStatusChart";
import type { ChannelRow, MonthlyEntry } from "../../MonthlyStatusChart";
import { defaultYear } from "../shared/utils";
import type { GeneralDashboard } from "../shared/types";
import { GeneralKpis } from "./GeneralKpis";
import { Metric } from "./Metric";
import { OperationalAlerts } from "./OperationalAlerts";
import { applyChargeFilter, type ChargeFilter } from "./applyChargeFilter";

const CHARGE_FILTERS: ChargeFilter[] = ["all", "paid", "rejected"];
const CHARGE_FILTER_LABEL: Record<ChargeFilter, string> = { all: "Todas", paid: "Pagada", rejected: "Rechazada" };
import type { GeneralState } from "./useGeneralDashboard";

/** Métricas, KPIs, gráficos, alertas y tarjetas por canal del resumen general (con `generalData` ya cargado). */
export function GeneralSummaryContent({ general, generalData }: { general: GeneralState; generalData: GeneralDashboard }) {
  const {
    summary,
    generalMode,
    generalYear,
    debtFilter,
    setDebtFilter,
    transactionFilter,
    setTransactionFilter,
  } = general;
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
  return (
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
          <MonthlyRevenueChart data={generalData.transactions_effective_monthly} year={generalYear} />
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas y bajas por mes</h3></div></div>
          <ActivationsVsChurnChart activations={generalData.activations_monthly} cancellations={cancellationsAsEntries} year={generalYear} mode={generalMode} />
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
              {CHARGE_FILTERS.map(f => (
                <button key={f} className={debtFilter === f ? "active" : ""} onClick={() => setDebtFilter(f)}>
                  {CHARGE_FILTER_LABEL[f]}
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
              {CHARGE_FILTERS.map(f => (
                <button key={f} className={transactionFilter === f ? "active" : ""} onClick={() => setTransactionFilter(f)}>
                  {CHARGE_FILTER_LABEL[f]}
                </button>
              ))}
            </div>
          </div>
          <MonthlyStatusChart data={applyChargeFilter(generalData.transactions_effective_monthly, transactionFilter)} mode={generalMode} year={generalYear} />
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
                <div><p className="eyebrow">{label("channel", channel.source).toUpperCase()}</p><h3>{channel.active_subscriptions.toLocaleString("es-CL")} suscripciones vigentes</h3></div>
                {lastSync ? <span className={`status-pill ${lastSync.status === "completed" ? "" : "status-attention"}`}>{label("runStatus", lastSync.status)}</span> : null}
              </div>
              <div className="channel-summary-details">
                <div><span>Operación</span><strong>{channel.clients.toLocaleString("es-CL")} clientes · {channel.accepted.toLocaleString("es-CL")} aceptadas</strong></div>
                <div><span>Recaudación</span><strong>${channel.amount.toLocaleString("es-CL")}</strong></div>
                <div><span>{staging ? "Carga staging" : "Carga local"}</span><strong>{staging ? `${staging.records.toLocaleString("es-CL")} registros` : "Histórico TCH integrado"}</strong></div>
                <div><span>Consolidación</span><strong>Entidades centralizadas disponibles</strong></div>
              </div>
              {staging ? <p className="resource-copy">{Object.entries(staging.resources).map(([resource, count]) => `${label("resourcePlural", resource)}: ${count}`).join(" · ")}</p> : null}
              {lastSync?.finished_at ? <p className="channel-summary-sync">Última carga: {new Date(lastSync.finished_at).toLocaleString("es-CL")} · {lastSync.records_processed.toLocaleString("es-CL")} procesados</p> : null}
            </article>
          );
        })}
      </section>
    </>
  );
}
