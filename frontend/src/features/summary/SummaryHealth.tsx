import { CHANNEL_NAME, channelText, entryState } from "../../components/healthLabels";
import { label } from "../../i18n/label";
import type { ChannelHealthMap, HealthChannel } from "../../hooks/useChannelHealth";
import { formatDataDate } from "./summaryFormat";
import type { SummaryChannel } from "./summaryTypes";

/**
 * Indicador compacto de salud de los canales del resumen (reutiliza `GET /api/v1/sync-runs/health`). Un canal sin
 * dato de salud no se pinta; sin ninguno, tampoco el bloque. TCH se rotula «Dato al <fecha>» (viene de Excel).
 */
export function SummaryHealth({ channels, health, generatedAt }: { channels: SummaryChannel[]; health: ChannelHealthMap; generatedAt?: string | null }) {
  const entries = channels.map((channel) => health[channel as HealthChannel]).filter((entry) => entry !== undefined);
  if (entries.length === 0) return null;
  const review = entries.filter((entry) => ["failed", "stale", "unknown"].includes(entryState(entry))).length;
  const running = entries.some((entry) => entryState(entry) === "running");
  return (
    <details className="summary-update-details">
      <summary><span>Actualización de datos</span><span className={`summary-update-status${review ? " needs-review" : ""}`}>
        {review ? `${review} ${review === 1 ? "canal requiere" : "canales requieren"} revisión` : running ? "Hay una actualización en curso" : entries.length < channels.length ? "Falta información de algunos canales" : "Canales al día"}
      </span></summary>
    <section className="summary-health" aria-label="Sincronización por canal">
      <p className="summary-update-explanation">Estado de la última sincronización de cada canal. TCH se carga desde reportes Excel.</p>
      <ul className="summary-health-list">
        {entries.map((entry) => {
          const date = entry.channel === "tch" ? formatDataDate(entry.last_finished_at) : null;
          const text = date ? `${label("syncState", entryState(entry))} · Dato al ${date}` : channelText(entry);
          return (
            <li key={entry.channel} className="summary-health-item">
              <span className={`health-dot ${entry.level}`} data-level={entry.level} aria-hidden="true" />
              <span className="summary-health-name">{CHANNEL_NAME[entry.channel]}</span>
              <span className="summary-health-text">{text}</span>
            </li>
          );
        })}
      </ul>
      {generatedAt ? <p className="summary-generated">Vista generada el {generatedAt}. Esta hora no indica cuándo se actualizaron los canales.</p> : null}
    </section>
    </details>
  );
}
