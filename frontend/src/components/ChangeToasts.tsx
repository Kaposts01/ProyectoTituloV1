import { useCallback, useEffect, useRef, useState } from "react";
import { useChangeStream, type StreamChange } from "../hooks/useChangeStream";
import { label, tryLabel } from "../i18n/label";
import "./ChangeToasts.css";

/**
 * Avisos breves de cambios de estado en vivo (RT-12). Solo muestra cambios de estado y de monto; el resto (altas,
 * glosas) solo invalida la caché. Si llegan muchos juntos se agrupan en un único aviso. Sin datos personales: el
 * stream solo trae ids externos del proveedor, estados y montos.
 */

export const TOAST_TTL_MS = 8000;
export const MAX_TOASTS = 3;
export const BURST_LIMIT = 5;
const BURST_WINDOW_MS = 2000;

type Toast = { key: string; title: string; detail: string; id?: string };

function channelName(source: string): string {
  return tryLabel("channel", source) ?? source;
}

export function describeChange(change: StreamChange): Toast | null {
  const entity = label("resource", change.entity);
  const where = channelName(change.source);
  if (change.kind === "status_changed") {
    return {
      key: change.id,
      title: `Cambió el estado: ${entity} de ${where}`,
      detail: `${label("status", change.from)} → ${label("status", change.to)}`,
      id: change.external_id,
    };
  }
  if (change.kind === "amount_changed") {
    return { key: change.id, title: `Cambió el monto: ${entity} de ${where}`, detail: `${change.from ?? "—"} → ${change.to ?? "—"}`, id: change.external_id };
  }
  return null;
}

export function ChangeToasts({ enabled = true }: { enabled?: boolean }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const burst = useRef<{ start: number; count: number }>({ start: 0, count: 0 });
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((key: string) => {
    const timer = timers.current.get(key);
    if (timer) clearTimeout(timer);
    timers.current.delete(key);
    setToasts((list) => list.filter((t) => t.key !== key));
  }, []);

  const push = useCallback((toast: Toast) => {
    setToasts((list) => [toast, ...list.filter((t) => t.key !== toast.key)].slice(0, MAX_TOASTS));
    const old = timers.current.get(toast.key);
    if (old) clearTimeout(old);
    timers.current.set(toast.key, setTimeout(() => dismiss(toast.key), TOAST_TTL_MS));
  }, [dismiss]);

  const onChange = useCallback((change: StreamChange) => {
    const toast = describeChange(change);
    if (!toast) return;
    const now = Date.now();
    if (now - burst.current.start > BURST_WINDOW_MS) burst.current = { start: now, count: 0 };
    burst.current.count += 1;
    if (burst.current.count > BURST_LIMIT) {
      push({ key: "burst", title: "Hay cambios nuevos", detail: `${burst.current.count} cambios de estado o monto en los últimos segundos.` });
      return;
    }
    push(toast);
  }, [push]);

  useChangeStream({ enabled, onChange });

  useEffect(() => {
    const map = timers.current;
    return () => { map.forEach((timer) => clearTimeout(timer)); map.clear(); };
  }, []);

  if (!toasts.length) return null;
  return (
    <div className="change-toasts" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.key} className="change-toast" role="status">
          <div className="change-toast-body">
            <strong>{toast.title}</strong>
            <span>{toast.detail}</span>
            {toast.id ? <span className="mono" data-raw-text>{toast.id}</span> : null}
          </div>
          <button type="button" className="change-toast-close" aria-label="Cerrar aviso" onClick={() => dismiss(toast.key)}>×</button>
        </div>
      ))}
    </div>
  );
}
