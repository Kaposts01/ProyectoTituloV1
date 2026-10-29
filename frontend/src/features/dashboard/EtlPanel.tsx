import { label } from "../../i18n/label";
import type { EtlRun } from "../shared/types";

/** Panel «Base de datos unificada»: botón de Sync completo y estado de la última corrida. */
export function EtlPanel({ etlRunning, lastEtlRun, etlError, runFullSync }: {
  etlRunning: boolean;
  lastEtlRun: EtlRun | null;
  etlError: string | null;
  runFullSync: () => void;
}) {
  return (
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
              ? `${label("phase", lastEtlRun.phase)}…`
              : "Procesando…"
            : "↻ Sync completo"}
        </button>
      </div>
      {etlError ? <p className="error-message">{etlError}</p> : null}
      {lastEtlRun ? (
        <div className="etl-status">
          <span className={`status-pill ${lastEtlRun.status === "completed" ? "" : lastEtlRun.status === "failed" ? "status-attention" : ""}`}>
            {label("runStatus", lastEtlRun.status)}
          </span>
          {lastEtlRun.phase && lastEtlRun.status === "running" ? (
            <span className="etl-phase-badge">{label("phase", lastEtlRun.phase)}</span>
          ) : null}
          <span className="muted-copy">
            {lastEtlRun.records_upserted.toLocaleString()} registros
            {lastEtlRun.finished_at
              ? ` · ${new Date(lastEtlRun.finished_at).toLocaleString("es-CL")}`
              : " · en progreso…"}
          </span>
          {lastEtlRun.error_message ? (
            <p className="error-message">Texto del proveedor: <span data-raw-text>{lastEtlRun.error_message}</span></p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
