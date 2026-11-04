import { useCallback, useEffect, useRef, useState } from "react";
import { label, tryLabel } from "../../i18n/label";
import { CHILE_TZ_NOTE, formatDateTime } from "../billing/billingLabels";
import { Notice } from "../billing/ui";
import { StatusBadge } from "./CancellationStatusBadge";
import { CascadePreviewView, StepResultsView } from "./CascadeView";
import * as api from "./cancellationsApi";
import { describeCancellationError } from "./cancellationErrors";
import { channelText, eventText, manualText, reasonText, stepText, stopModeText } from "./cancellationLabels";
import type { CancellationDetail, CancellationEvent } from "./types";
import "./cancellations.css";

type Props = {
  id: string;
  /** Cambia cada vez que el usuario elige una fila (también la ya abierta): lleva el detalle a la vista y el foco al título. */
  focusToken?: number;
  /** Recarga el detalle cuando cambia este valor (la bandeja lo incrementa tras una acción). */
  reloadToken?: number;
  /** Zona de acciones (aprobar, rechazar, aplicar…). Solo se pinta si el usuario tiene permisos. */
  renderActions?: (detail: CancellationDetail, reload: () => void) => React.ReactNode;
};

/** Notas seguras de un evento: solo valores del catálogo; el texto libre del proveedor nunca llega aquí. */
function eventNotes(event: CancellationEvent): string[] {
  const notes: string[] = [];
  const { step, code, reason } = event.detail;
  if (typeof step === "string" && tryLabel("cancellationStep", step)) notes.push(`Paso: ${stepText(step)}`);
  if (typeof code === "string" && code) {
    const text = tryLabel("cancellationError", code) ?? tryLabel("cancellationManual", code);
    if (text) notes.push(text);
  }
  if (typeof reason === "string" && reason) {
    const text = tryLabel("cancellationError", reason);
    if (text) notes.push(text);
  }
  return notes;
}

function eventComment(event: CancellationEvent): string | null {
  const comment = event.detail.comment;
  return typeof comment === "string" && comment.trim() ? comment : null;
}

