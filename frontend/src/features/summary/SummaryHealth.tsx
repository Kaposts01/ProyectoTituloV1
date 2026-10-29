import { CHANNEL_NAME, LEVEL_LABEL, channelText } from "../../components/healthLabels";
import type { ChannelHealthMap, HealthChannel } from "../../hooks/useChannelHealth";
import { formatDataDate } from "./summaryFormat";
import type { SummaryChannel } from "./summaryTypes";

/**
 * Indicador compacto de salud de los canales del resumen (reutiliza `GET /api/v1/sync-runs/health`). Un canal sin
 * dato de salud no se pinta; sin ninguno, tampoco el bloque. TCH se rotula «Dato al <fecha>» (viene de Excel).
 */
export function SummaryHealth({ channels, health }: { channels: SummaryChannel[]; health: ChannelHealthMap }) {
  const entries = channels.map((channel) => health[channel as HealthChannel]).filter((entry) => entry !== undefined);
  if (entries.length === 0) return null;
  return (
    <section className="summary-health" aria-label="Sincronización por canal">
      <ul className="summary-health-list">
        {entries.map((entry) => {
          const date = entry.channel === "tch" ? formatDataDate(entry.last_finished_at) : null;
          const text = date ? `${LEVEL_LABEL[entry.level]} · Dato al ${date}` : channelText(entry.level, entry.age_hours);
          return (
            <li key={entry.channel} className="summary-health-item">
              <span className={`health-dot ${entry.level}`} data-level={entry.level} aria-hidden="true" />
              <span className="summary-health-name">{CHANNEL_NAME[entry.channel]}</span>
              <span className="summary-health-text mono">{text}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
