import { EtlPanel } from "./EtlPanel";
import { GeneralClientsPanel } from "./GeneralClientsPanel";
import { GeneralSubscriptionsPanel } from "./GeneralSubscriptionsPanel";
import type { GeneralState } from "./useGeneralDashboard";
import type { useEtl } from "./useEtl";

/**
 * Marco de las vistas consolidadas que aún no tienen pantalla propia (Socios): cabecera, la tabla según
 * `generalView` y el panel del ETL. La vista anterior del resumen (/central/resumen-clasico) se retiró en UX-15;
 * el resumen vive en features/summary.
 */
export function GeneralDashboardView({ general, etl, error, setError, can }: {
  general: GeneralState;
  etl: ReturnType<typeof useEtl>;
  error: string | null;
  setError: (message: string | null) => void;
  can?: (permission: string) => boolean;
}) {
  const { generalView } = general;
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
          </h2>
        </div>
        <p className="sync-copy">KPIs y actividad mensual calculados desde las entidades centralizadas y TCH.</p>
      </section>
      {error ? <p className="error-message">{error}</p> : null}
      {generalView === "subscriptions" ? (
        <GeneralSubscriptionsPanel general={general} can={can} />
      ) : (
        <GeneralClientsPanel general={general} setError={setError} can={can} />
      )}
      <EtlPanel etlRunning={etl.etlRunning} lastEtlRun={etl.lastEtlRun} etlError={etl.etlError} runFullSync={etl.runFullSync} />
    </main>
  );
}
