/** Textos en español del estado de sincronización por canal (compartidos por el menú y el resumen). */
import type { HealthChannel, HealthLevel } from "../hooks/useChannelHealth";

export const LEVEL_LABEL: Record<HealthLevel, string> = {
  ok: "Sincronizado",
  warn: "Sincronización atrasada",
  error: "Error de sincronización",
  unknown: "Sin datos de sincronización",
};
export const GLOBAL_LABEL: Record<HealthLevel, string> = {
  ok: "Todo sincronizado",
  warn: "Sincronización atrasada",
  error: "Error de sincronización",
  unknown: "Sin datos de sincronización",
};
export const CHANNEL_NAME: Record<HealthChannel, string> = { virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
export const CHANNEL_ORDER: HealthChannel[] = ["virtualpos", "toku", "payku", "tch"];
export function channelText(level: HealthLevel, age: number | null | undefined): string {
  return age === null || age === undefined ? LEVEL_LABEL[level] : `${LEVEL_LABEL[level]}: hace ${Math.round(age)} h`;
}
