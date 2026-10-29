import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { getBlob, getJson, saveBlob } from "../../api";
import type { ExportEntity, ExportParams } from "./exportMapping";
import { EXPORT_VOLUME_WARNING_ROWS, exportErrorMessage } from "./exportSupport";

type Scope = "view" | "all";
type CountResponse = { entity: string; rows: number; canales: string[]; include_pii: boolean };
type Phase =
  | { kind: "idle" }
  | { kind: "menu" }
  | { kind: "counting"; scope: Scope }
  | { kind: "confirm"; scope: Scope; total: number; includePii: boolean }
  | { kind: "downloading"; scope: Scope; total: number }
  | { kind: "done"; filename: string; total: number };

const ENTITY_LABEL: Record<ExportEntity, string> = {
  clientes: "clientes",
  suscripciones: "suscripciones",
  cobros: "cobros",
  pagos: "pagos",
};

const fmt = (n: number) => n.toLocaleString("es-CL");

/**
 * Botón «Exportar» de una lista de datos (CSV). Ofrece «Esta vista» (la página mostrada, con filtros) y
 * «Todo el listado» (sin paginación, con los filtros activos). Antes de descargar consulta `/count`,
 * muestra «N filas» y, si el volumen es muy grande, un aviso dentro de la página. El backend decide si
 * el archivo lleva datos personales (permiso `export.pii`) y audita la descarga.
 */
