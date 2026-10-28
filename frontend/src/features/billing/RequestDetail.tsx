import { useCallback, useEffect, useRef, useState } from "react";
import { describeBillingError, type BillingErrorInfo } from "./billingErrors";
import * as api from "./billingApi";
import {
  approveBlockReason, availableActions, canWithdrawRequest, CHILE_TZ_NOTE, eventComment, eventLabel, eventNotes, eventTechnical, expiryText,
  formatDateTime, PLATFORM_LABELS, requestSummary, technicalCode, typeLabel,
} from "./billingLabels";
import { describeDrift } from "./billingPlan";
import { applyOutcome } from "./billingResult";
import { PlanPreviewView } from "./PlanPreviewView";
import type { ApplyResponse, BillingRequestDetail } from "./types";
import { Dialog, Notice, StatusBadge } from "./ui";

type ActionKind = "approve" | "reject" | "withdraw" | "reopen" | "apply";

const ACTION_COPY: Record<ActionKind, { title: string; confirm: string; busy: string; comment: "none" | "optional" | "required"; help: string; danger?: boolean }> = {
  approve: { title: "Aprobar solicitud", confirm: "Aprobar", busy: "Aprobando…", comment: "optional", help: "Al aprobar, el cambio queda listo para aplicarse en VirtualPOS." },
  reject: { title: "Rechazar solicitud", confirm: "Rechazar", busy: "Rechazando…", comment: "required", help: "Indique el motivo del rechazo; queda registrado en la auditoría.", danger: true },
  withdraw: { title: "Retirar solicitud", confirm: "Retirar", busy: "Retirando…", comment: "optional", help: "La solicitud se cierra sin aplicar ningún cambio.", danger: true },
  reopen: { title: "Reabrir solicitud", confirm: "Reabrir", busy: "Reabriendo…", comment: "required", help: "La solicitud vuelve a «aprobada». No se reintenta automáticamente: después debe aplicarla. Indique qué se revisó o corrigió." },
  apply: { title: "Aplicar cambio en VirtualPOS", confirm: "Aplicar ahora", busy: "Aplicando…", comment: "none", help: "Se recalcula el plan con el estado actual de VirtualPOS y se ejecutan las escrituras cobro por cobro. Esta acción modifica cobros reales." },
};

/** Etiqueta técnica corta del error (p. ej. «RuntimeError»): se muestra tal cual, en mono, sin interpretarla. */
function techLine(value: unknown) {
  const code = technicalCode(value);
  return code ? <p className="bx-tech">Código técnico: <span className="mono">{code}</span></p> : null;
}

type DriftState = { info: NonNullable<BillingErrorInfo["drift"]> };

type Props = {
  id: string;
  can: (permission: string) => boolean;
  /** Usuario actual: «Retirar» solo para el solicitante (o admin) y detecta si ya aprobó. Sin él no se oculta nada. */
  currentUserId?: string;
  isAdmin?: boolean;
  /** Se invoca tras cualquier cambio de estado para que la bandeja se refresque. */
  onChanged: () => void;
};

