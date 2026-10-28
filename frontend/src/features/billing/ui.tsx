import { useEffect, useId, useRef, type ReactNode } from "react";
import { statusLabel, statusTone, type Tone } from "./billingLabels";
import "./billing.css";

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`bx-badge bx-badge-${tone}`}>{children}</span>;
}

/** Estado: punto + texto + color (nunca solo color). */
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

type DialogProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
  /** Mientras es true no se puede cerrar con Escape ni clic fuera. */
  busy?: boolean;
  wide?: boolean;
};

/**
 * Diálogo modal accesible: mueve el foco al abrir (primer campo), lo atrapa con Tab, cierra con Escape
 * y devuelve el foco al elemento que lo abrió.
 */
export function Dialog({ title, children, onClose, busy = false, wide = false }: DialogProps) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const busyRef = useRef(busy);
  const closeRef = useRef(onClose);
  useEffect(() => {
    busyRef.current = busy;
    closeRef.current = onClose;
  });

  useEffect(() => {
    opener.current = document.activeElement;
    const root = ref.current;
    const first = root?.querySelector<HTMLElement>("textarea, input, select") ?? root?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? root)?.focus();
    return () => {
      const el = opener.current;
      if (el instanceof HTMLElement && el.isConnected) el.focus();
    };
  }, []);

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!busyRef.current) closeRef.current();
      return;
    }
    if (event.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) { event.preventDefault(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  return (
    <div className="bx-dialog-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div
        ref={ref} className="bx-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        style={wide ? undefined : { width: "min(560px, 100%)" }} onKeyDown={onKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Notice({ tone, children, live = false }: { tone: "ok" | "warning" | "error" | "neutral"; children: ReactNode; live?: boolean }) {
  const cls = tone === "neutral" ? "bx-notice" : `bx-notice bx-notice-${tone}`;
  return <div className={cls} role={tone === "error" ? "alert" : live ? "status" : undefined}>{children}</div>;
}