export function ExportButton({
  entity,
  canal,
  params,
  window: viewWindow,
  ignoredFilters = [],
  notes = [],
  canPii,
  label = "Exportar",
}: {
  entity: ExportEntity;
  canal?: string;
  /** Filtros y búsqueda activos, con los nombres exactos del contrato. */
  params: ExportParams;
  /** Página visible: `offset` y `limit` (1 a 1000) de «Esta vista». */
  window: { offset: number; limit: number };
  /** Filtros activos que el contrato no puede aplicar; se avisan antes de confirmar. */
  ignoredFilters?: string[];
  /** Aclaraciones propias de la vista (p. ej. que el archivo lista un registro por canal). */
  notes?: string[];
  /** Si el front conoce el permiso `export.pii` del usuario; el backend decide igualmente. */
  canPii?: boolean;
  label?: string;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const uid = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busy = phase.kind === "counting" || phase.kind === "downloading";
  const open = phase.kind === "menu" || phase.kind === "confirm" || phase.kind === "counting";

  const buildQuery = useCallback(
    (scope: Scope, withCount: boolean) => {
      const qs = new URLSearchParams(params);
      if (canal) qs.set("canal", canal);
      if (!withCount) {
        if (scope === "all") qs.set("all", "true");
        else {
          qs.set("offset", String(viewWindow.offset));
          qs.set("limit", String(Math.min(1000, Math.max(1, viewWindow.limit))));
        }
      }
      return qs.toString();
    },
    [params, canal, viewWindow.offset, viewWindow.limit],
  );

  useEffect(() => () => abortRef.current?.abort(), []);

  // Cierra con Escape y al hacer clic fuera (sin interrumpir una descarga en curso).
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!busy && rootRef.current && !rootRef.current.contains(event.target as Node)) setPhase({ kind: "idle" });
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open, busy]);

  useEffect(() => {
    if (phase.kind === "confirm") confirmRef.current?.focus();
  }, [phase.kind]);

  function close() {
    abortRef.current?.abort();
    setPhase({ kind: "idle" });
    triggerRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      close();
      return;
    }
    if (phase.kind !== "menu" || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    const items = Array.from(rootRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
    items[next].focus();
  }

  function toggleMenu() {
    if (busy) return;
    setError(null);
    setPhase(open ? { kind: "idle" } : { kind: "menu" });
  }

  useEffect(() => {
    if (phase.kind === "menu") rootRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [phase.kind]);

  async function choose(scope: Scope) {
    setError(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase({ kind: "counting", scope });
    try {
      const count = await getJson<CountResponse>(`/api/v1/export/${entity}/count?${buildQuery(scope, true)}`, controller.signal);
      if (controller.signal.aborted) return;
      const total = scope === "all" ? count.rows : Math.max(0, Math.min(viewWindow.limit, 1000, count.rows - viewWindow.offset));
      setPhase({ kind: "confirm", scope, total, includePii: Boolean(count.include_pii) });
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(exportErrorMessage(err));
      setPhase({ kind: "menu" });
    }
  }

  async function download(scope: Scope, total: number) {
    setError(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase({ kind: "downloading", scope, total });
    try {
      const { blob, filename } = await getBlob(`/api/v1/export/${entity}?${buildQuery(scope, false)}`, controller.signal);
      if (controller.signal.aborted) return;
      const name = filename ?? `${entity}${canal ? `-${canal}` : ""}.csv`;
      saveBlob(blob, name);
      setPhase({ kind: "done", filename: name, total });
      triggerRef.current?.focus();
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(exportErrorMessage(err));
      setPhase({ kind: "idle" });
      triggerRef.current?.focus();
    }
  }

  const panelId = `${uid}-panel`;
  const piiHint =
    canPii === undefined
      ? "El backend decide si el archivo incluye datos personales según tu rol."
      : canPii
        ? "Tu rol puede exportar con datos personales (RUT, nombre, contacto)."
        : "Tu rol exporta sin datos personales (RUT, nombre, contacto).";

  return (
    <div className="export-button" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className="export-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-busy={busy}
        disabled={phase.kind === "downloading"}
        onClick={toggleMenu}
      >
        <span aria-hidden="true">{phase.kind === "downloading" ? "…" : "↓"}</span>{" "}
        {phase.kind === "downloading" ? "Exportando…" : label}
      </button>
      <span className="export-status" role="status" aria-live="polite">
        {phase.kind === "done" ? `Descargado ${phase.filename} (${fmt(phase.total)} filas).` : ""}
        {phase.kind === "downloading" ? `Preparando el archivo de ${ENTITY_LABEL[entity]}…` : ""}
      </span>
      {error && !open ? <p className="export-error" role="alert">{error}</p> : null}
      {open ? (
        <div className="export-panel" id={panelId}>
          {phase.kind === "menu" || phase.kind === "counting" ? (
            <div role="menu" aria-label={`Exportar ${ENTITY_LABEL[entity]} a CSV`}>
              <button
                type="button"
                role="menuitem"
                className="export-item"
                disabled={phase.kind === "counting"}
                onClick={() => void choose("view")}
              >
                Esta vista (con filtros)
              </button>
              <button
                type="button"
                role="menuitem"
                className="export-item"
                disabled={phase.kind === "counting"}
                onClick={() => void choose("all")}
              >
                Todo el listado (con los filtros activos, sin paginación)
              </button>
            </div>
          ) : null}
          {phase.kind === "counting" ? <p className="export-note" role="status">Contando filas…</p> : null}
          {error ? <p className="export-error" role="alert">{error}</p> : null}
          {phase.kind === "menu" || phase.kind === "counting" ? <p className="export-note">{piiHint}</p> : null}
          {phase.kind === "confirm" ? (
            <div role="group" aria-label="Confirmar exportación">
              <p className="export-count">
                <strong className="mono">{fmt(phase.total)} filas</strong>{" "}
                {phase.scope === "all" ? "en todo el listado" : "en esta vista"} · CSV
              </p>
              <p className="export-note" role="status">
                {phase.includePii
                  ? "El archivo incluirá datos personales (RUT, nombre y contacto). Trátalo con cuidado."
                  : "El archivo no incluirá datos personales."}
              </p>
              {phase.scope === "all" && phase.total > EXPORT_VOLUME_WARNING_ROWS ? (
                <p className="export-warning" role="alert">
                  Es un archivo muy grande ({fmt(phase.total)} filas): la descarga puede tardar varios minutos y pesar cientos
                  de megas; Excel no abre más de 1.048.576 filas. Considera acotar con filtros.
                </p>
              ) : null}
              {ignoredFilters.length ? (
                <p className="export-warning" role="alert">
                  No se pueden aplicar a la exportación: {ignoredFilters.join("; ")}. El archivo saldrá sin esos filtros.
                </p>
              ) : null}
              {notes.map((note) => <p className="export-note" key={note}>{note}</p>)}
              {phase.total === 0 ? <p className="export-note">No hay filas para exportar con estos filtros.</p> : null}
              <div className="export-actions">
                <button
                  ref={confirmRef}
                  type="button"
                  className="export-confirm"
                  disabled={phase.total === 0}
                  onClick={() => void download(phase.scope, phase.total)}
                >
                  {phase.scope === "all" && phase.total > EXPORT_VOLUME_WARNING_ROWS ? "Descargar de todos modos" : "Descargar CSV"}
                </button>
                <button type="button" className="export-cancel" onClick={close}>Cancelar</button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
