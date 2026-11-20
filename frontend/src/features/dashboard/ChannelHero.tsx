import { title, defaultYear } from "../shared/utils";

type Mode = "count" | "amount";

/**
 * Cabecera del dashboard de un canal (eyebrow, «Resumen operativo», descripción, modo, año y acciones).
 * Es la misma para la vista con datos y para el estado de carga (PERF-03, d264 A): mientras llegan los datos se
 * muestra la cabecera real con los controles deshabilitados, y al llegar solo se habilitan: ni el alto ni la
 * posición de nada cambian. No importa gráficos, así que puede cargarse con el arranque sin sumar peso.
 */
export type ChannelHeroProps = {
  source: string;
  /** Verdadero mientras no hay datos del canal: controles deshabilitados y sin estado de sincronización. */
  loading?: boolean;
  years?: number[];
  lastSyncStatus?: string | null;
  mode?: Mode;
  year?: number | null;
  syncing?: boolean;
  refreshing?: boolean;
  syncUnavailable?: boolean;
  unavailableReason?: string;
  reasonId?: string;
  onMode?: (mode: Mode) => void;
  onYear?: (year: number) => void;
  onSync?: (source: string) => void;
  onReport?: (scope: string) => void;
};

export function ChannelHero({
  source, loading = false, years = [], lastSyncStatus = null, mode = "count", year = null, syncing = false, refreshing = false,
  syncUnavailable = false, unavailableReason, reasonId, onMode, onYear, onSync, onReport,
}: ChannelHeroProps) {
  const syncLabel = lastSyncStatus === "completed" ? "Sincronización completada"
    : lastSyncStatus === "running" ? "Sincronización en curso"
    : lastSyncStatus === "failed" ? "Última sincronización con errores"
    : "Sin sincronizaciones registradas";
  return (
    <>
      <p className="eyebrow">{title(source).toUpperCase()}</p>
      <header className="channel-hero">
        <div>
          <h2>Resumen operativo {refreshing && <span className="refreshing-badge">⟳ Actualizando</span>}</h2>
          <p>Indicadores y actividad del período seleccionado.</p>
        </div>
        <div className="channel-hero-controls">
          <div className="dashboard-controls">
            <div className="mode-switch">
              <button className={mode === "count" ? "active" : ""} disabled={loading} onClick={() => onMode?.("count")}>Cantidad</button>
              <button className={mode === "amount" ? "active" : ""} disabled={loading} onClick={() => onMode?.("amount")}>Monto</button>
            </div>
            {loading ? (
              <select aria-label="Año" disabled value=""><option value="">{new Date().getFullYear()}</option></select>
            ) : years.length ? (
              <select aria-label="Año" value={year ?? defaultYear(years) ?? years[0]} onChange={(e) => onYear?.(Number(e.target.value))}>
                {years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
              </select>
            ) : null}
          </div>
          <div className="channel-hero-bottom-row">
            <div className={`sync-state ${!loading && lastSyncStatus === "completed" ? "ready" : "attention"}`}><span />{loading ? "Cargando estado…" : syncLabel}</div>
            <button className={`sync-btn ${syncing ? "syncing" : ""}`} disabled={loading || syncing || syncUnavailable} title={syncUnavailable ? unavailableReason : undefined} aria-describedby={syncUnavailable ? reasonId : undefined} onClick={() => onSync?.(source)}>{syncing ? "Sincronizando…" : "↻ Sincronizar"}</button>
            <button className="sync-btn sync-btn-secondary" disabled={loading} onClick={() => onReport?.(source)}>Generar reporte</button>
          </div>
          {syncUnavailable ? <p id={reasonId} className="sync-reason muted-copy">{unavailableReason}</p> : null}
        </div>
      </header>
    </>
  );
}
