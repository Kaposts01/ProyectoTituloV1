import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
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
  /** Con cambios sin guardar, un clic en el fondo NO cierra el diálogo (Escape y «Cancelar» siguen siendo explícitos). */
  dirty?: boolean;
};

/**
 * Diálogo modal accesible: se monta en un portal fuera de la app, deja `inert` + `aria-hidden` el resto de la página
 * mientras está abierto, mueve el foco al abrir (primer campo), lo atrapa con Tab, cierra con Escape
 * y devuelve el foco al elemento que lo abrió.
 */
export function Dialog({ title, children, onClose, busy = false, wide = false, dirty = false }: DialogProps) {
  const titleId = useId();
  const [host] = useState(() => document.createElement("div"));
  const opener = useRef<Element | null>(null);
  useLayoutEffect(() => {
    opener.current = document.activeElement; // antes de volver inert el resto: el navegador puede quitar el foco
    document.body.appendChild(host);
    const others = Array.from(document.body.children).filter((el) => el !== host && el instanceof HTMLElement) as HTMLElement[];
    const saved = others.map((el) => ({ el, inert: el.hasAttribute("inert"), ariaHidden: el.getAttribute("aria-hidden") }));
    for (const { el } of saved) {
      el.setAttribute("inert", "");
      el.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const { el, inert, ariaHidden } of saved) {
        if (!inert) el.removeAttribute("inert");
        if (ariaHidden === null) el.removeAttribute("aria-hidden");
        else el.setAttribute("aria-hidden", ariaHidden);
      }
      host.remove();
    };
  }, [host]);
  const ref = useRef<HTMLDivElement>(null);
  const busyRef = useRef(busy);
  const closeRef = useRef(onClose);
  useEffect(() => {
    busyRef.current = busy;
    closeRef.current = onClose;
  });

  useEffect(() => {
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

  return createPortal(
    <div className="bx-dialog-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy && !dirty) onClose(); }}>
      <div
        ref={ref} className="bx-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        style={wide ? undefined : { width: "min(560px, 100%)" }} onKeyDown={onKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>,
    host,
  );
}

/** Celda de tabla apilable: `data-label` alimenta la etiqueta visible en tarjetas móviles (CSS) y el rol se fija explícito. */
export function Cell({ label, className, children, title }: { label: string; className?: string; children?: ReactNode; title?: string }) {
  return <td role="cell" data-label={label} className={className} title={title}>{children}</td>;
}

/**
 * Filtros colapsables en móvil. En escritorio el botón no se muestra y el cuerpo queda siempre visible (CSS).
 * Debe renderizarse DENTRO del `<form>`: los botones Buscar/Limpiar viven en el cuerpo.
 */
export function FiltersPanel({ activeCount, children }: { activeCount: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return (
    <>
      <button type="button" className="bx-btn bx-btn-ghost bx-filters-toggle" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((v) => !v)}>
        {activeCount > 0 ? `Filtros (${activeCount})` : "Filtros"}
      </button>
      <div id={bodyId} className={`bx-filters-body${open ? "" : " is-collapsed"}`}>{children}</div>
    </>
  );
}

export function Notice({ tone, children, live = false }: { tone: "ok" | "warning" | "error" | "neutral"; children: ReactNode; live?: boolean }) {
  const cls = tone === "neutral" ? "bx-notice" : `bx-notice bx-notice-${tone}`;
  return <div className={cls} role={tone === "error" ? "alert" : live ? "status" : undefined}>{children}</div>;
}
