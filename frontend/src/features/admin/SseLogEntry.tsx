import { label } from "../../i18n/label";
import type { SseEvent } from "../shared/types";
import { phaseText } from "./schedulerLabels";

/**
 * Línea del registro en vivo de una sincronización: fase y recurso traducidos. El mensaje `msg` es texto libre
 * del proveedor o del backend: se muestra SIN traducir, bajo el rótulo «Texto del proveedor» y marcado con
 * `data-raw-text` (excepción documentada en docs/engineering/i18n-frontend.md).
 */
export function SseLogEntry({ event: e }: { event: SseEvent }) {
  return (
    <>
      [{e.phase ? phaseText(e.phase) : ""}]
      {e.resource ? ` ${label("resourcePlural", e.resource)}` : ""}
      {e.pct != null ? ` ${e.pct}%` : ""}
      {e.records != null ? ` (${e.records.toLocaleString("es-CL")})` : ""}
      {e.msg ? <> — Texto del proveedor: <span data-raw-text>{e.msg}</span></> : ""}
    </>
  );
}
