import { useEffect, useState } from "react";
import { friendlyError } from "../../api";
import { fetchSummary } from "./summaryApi";
import type { SummaryChannel, UnifiedSummary } from "./summaryTypes";

export type SummaryState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: UnifiedSummary };

type Result = { key: string; data?: UnifiedSummary; error?: string };

/**
 * Carga el resumen unificado para un mes y un conjunto de canales. Sin `month` el servidor usa el mes actual; sin
 * `channels`, todos los canales permitidos. Devuelve también:
 * - `availableChannels`: los canales que el servidor devolvió en la última petición SIN filtro (los permitidos al usuario);
 * - `currentMonth`: el mes que el servidor tomó como actual en la última petición sin `month`;
 * - `reload`: reintenta la misma petición.
 * El estado de carga se deriva de la clave de la petición (no se apaga ni enciende con efectos).
 */
export function useSummary(month: string | undefined, channels: SummaryChannel[] | undefined) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [availableChannels, setAvailableChannels] = useState<SummaryChannel[]>([]);
  const [currentMonth, setCurrentMonth] = useState<string | null>(null);
  const channelsKey = channels ? channels.join(",") : "";
  const requestKey = `${month ?? ""}|${channelsKey}|${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    const query = { month, channels: channelsKey ? (channelsKey.split(",") as SummaryChannel[]) : undefined };
    fetchSummary(query, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult({ key: requestKey, data });
        if (!query.channels) setAvailableChannels(data.channels);
        if (!query.month) setCurrentMonth(data.month);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setResult({ key: requestKey, error: friendlyError(error, "No se pudo cargar el resumen.") });
      });
    return () => controller.abort();
  }, [month, channelsKey, attempt, requestKey]);

  const current = result?.key === requestKey ? result : null;
  const state: SummaryState = !current
    ? { status: "loading" }
    : current.data
      ? { status: "ready", data: current.data }
      : { status: "error", message: current.error ?? "No se pudo cargar el resumen." };

  return { state, availableChannels, currentMonth, reload: () => setAttempt((value) => value + 1) };
}
