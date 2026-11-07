import { useState } from "react";
import { label } from "../../i18n/label";
import type { EtlRun } from "../shared/types";

const PROVIDER_NAMES: Record<string, string> = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku" };

/** «VirtualPOS, Toku y Payku»: la lista de canales que leerá el Sync completo, en español. */
export function providerList(providers: string[]): string {
  const names = providers.map((provider) => PROVIDER_NAMES[provider] ?? provider);
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} y ${names.at(-1)}`;
}

/**
 * Panel «Base de datos unificada»: botón de Sync completo y estado de la última corrida. El botón lee todos los
 * canales habilitados en los proveedores, así que pide confirmación y dice qué canales va a leer (QA-02).
 */
export function EtlPanel({ etlRunning, lastEtlRun, etlError, runFullSync, providers = ["virtualpos", "toku", "payku"] }: {
  etlRunning: boolean;
  lastEtlRun: EtlRun | null;
  etlError: string | null;
  runFullSync: () => void;
  providers?: string[];
}) {
  const [confirming, setConfirming] = useState(false);
  const confirm = () => { setConfirming(false); runFullSync(); };
  return (
    <section className="etl-panel">
      <div className="etl-panel-heading">
        <div>
          <p className="eyebrow">CONSOLIDACIÓN</p>
          <h3>Base de datos unificada</h3>
        </div>
        <button
          className={`sync-btn ${etlRunning ? "syncing" : ""}`}
          disabled={etlRunning || providers.length === 0}
          aria-expanded={confirming}
          onClick={() => setConfirming(true)}
        >
          {etlRunning
            ? lastEtlRun?.phase
              ? `${label("phase", lastEtlRun.phase)}…`
              : "Procesando…"
            : "↻ Sync completo"}
        </button>
      </div>
      {confirming && !etlRunning ? (
        <div role="alertdialog" aria-label="Confirmar Sync completo" className="environment-confirm etl-confirm">
          <p>
            Se van a leer las APIs de <strong>{providerList(providers)}</strong> y luego se consolidará la base unificada.
            Puede tardar varios minutos y no se puede lanzar otra sincronización mientras corre. TCH no se lee: entra por su Excel.
          </p>
          <button type="button" className="primary-button" onClick={confirm}>Sí, sincronizar {providerList(providers)}</button>
          <button type="button" className="secondary-button" onClick={() => setConfirming(false)}>Cancelar</button>
        </div>
      ) : null}
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
            {lastEtlRun.records_upserted.toLocaleString("es-CL")} registros
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
