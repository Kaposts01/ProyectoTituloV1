import { defaultYear } from "../shared/utils";
import { EtlPanel } from "./EtlPanel";
import { GeneralClientsPanel } from "./GeneralClientsPanel";
import { GeneralSubscriptionsPanel } from "./GeneralSubscriptionsPanel";
import { GeneralSummaryContent } from "./GeneralSummaryContent";
import type { GeneralState } from "./useGeneralDashboard";
import type { useEtl } from "./useEtl";

/** Dashboard general: cabecera, selector de modo/año y, según `generalView`, resumen, clientes o suscripciones. */
export function GeneralDashboardView({ general, etl, error, setError, onReport }: {
  general: GeneralState;
  etl: ReturnType<typeof useEtl>;
  error: string | null;
  setError: (message: string | null) => void;
  onReport: (scope: string) => void;
}) {
  const { generalData, generalView, generalRefreshing, summaryRefreshing, generalMode, setGeneralMode, generalYear, setGeneralYear } = general;
  return (
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
            <button className="sync-btn sync-btn-secondary" onClick={() => onReport("general")}>Generar reporte</button>
          </div>
          </>
        ) : (
          <p className="sync-copy">KPIs y actividad mensual calculados desde las entidades centralizadas y TCH.</p>
        )}
      </section>
      {error ? <p className="error-message">{error}</p> : null}
      {generalView === "subscriptions" ? (
        <GeneralSubscriptionsPanel general={general} />
      ) : generalView === "clients" ? (
        <GeneralClientsPanel general={general} setError={setError} />
      ) : generalData ? (
        <GeneralSummaryContent general={general} generalData={generalData} />
      ) : (
        <p className="muted-copy">Cargando indicadores consolidados...</p>
      )}
      <EtlPanel etlRunning={etl.etlRunning} lastEtlRun={etl.lastEtlRun} etlError={etl.etlError} runFullSync={etl.runFullSync} />
    </main>
  );
}