export function RequestDetail({ id, can, currentUserId, isAdmin = false, onChanged }: Props) {
  const [detail, setDetail] = useState<BillingRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionKind | null>(null);
  const [drift, setDrift] = useState<DriftState | null>(null);
  const [driftAck, setDriftAck] = useState(false);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<BillingErrorInfo | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "warning"; text: string } | null>(null);
  const inFlight = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setDetail(await api.fetchRequest(id));
    } catch (err) {
      setLoadError(describeBillingError(err, "No se pudo cargar el detalle de la solicitud.").message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);
  const detailId = detail?.id;
  useEffect(() => { if (detailId) headingRef.current?.focus(); }, [detailId]);

  function openAction(kind: ActionKind) {
    setAction(kind);
    setComment("");
    setCommentError(null);
    setDialogError(null);
    setDrift(null);
    setDriftAck(false);
    setNotice(null);
  }
  function closeDialog() {
    if (inFlight.current) return;
    setAction(null);
    setDrift(null);
    setDialogError(null);
  }

  async function submit() {
    if (!action || inFlight.current || !detail) return;
    const copy = ACTION_COPY[action];
    const text = comment.trim();
    if (copy.comment === "required" && !text) {
      setCommentError("El comentario es obligatorio.");
      return;
    }
    if (action === "apply" && drift && !driftAck) return;
    inFlight.current = true;
    setBusy(true);
    setDialogError(null);
    setCommentError(null);
    try {
      let message: string;
      let tone: "ok" | "warning" = "ok";
      if (action === "approve") {
        const updated = await api.approveRequest(detail.id, text || undefined);
        message = updated.status === "aprobada" ? "Solicitud aprobada. Ya puede aplicarse." : `Aprobación registrada (${updated.approvals_count} de ${updated.approvals_required}). Falta otro aprobador.`;
      } else if (action === "reject") {
        await api.rejectRequest(detail.id, text);
        message = "Solicitud rechazada.";
      } else if (action === "withdraw") {
        await api.withdrawRequest(detail.id, text || undefined);
        message = "Solicitud retirada.";
      } else if (action === "reopen") {
        await api.reopenRequest(detail.id, text);
        message = "Solicitud reabierta como aprobada. Aplíquela cuando esté lista.";
      } else {
        const result: ApplyResponse = await api.applyRequest(detail.id, Boolean(drift));
        ({ message, tone } = applyOutcome(result));
      }
      setAction(null);
      setDrift(null);
      setNotice({ tone, text: message });
      onChanged();
      await load();
      headingRef.current?.focus();
    } catch (err) {
      const info = describeBillingError(err, "No se pudo completar la acción. Reintente.");
      if (info.drift) {
        setDrift({ info: info.drift });
        setDriftAck(false);
      } else {
        // Sin respuesta definitiva (red, 5xx sin código): la operación pudo haberse aplicado; no se ofrece «reintentar» a ciegas.
        const uncertain = (info.status === null || info.status >= 500) && !info.code;
        setDialogError(uncertain ? { ...info, message: "No se pudo confirmar el resultado de la operación. Revise el estado de la solicitud antes de reintentar: puede haberse aplicado." } : info);
        if (action === "apply" || action === "reopen" || info.status === 409 || info.status === 502 || info.status === 503 || info.code === "request_not_found") {
          onChanged();
          void load();
        }
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  if (loading && !detail) return <section className="bx-detail"><p className="muted-copy" role="status">Cargando detalle…</p></section>;
  if (loadError && !detail) {
    return (
      <section className="bx-detail">
        <Notice tone="error">{loadError}</Notice>
        <button className="bx-btn bx-btn-ghost" onClick={() => void load()}>Reintentar</button>
      </section>
    );
  }
  if (!detail) return null;

  const actions = availableActions(detail, can);
  actions.withdraw = actions.withdraw && canWithdrawRequest(detail, currentUserId, isAdmin);
  const approveBlock = actions.approve ? approveBlockReason(detail, currentUserId) : null;
  const expiry = expiryText(detail);
  const copy = action ? ACTION_COPY[action] : null;
  const driftLines = drift ? describeDrift(drift.info.diff) : [];

  return (
    <section className="bx-detail" aria-labelledby={`bx-detail-title-${detail.id}`}>
      <p className="eyebrow">DETALLE DE SOLICITUD</p>
      <h2 id={`bx-detail-title-${detail.id}`} ref={headingRef} tabIndex={-1}>
        {typeLabel(detail.request_type)} · <span className="mono">{detail.subscription_external_id}</span>
      </h2>
      <div aria-live="polite">{notice ? <Notice tone={notice.tone} live>{notice.text}</Notice> : null}</div>
      {loadError ? <Notice tone="error">{loadError}</Notice> : null}

      <dl className="bx-dl">
        <dt>Estado</dt><dd><StatusBadge status={detail.status} />{expiry ? <> <span className="mono">{expiry}</span></> : null}</dd>
        <dt>Plataforma</dt><dd>{PLATFORM_LABELS[detail.platform] ?? detail.platform}</dd>
        <dt>Cambio solicitado</dt><dd className="mono">{requestSummary(detail)}</dd>
        {detail.request_type === "renew_calendar" || detail.horizon_months ? <><dt>Horizonte</dt><dd className="mono">{detail.horizon_months ?? "—"} meses{detail.horizon_start_month ? ` desde ${detail.horizon_start_month}` : ""}</dd></> : null}
        <dt>Solicitante</dt><dd>{detail.requested_by ?? "—"}</dd>
        <dt>Creada</dt><dd className="mono">{formatDateTime(detail.created_at)}</dd>
        <dt>Aprobaciones</dt><dd className="mono">{detail.approvals_count} de {detail.approvals_required}{detail.approvals_required > 1 ? " (doble aprobación)" : ""}{detail.self_approved ? " · autoaprobada" : ""}</dd>
        {detail.approved_by ? <><dt>Aprobada por</dt><dd>{detail.approved_by}</dd></> : null}
        {detail.decided_at ? <><dt>Decisión</dt><dd className="mono">{formatDateTime(detail.decided_at)}</dd></> : null}
        {detail.executed_at ? <><dt>Ejecutada</dt><dd className="mono">{formatDateTime(detail.executed_at)}</dd></> : null}
        {detail.expires_at && detail.status === "pendiente" ? <><dt>Vence</dt><dd className="mono">{formatDateTime(detail.expires_at)}</dd></> : null}
      </dl>

      {detail.requester_comment ? <><h3>Comentario del solicitante</h3><p className="bx-comment">{detail.requester_comment}</p></> : null}
      {detail.decision_comment ? <><h3>Comentario de la decisión</h3><p className="bx-comment">{detail.decision_comment}</p></> : null}
      {detail.status === "fallida" ? <Notice tone="error">La aplicación falló. Los cobros creados se compensaron y el calendario original quedó intacto. Un aprobador puede reabrir la solicitud.{techLine(detail.error_message)}</Notice> : null}
      {detail.status === "requiere_conciliacion" ? <Notice tone="error">La aplicación quedó incompleta y requiere conciliación manual antes de reabrir la solicitud.{techLine(detail.error_message)}</Notice> : null}

      {actions.approve || actions.reject || actions.withdraw || actions.reopen || actions.apply ? (
        <div className="bx-actions" role="group" aria-label="Acciones de la solicitud">
          {actions.approve ? <button className="bx-btn bx-btn-primary" disabled={Boolean(approveBlock)} aria-describedby={approveBlock ? "bx-approve-block" : undefined} onClick={() => openAction("approve")}>Aprobar</button> : null}
          {actions.apply ? <button className="bx-btn bx-btn-primary" onClick={() => openAction("apply")}>Aplicar</button> : null}
          {actions.reject ? <button className="bx-btn bx-btn-danger" onClick={() => openAction("reject")}>Rechazar</button> : null}
          {actions.withdraw ? <button className="bx-btn bx-btn-ghost" onClick={() => openAction("withdraw")}>Retirar</button> : null}
          {actions.reopen ? <button className="bx-btn bx-btn-ghost" onClick={() => openAction("reopen")}>Reabrir</button> : null}
        </div>
      ) : null}

      {approveBlock ? <p id="bx-approve-block" className="bx-hint">{approveBlock}</p> : null}

      <PlanPreviewView plan={detail.plan_preview} />

      <p className="bx-hint">{CHILE_TZ_NOTE}</p>
      <h3>Línea de tiempo</h3>
      {detail.events.length === 0 ? <p className="muted-copy">Sin eventos registrados.</p> : (
        <ol className="bx-timeline" aria-label="Línea de tiempo de la solicitud">
          {detail.events.map((e) => {
            const text = eventComment(e.detail);
            return (
              <li key={e.id}>
                <span><strong>{eventLabel(e.event_type)}</strong> · {e.actor ?? "sistema"}</span>
                <span className="mono">{formatDateTime(e.created_at)}</span>
                {eventNotes(e.event_type, e.detail).map((n, i) => <span key={i} className="bx-hint">{n}</span>)}
                {eventTechnical(e.detail).map((t) => <span key={t.label} className="bx-hint">{t.label}: <span className="mono">{t.code}</span></span>)}
                {text ? <p className="bx-comment">{text}</p> : null}
              </li>
            );
          })}
        </ol>
      )}

      {action && copy ? (
        <Dialog title={drift ? "El plan cambió desde la aprobación" : copy.title} onClose={closeDialog} busy={busy} wide={Boolean(drift)}>
          {drift ? (
            <>
              <Notice tone="warning">
                El estado en VirtualPOS cambió desde la aprobación y el plan recalculado difiere del aprobado. No se escribió nada todavía.
              </Notice>
              <h3>Diferencias</h3>
              {driftLines.length > 0
                ? <ul>{driftLines.map((l, i) => <li key={i}>{l}</li>)}</ul>
                : <p className="muted-copy">El detalle de diferencias no está disponible; revise el nuevo plan.</p>}
              <PlanPreviewView plan={drift.info.newPreview} title="Nuevo plan recalculado" />
              <label className="bx-check">
                <input type="checkbox" checked={driftAck} disabled={busy} onChange={(e) => setDriftAck(e.target.checked)} />
                Entiendo que el plan difiere del aprobado y acepto aplicar el nuevo plan.
              </label>
            </>
          ) : (
            <>
              <p>{copy.help}</p>
              {copy.comment !== "none" ? (
                <label className="bx-form" style={{ display: "grid", gap: 5 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>
                    Comentario{copy.comment === "required" ? " (obligatorio)" : " (opcional)"}
                  </span>
                  <textarea
                    value={comment} maxLength={2000} disabled={busy} aria-required={copy.comment === "required"}
                    aria-invalid={commentError ? true : undefined} aria-describedby={commentError ? "bx-comment-error" : undefined}
                    onChange={(e) => { setComment(e.target.value); setCommentError(null); }}
                  />
                  {commentError ? <span id="bx-comment-error" className="bx-field-error" role="alert">{commentError}</span> : null}
                </label>
              ) : null}
            </>
          )}
          {dialogError ? (
            <Notice tone="error">
              {dialogError.message}
              {dialogError.planErrors?.length ? <ul>{dialogError.planErrors.map((e, i) => <li key={i}>{e.message}</li>)}</ul> : null}
            </Notice>
          ) : null}
          <div className="bx-dialog-actions">
            <button className="bx-btn bx-btn-ghost" onClick={closeDialog} disabled={busy}>Cancelar</button>
            <button
              className={`bx-btn ${copy.danger ? "bx-btn-danger" : "bx-btn-primary"}`} onClick={() => void submit()}
              disabled={busy || (Boolean(drift) && !driftAck)}
            >
              {busy ? copy.busy : drift ? "Aceptar cambios y aplicar" : copy.confirm}
            </button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