export function CancellationDetailView({ id, focusToken = 0, reloadToken = 0, renderActions }: Props) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<{ key: string; detail: CancellationDetail | null; error: string | null }>({ key: "", detail: null, error: null });
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sectionRef = useRef<HTMLElement>(null);

  // Carga derivada de la clave: mientras el resultado guardado no sea el de la clave vigente, se está cargando.
  const requestKey = `${id}|${version}|${reloadToken}`;
  useEffect(() => {
    let alive = true;
    api.fetchCancellation(id).then((detail) => {
      if (alive) setState({ key: requestKey, detail, error: null });
    }).catch((err: unknown) => {
      if (!alive) return;
      const message = describeCancellationError(err, "No se pudo cargar el detalle de la solicitud de baja.").message;
      setState((prev) => ({ key: requestKey, detail: prev.detail, error: message }));
    });
    return () => { alive = false; };
  }, [id, requestKey]);

  const detail = state.detail;
  const loading = state.key !== requestKey;
  const loadError = state.key === requestKey ? state.error : null;
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  const detailId = detail?.id;
  useEffect(() => {
    if (!detailId) return;
    const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    sectionRef.current?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
    headingRef.current?.focus({ preventScroll: true });
  }, [detailId, focusToken]);

  if (loading && !detail) return <section className="bx-detail"><p className="muted-copy" role="status">Cargando detalle…</p></section>;
  if (loadError && !detail) {
    return (
      <section className="bx-detail">
        <Notice tone="error">{loadError}</Notice>
        <button className="bx-btn bx-btn-ghost" onClick={reload}>Reintentar</button>
      </section>
    );
  }
  if (!detail) return null;

  const manualSteps = detail.steps.filter((s) => s.status === "manual");
  const options = detail.options ?? {};
  const awaitingReport = detail.status === "pending_external";
  const reconciliation = detail.status === "requires_reconciliation" || detail.requires_reconciliation;
  const actions = renderActions?.(detail, reload) ?? null;

  return (
    <section className="bx-detail" ref={sectionRef} aria-labelledby={`cx-detail-title-${detail.id}`}>
      <p className="eyebrow">DETALLE DE LA BAJA</p>
      <h2 id={`cx-detail-title-${detail.id}`} ref={headingRef} tabIndex={-1}>
        {channelText(detail.channel)} · <span className="mono">{detail.subscription_external_id}</span>
      </h2>
      {loadError ? <Notice tone="error">{loadError}</Notice> : null}

      <dl className="bx-dl">
        <dt>Estado</dt><dd><StatusBadge status={detail.status} /></dd>
        <dt>Canal</dt><dd>{channelText(detail.channel)}</dd>
        <dt>Motivo</dt><dd>{reasonText(detail.reason_code)}</dd>
        <dt>Solicitante</dt><dd className="mono">{detail.requested_by ?? "—"}</dd>
        <dt>Creada</dt><dd className="mono">{formatDateTime(detail.created_at)}</dd>
        {options.toku_stop_mode ? <><dt>Forma de baja</dt><dd>{stopModeText(options.toku_stop_mode)}{options.toku_end_date ? <> · <span className="mono">{options.toku_end_date}</span></> : null}</dd></> : null}
        {options.confirm_irreversible ? <><dt>Baja irreversible</dt><dd>{label("boolean", true)}, confirmada de forma explícita</dd></> : null}
        <dt>Aprobaciones</dt><dd className="mono">{detail.approvals_count} de {detail.approvals_required}{detail.self_approved ? " · autoaprobada" : ""}</dd>
        {detail.approved_by ? <><dt>Aprobada por</dt><dd className="mono">{detail.approved_by}</dd></> : null}
        {detail.decided_at ? <><dt>Decisión</dt><dd className="mono">{formatDateTime(detail.decided_at)}</dd></> : null}
        {detail.executed_at ? <><dt>Ejecutada</dt><dd className="mono">{formatDateTime(detail.executed_at)}</dd></> : null}
        {detail.expires_at && detail.status === "pending" ? <><dt>Vence</dt><dd className="mono">{formatDateTime(detail.expires_at)}</dd></> : null}
      </dl>

      <h3>Comentario del motivo</h3>
      <p className="bx-comment">{detail.reason_comment}</p>
      {detail.decision_comment ? <><h3>Comentario de la decisión</h3><p className="bx-comment">{detail.decision_comment}</p></> : null}

      {reconciliation ? (
        <Notice tone="error">
          La baja quedó incompleta y requiere conciliación: lo que ya se hizo en el proveedor no se revierte. Revise los pasos y, cuando
          corresponda, un aprobador puede reabrir la solicitud para reanudar desde el paso fallido sin repetir lo hecho.
        </Notice>
      ) : null}
      {detail.status === "failed" ? (
        <Notice tone="error">La baja falló antes de cambiar nada en el proveedor. Un aprobador puede reabrir la solicitud y volver a aplicarla.</Notice>
      ) : null}
      {awaitingReport ? (
        <Notice tone="warning">
          La baja está en trámite: queda registrada en el CRM y se cierra sola cuando el siguiente Excel de TCH traiga la ficha eliminada.
          Mientras tanto la revocación del mandato se hace en el banco.
        </Notice>
      ) : null}
      {manualSteps.length > 0 ? (
        <Notice tone="warning">
          <strong>Pasos manuales pendientes de una persona:</strong>
          <ul>{manualSteps.map((s) => <li key={s.step}><strong>{stepText(s.step)}</strong>: {typeof s.code === "string" ? manualText(s.code) : "Tarea manual."}</li>)}</ul>
        </Notice>
      ) : null}

      {actions}

      <CascadePreviewView preview={detail.cascade_preview} />
      <StepResultsView steps={detail.steps} />

      <p className="bx-hint">{CHILE_TZ_NOTE}</p>
      <h3>Línea de tiempo</h3>
      {detail.events.length === 0 ? <p className="muted-copy">Sin eventos registrados.</p> : (
        <ol className="bx-timeline" aria-label="Línea de tiempo de la solicitud de baja">
          {detail.events.map((event) => {
            const comment = eventComment(event);
            return (
              <li key={event.id}>
                <span><strong>{eventText(event.event_type)}</strong> · <span className="mono bx-ev-actor">{event.actor ?? "sistema"}</span></span>
                <span className="mono bx-ev-time">{formatDateTime(event.created_at)}</span>
                {eventNotes(event).map((note, index) => <span key={index} className="bx-hint">{note}</span>)}
                {comment ? <p className="bx-comment">{comment}</p> : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

