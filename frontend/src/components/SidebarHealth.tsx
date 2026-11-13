import { useId, useState } from "react";
import type { ChannelHealthMap, HealthLevel } from "../hooks/useChannelHealth";
import { CHANNEL_NAME, CHANNEL_ORDER, GLOBAL_LABEL, STATE_SEVERITY, channelText, entryState } from "./healthLabels";

/** Peor nivel gana: error > atrasado > sin datos > ok. */
const SEVERITY: Record<HealthLevel, number> = { ok: 0, unknown: 1, warn: 2, error: 3 };

/**
 * Indicador GLOBAL y compacto de salud de sincronización (encabezado del menú). El nivel es el peor de los
 * canales; al abrirlo muestra el detalle por canal (GET /api/v1/sync-runs/health). Sin datos no se pinta.
 */
export function SidebarHealth({ health }: { health?: ChannelHealthMap }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const entries = CHANNEL_ORDER.map((channel) => health?.[channel]).filter((entry) => entry !== undefined);
  if (entries.length === 0) return null;
  const worst = entries.reduce((acc, entry) => (SEVERITY[entry.level] > SEVERITY[acc] ? entry.level : acc), entries[0].level);
  // 13B: el texto sale del peor ESTADO (falló, atrasada, en curso…); el color, del peor nivel.
  const worstState = entries.map(entryState).reduce((acc, state) => (STATE_SEVERITY[state] > STATE_SEVERITY[acc] ? state : acc));
  return (
    <div className="sidebar-health">
      <button
        type="button"
        className="sidebar-health-toggle"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`health-dot mono ${worst}`} data-level={worst} data-scope="global" aria-hidden="true" />
        <span className="sidebar-health-text">{GLOBAL_LABEL[worstState]}</span>
        <span className="sidebar-health-glyph" aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <ul id={listId} className="sidebar-health-list" aria-label="Sincronización por canal">
          {entries.map((entry) => {
            const text = channelText(entry);
            return (
              <li key={entry.channel} data-state={entryState(entry)}>
                <span className={`health-dot mono ${entry.level}`} aria-hidden="true" data-level={entry.level} />
                <span>{CHANNEL_NAME[entry.channel]}</span>
                <span className="sidebar-health-age">{text}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
