import { label } from "../../i18n/label";
import type { SchedulerJob } from "../shared/types";

/** Canales con API que sincroniza el panel (VirtualPOS 1 y 2, Toku, Payku). TCH se importa por reporte. */
export const API_CHANNELS = ["virtualpos1", "virtualpos2", "toku", "payku"];

/** Texto propio del panel para las fases que muestra en su lista de progreso. */
const PHASE_LABELS: Record<string, string> = {
  sync_virtualpos1: "VirtualPOS VP1",
  sync_virtualpos2: "VirtualPOS VP2",
  sync_toku: "Toku",
  sync_payku: "Payku",
  consolidating: "Consolidación centralizada",
};

/** Texto de una fase: el del panel si lo tiene y, si no, el catálogo («Desconocido (fase)» si tampoco). */
export function phaseText(phase: string): string {
  return PHASE_LABELS[phase] ?? label("phase", phase);
}

/** Tipo de una corrida a partir de los canales que procesó. */
export function runTypeLabel(channels: string[] | null, enabled: string[]): string {
  if (!channels || channels.length === 0) return "—";
  const short: Record<string, string> = { virtualpos1: "VP1", virtualpos2: "VP2", toku: "Toku", payku: "Payku", tch: "TCH" };
  const apiChannels = API_CHANNELS.filter((c) => enabled.includes(c));
  const hasAllApi = apiChannels.length > 0 && apiChannels.every((c) => channels.includes(c));
  if (hasAllApi) return "Sync completa";
  if (channels.length === 1 && channels[0] === "tch") return "TCH (importación)";
  return channels.map((c) => short[c] ?? label("channel", c)).join(" + ");
}

/**
 * QA-15: «Falló: Toku» para los canales que fallaron en una corrida. El tipo de la corrida solo nombra los canales que
 * terminaron bien, así que un fallo de Toku dentro de una corrida «VP1 · Parcial» no se veía en el Historial.
 */
export function failedChannelsLabel(failed: string[] | null | undefined): string | null {
  if (!failed || failed.length === 0) return null;
  const short: Record<string, string> = { virtualpos1: "VP1", virtualpos2: "VP2", toku: "Toku", payku: "Payku", tch: "TCH" };
  return `Falló: ${failed.map((c) => short[c] ?? label("channel", c)).join(", ")}`;
}

/** Duración legible entre dos instantes (ISO o milisegundos). */
export function fmtDuration(start: string | number | null | undefined, end: string | number | null | undefined): string {
  if (start === null || start === undefined || end === null || end === undefined) return "—";
  const s = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** 13D: insignia del proceso. Estado + texto (nunca solo color, DESIGN.md). */
export function jobBadge(job: SchedulerJob): { text: string; cls: string } {
  if (job.status === "running") return { text: "En curso", cls: "badge-blue" };
  const last = job.last_run?.status;
  if (last === "failed") return { text: "Falló", cls: "badge-red" };
  if (last === "partial") return { text: "Parcial", cls: "badge-orange" };
  if (last === "completed") return { text: "OK", cls: "badge-green" };
  return { text: label("runStatus", job.status), cls: "badge-gray" };
}
