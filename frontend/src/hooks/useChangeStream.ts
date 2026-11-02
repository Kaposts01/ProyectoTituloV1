import { useEffect, useRef, useState } from "react";
import { invalidateCache } from "../apiCache";

/**
 * Cambios de estado en vivo (RT-12, decisión D9: SSE con polling de respaldo).
 *
 * Abre `GET /api/v1/events/stream` con `EventSource` (la cookie de sesión viaja sola). Cada cambio invalida la caché
 * de la API para que la siguiente consulta traiga datos frescos y se avisa a `onChange`. El navegador reconecta solo y
 * manda `Last-Event-ID`; si la conexión queda cerrada (error HTTP o sin soporte de `EventSource`), se pasa a polling:
 * cada `fallbackMs` se invalida la caché y se reintenta el stream con `?last_event_id=`.
 *
 * El stream no trae datos personales: solo entidad, canal, id externo, tipo de cambio, estados y fecha.
 */

export const CHANGE_STREAM_URL = "/api/v1/events/stream";
export const DEFAULT_FALLBACK_MS = 60000;
const SEEN_LIMIT = 500;

export type ChangeEntity = "charge" | "subscription" | "payment" | "client";
export type ChangeKind = "created" | "status_changed" | "amount_changed" | "reason_changed" | "removed";

export type StreamChange = {
  id: string;
  entity: ChangeEntity | string;
  source: string;
  external_id: string;
  subscription_external_id: string | null;
  kind: ChangeKind | string;
  field: string;
  from: string | null;
  to: string | null;
  at: string;
};

export type ChangeStreamMode = "off" | "connecting" | "live" | "polling";

export type ChangeStreamOptions = {
  enabled: boolean;
  onChange?: (change: StreamChange) => void;
  /** El servidor pidió recargar todo (cursor vencido) o el polling de respaldo hizo un ciclo. */
  onRefresh?: () => void;
  fallbackMs?: number;
};

type Handlers = Pick<ChangeStreamOptions, "onChange" | "onRefresh">;

/** Recuerda los últimos ids para descartar repetidos (el servidor reenvía un margen al reanudar). */
export class SeenIds {
  private readonly order: string[] = [];
  private readonly set = new Set<string>();
  private readonly limit: number;

  constructor(limit = SEEN_LIMIT) {
    this.limit = limit;
  }

  /** `true` si el id es nuevo (y lo registra). */
  add(id: string): boolean {
    if (this.set.has(id)) return false;
    this.set.add(id);
    this.order.push(id);
    while (this.order.length > this.limit) this.set.delete(this.order.shift() as string);
    return true;
  }
}

export function parseChange(id: string, raw: string): StreamChange | null {
  try {
    const data = JSON.parse(raw) as Partial<StreamChange> | null;
    if (!data || typeof data !== "object" || typeof data.entity !== "string" || typeof data.kind !== "string") return null;
    return {
      id,
      entity: data.entity,
      source: String(data.source ?? ""),
      external_id: String(data.external_id ?? ""),
      subscription_external_id: data.subscription_external_id ?? null,
      kind: data.kind,
      field: String(data.field ?? ""),
      from: data.from ?? null,
      to: data.to ?? null,
      at: String(data.at ?? ""),
    };
  } catch {
    return null;
  }
}

export function useChangeStream({ enabled, onChange, onRefresh, fallbackMs = DEFAULT_FALLBACK_MS }: ChangeStreamOptions): ChangeStreamMode {
  const [mode, setMode] = useState<ChangeStreamMode>("off");
  const handlers = useRef<Handlers>({ onChange, onRefresh });
  useEffect(() => {
    handlers.current = { onChange, onRefresh };
  }, [onChange, onRefresh]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let source: EventSource | null = null;
    let lastId = "";
    let timer: ReturnType<typeof setInterval> | null = null;
    const seen = new SeenIds();

    const refresh = () => {
      invalidateCache();
      handlers.current.onRefresh?.();
    };

    const stopPolling = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };

    const startPolling = () => {
      setMode("polling");
      if (timer !== null) return;
      timer = setInterval(() => {
        refresh();
        if (typeof EventSource !== "undefined") open();
      }, fallbackMs);
    };

    function open() {
      if (disposed || typeof EventSource === "undefined") return;
      source?.close();
      const url = lastId ? `${CHANGE_STREAM_URL}?last_event_id=${encodeURIComponent(lastId)}` : CHANGE_STREAM_URL;
      const es = new EventSource(url, { withCredentials: true });
      source = es;
      setMode((current) => (current === "polling" ? current : "connecting"));
      es.addEventListener("ready", (event) => {
        const id = (event as MessageEvent).lastEventId;
        if (id && !lastId) lastId = id;
        stopPolling();
        setMode("live");
      });
      es.addEventListener("change", (event) => {
        const message = event as MessageEvent<string>;
        if (message.lastEventId) lastId = message.lastEventId;
        const change = parseChange(message.lastEventId, message.data);
        if (!change || !seen.add(change.id || `${change.at}|${change.external_id}|${change.kind}`)) return;
        invalidateCache();
        handlers.current.onChange?.(change);
      });
      es.addEventListener("reset", () => refresh());
      es.onerror = () => {
        // CONNECTING: el navegador reintenta solo con Last-Event-ID. CLOSED: error HTTP (p. ej. sesión vencida).
        if (es.readyState === EventSource.CLOSED) {
          es.close();
          if (source === es) source = null;
          startPolling();
        }
      };
    }

    const start = setTimeout(() => {
      if (typeof EventSource === "undefined") startPolling();
      else open();
    }, 0);

    return () => {
      disposed = true;
      clearTimeout(start);
      stopPolling();
      source?.close();
      source = null;
      setMode("off");
    };
  }, [enabled, fallbackMs]);

  return enabled ? mode : "off";
}
