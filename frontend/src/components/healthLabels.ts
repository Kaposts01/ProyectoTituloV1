/** Textos en español del estado de sincronización por canal (compartidos por el menú, el resumen y el orquestador). */
import type { ChannelHealthEntry, HealthChannel, HealthLevel, SyncState } from "../hooks/useChannelHealth";
import { label } from "../i18n/label";

/** Texto del indicador global (el peor estado de los canales). */
export const GLOBAL_LABEL: Record<SyncState, string> = {
  ok: "Todo al día",
  stale: "Sincronización atrasada",
  failed: "Sincronización con fallos",
  running: "Sincronización en curso",
  unknown: "Sin datos de sincronización",
};
/** Peor estado gana en el indicador global: falló > atrasada > en curso > sin datos > al día. */
export const STATE_SEVERITY: Record<SyncState, number> = { ok: 0, unknown: 1, running: 2, stale: 3, failed: 4 };
export const CHANNEL_NAME: Record<HealthChannel, string> = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
export const CHANNEL_ORDER: HealthChannel[] = ["virtualpos", "toku", "payku", "tch"];

const LEVEL_STATE: Record<HealthLevel, SyncState> = { ok: "ok", warn: "stale", error: "failed", unknown: "unknown" };

/** Estado del canal: el `state` del backend o, si no viene (backend anterior), el que corresponde a su nivel. */
export function entryState(entry: Pick<ChannelHealthEntry, "level" | "state">): SyncState {
  return entry.state ?? LEVEL_STATE[entry.level];
}

/** «hace 5 h» hasta 47 h; desde 48 h, en días («hace 4 d»). */
export function ageText(hours: number | null | undefined): string | null {
  if (hours === null || hours === undefined) return null;
  if (hours < 1) return "hace menos de 1 h";
  if (hours < 48) return `hace ${Math.round(hours)} h`;
  return `hace ${Math.floor(hours / 24)} d`;
}

/**
 * 13B: texto del canal. «Al día · hace 2 h», «Atrasada · hace 4 d» (la antigüedad sola nunca es un fallo),
 * «Falló · hace 1 h» (la última corrida terminó con error), «En curso» o «Sin datos de sincronización».
 */
export function channelText(entry: Pick<ChannelHealthEntry, "level" | "state" | "age_hours">): string {
  const state = entryState(entry);
  const text = label("syncState", state);
  const age = state === "running" || state === "unknown" ? null : ageText(entry.age_hours);
  return age ? `${text} · ${age}` : text;
}
