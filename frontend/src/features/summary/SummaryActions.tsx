import { label } from "../../i18n/label";
import { formatKpi } from "../../components/formatKpi";
import { channelText, entryState } from "../../components/healthLabels";
import type { ChannelHealthMap } from "../../hooks/useChannelHealth";
import type { PrimaryMetric } from "./dashboardContext";
import type { UnifiedSummary } from "./summaryTypes";

export function SummaryActions({ summary, health, healthReady, can, onOpenPath, onDetail }: {
  summary: UnifiedSummary; health: ChannelHealthMap; healthReady: boolean; can: (permission: string) => boolean;
  onOpenPath?: (path: string) => void; onDetail: (key: PrimaryMetric, button: HTMLButtonElement) => void;
}) {
  const needsUpdate = healthReady ? summary.channels.filter((c) => !health[c] || ["failed", "stale", "unknown"].includes(entryState(health[c]!))) : [];
  const running = healthReady ? summary.channels.filter((c) => health[c] && entryState(health[c]!) === "running") : [];
  const up = summary.dataQuality.activationsWithoutDate, down = summary.dataQuality.cancellationsWithoutDate;
  const outstanding = summary.kpis.uncollected.value;
  const canSync = can("sync_runs.view") || can("sync.run");
  const count = Number(needsUpdate.length > 0) + Number(running.length > 0) + Number(up > 0 || down > 0) + Number(outstanding !== null && outstanding > 0);
  const syncLink = (text: string) => canSync ? <a href="/admin/sincronizaciones" onClick={(event) => {
    if (onOpenPath && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onOpenPath("/admin/sincronizaciones"); }
  }}>{text}</a> : <span className="muted-copy">Pide a un administrador revisar la sincronización o la última carga de reportes.</span>;
  if (count === 0) return null;
  return <section className="summary-actions" aria-labelledby="summary-actions-title">
    <h2 id="summary-actions-title" className="summary-section-title">Qué revisar <span className="mono">({count})</span></h2>
    <ul>
      {needsUpdate.length > 0 ? <li><div><strong>Revisa la actualización de los datos</strong>
        <p>{needsUpdate.map((c) => `${label("channel", c)}: ${health[c] ? channelText(health[c]!) : "sin información de actualización"}`).join(" · ")}.</p>
        <p>Los indicadores usan lo registrado hasta la última actualización. TCH se actualiza mediante reportes Excel.</p></div>{syncLink("Revisar sincronización")}</li> : null}
      {running.length > 0 ? <li><div><strong>Hay una actualización en curso</strong><p>{running.map((c) => label("channel", c)).join(", ")}. Espera a que termine y vuelve a consultar el Dashboard.</p></div>{syncLink("Ver progreso")}</li> : null}
      {outstanding !== null && outstanding > 0 ? <li><div><strong>Hay {formatKpi(outstanding, "clp")} no cobrados en el mes seleccionado</strong>
        <p>Revisa el origen y los registros relacionados antes de decidir la gestión de cobro.</p></div>
        <button type="button" className="secondary-button" onClick={(event) => onDetail("uncollected", event.currentTarget)}>Revisar no cobrado</button></li> : null}
      {up > 0 || down > 0 ? <li><div><strong>Revisa las fechas de las suscripciones</strong>
        <p className="summary-quality">Datos incompletos: {[
          up > 0 ? `${up.toLocaleString("es-CL")} ${up === 1 ? "suscripción sin fecha de alta válida" : "suscripciones sin fecha de alta válida"}` : null,
          down > 0 ? `${down.toLocaleString("es-CL")} ${down === 1 ? "baja sin fecha de baja válida" : "bajas sin fecha de baja válida"}` : null,
        ].filter(Boolean).join(" y ")}. No entran en los indicadores de ningún mes.</p></div>{syncLink("Revisar origen de los datos")}</li> : null}
    </ul>
  </section>;
}
