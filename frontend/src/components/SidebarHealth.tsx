import { useId, useState } from "react";
import type { ChannelHealthMap, HealthChannel, HealthLevel } from "../hooks/useChannelHealth";

const LEVEL_LABEL: Record<HealthLevel, string> = {
  ok: "Sincronizado",
  warn: "Sincronización atrasada",
  error: "Error de sincronización",
  unknown: "Sin datos de sincronización",
};
const GLOBAL_LABEL: Record<HealthLevel, string> = {
  ok: "Todo sincronizado",
  warn: "Sincronización atrasada",
  error: "Error de sincronización",
  unknown: "Sin datos de sincronización",
};
const CHANNEL_NAME: Record<HealthChannel, string> = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
const CHANNEL_ORDER: HealthChannel[] = ["virtualpos", "toku", "payku", "tch"];
/** Peor nivel gana: error > atrasado > sin datos > ok. */
const SEVERITY: Record<HealthLevel, number> = { ok: 0, unknown: 1, warn: 2, error: 3 };

function channelText(level: HealthLevel, age: number | null | undefined): string {
  return age === null || age === undefined ? LEVEL_LABEL[level] : `${LEVEL_LABEL[level]}: hace ${Math.round(age)} h`;
}

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
        <span className="sidebar-health-text">{GLOBAL_LABEL[worst]}</span>
        <span className="sidebar-health-glyph" aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <ul id={listId} className="sidebar-health-list" aria-label="Sincronización por canal">
          {entries.map((entry) => {
            const text = channelText(entry.level, entry.age_hours);
            return (
              <li key={entry.channel}>
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
