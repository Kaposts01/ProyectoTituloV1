import { CHANNEL_NAME, channelText, entryState } from "../../components/healthLabels";
import type { ChannelHealthMap } from "../../hooks/useChannelHealth";
import { formatDataDate } from "./summaryFormat";
import type { SummaryChannel } from "./summaryTypes";

/**
 * La salud describe ejecuciones, no cobertura de movimientos ni fecha del cálculo.
 * Conserva los canales permitidos sin respuesta para no aparentar una actualización confirmada.
 */
export function SummaryHealth({ channels, health, ready, generatedAt }: { channels: SummaryChannel[]; health: ChannelHealthMap; ready: boolean; generatedAt?: string | null }) {
  if (channels.length === 0) return null;
  const review = channels.filter((channel) => !health[channel] || ["failed", "stale", "unknown"].includes(entryState(health[channel]!))).length;
  const running = channels.some((channel) => health[channel] && entryState(health[channel]!) === "running");
  return (
    <details className="summary-update-details">
      <summary><span>Actualización de datos</span><span className={`summary-update-status${ready && review ? " needs-review" : ""}`}>
        {!ready ? "Consultando actualización…" : review ? `${review} ${review === 1 ? "canal requiere" : "canales requieren"} revisión` : running ? "Hay una actualización en curso" : "Canales al día"}
      </span></summary>
    <section className="summary-health" aria-label="Sincronización por canal">
      <p className="summary-update-explanation">Estado de la última ejecución por canal. Una ejecución reciente no garantiza cobertura completa. TCH se carga desde reportes Excel.</p>
      <ul className="summary-health-list">
        {channels.map((channel) => {
          const entry = ready ? health[channel] : undefined;
          const date = entry ? formatDataDate(entry.last_finished_at) : null;
          const text = !ready ? "Consultando…" : entry ? channelText(entry) : "Sin información de actualización";
          return (
            <li key={channel} className="summary-health-item">
              <span className={`health-dot ${entry?.level ?? "unknown"}`} data-level={entry?.level ?? "unknown"} aria-hidden="true" />
              <span className="summary-health-name">{CHANNEL_NAME[channel]}</span>
              <span className="summary-health-text">{text}{date ? <span className="summary-health-date">Última ejecución: {date}</span> : null}</span>
            </li>
          );
        })}
      </ul>
      {generatedAt ? <p className="summary-generated">Vista generada el {generatedAt}. Esta hora no indica cuándo se actualizaron los canales.</p> : null}
    </section>
    </details>
  );
}
