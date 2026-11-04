import { useRef, useState } from "react";
import { Dialog, Notice } from "../billing/ui";
import { ApplyPlanView } from "./CascadeView";
import * as api from "./cancellationsApi";
import { describeCancellationError, type CancellationErrorInfo } from "./cancellationErrors";
import { availableActions, canWithdraw, codeText, stepText } from "./cancellationLabels";
import { applyOutcomeNotice, canConfirmApply, type NoticeState } from "./cancellationOutcome";
import { PERM_CANCELLATION_APPROVE, PERM_CANCELLATION_REQUEST, type ApplyResponse, type CancellationDetail } from "./types";
import "./cancellations.css";

type ActionKind = "approve" | "reject" | "withdraw" | "reopen" | "apply";

type CommentRule = "none" | "optional" | "required";
const ACTION_COPY: Record<ActionKind, { title: string; confirm: string; busy: string; comment: CommentRule; help: string; danger?: boolean }> = {
  approve: { title: "Aprobar baja", confirm: "Aprobar", busy: "Aprobando…", comment: "optional", help: "Al aprobar, la baja queda lista para aplicarse. Todavía no se cambia nada en el proveedor." },
  reject: { title: "Rechazar baja", confirm: "Rechazar", busy: "Rechazando…", comment: "required", help: "Indique el motivo del rechazo; queda registrado en la auditoría.", danger: true },
  withdraw: { title: "Retirar solicitud de baja", confirm: "Retirar", busy: "Retirando…", comment: "optional", help: "La solicitud se cierra sin aplicar ningún cambio.", danger: true },
  reopen: { title: "Reabrir solicitud de baja", confirm: "Reabrir", busy: "Reabriendo…", comment: "required", help: "La solicitud vuelve a «aprobada» y conserva los pasos ya hechos. Al aplicarla se reanuda desde el paso fallido sin repetir lo hecho. Indique qué se revisó o corrigió." },
  apply: { title: "Aplicar baja", confirm: "Confirmar y aplicar", busy: "Aplicando…", comment: "none", help: "Primero simule la baja: no escribe nada y muestra qué pasos se harían y si algo la bloquea. Después podrá confirmarla." },
};

type Props = {
  detail: CancellationDetail;
  can: (permission: string) => boolean;
  currentUserId?: string;
  isAdmin?: boolean;
  /** Recarga el detalle abierto. */
  reload: () => void;
  /** Avisa a la bandeja para que se refresque tras cualquier cambio de estado. */
  onChanged: () => void;
};

/** Acciones de una solicitud según su estado y los permisos del usuario. El servidor decide en último término. */
export function CancellationActions({ detail, can, currentUserId, isAdmin = false, reload, onChanged }: Props) {
  const [action, setAction] = useState<ActionKind | null>(null);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"simulate" | "submit" | null>(null);
  const [dialogError, setDialogError] = useState<CancellationErrorInfo | null>(null);
  const [simulation, setSimulation] = useState<ApplyResponse | null>(null);
  const [ack, setAck] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const inFlight = useRef(false);

  const actions = availableActions(detail, can, { request: PERM_CANCELLATION_REQUEST, approve: PERM_CANCELLATION_APPROVE });
  actions.withdraw = actions.withdraw && canWithdraw(detail, currentUserId, isAdmin);
  const any = Object.values(actions).some(Boolean);

  function openAction(kind: ActionKind) {
    setAction(kind);
    setComment("");
    setCommentError(null);
    setDialogError(null);
    setSimulation(null);
    setAck(false);
    setNotice(null);
  }
  function closeDialog() {
    if (inFlight.current) return;
    setAction(null);
    setDialogError(null);
    setSimulation(null);
  }
  function focusHeading() {
    document.getElementById(`cx-detail-title-${detail.id}`)?.focus();
  }

  async function simulate() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy("simulate");
    setDialogError(null);
    setSimulation(null);
    setAck(false);
    try {
      setSimulation(await api.applyCancellation(detail.id, true));
    } catch (err) {
      setDialogError(describeCancellationError(err, "No se pudo simular la baja."));
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function submit() {
    if (!action || inFlight.current) return;
    const copy = ACTION_COPY[action];
    const text = comment.trim();
    if (copy.comment === "required" && !text) {
      setCommentError("El comentario es obligatorio.");
      return;
    }
    if (action === "apply" && (!simulation || !canConfirmApply(simulation, ack))) return;
    inFlight.current = true;
    setBusy("submit");
    setDialogError(null);
    setCommentError(null);
    try {
      let result: NoticeState;
      if (action === "approve") {
        const updated = await api.approveCancellation(detail.id, text || undefined);
        result = { tone: "ok", text: updated.status === "approved" ? "Baja aprobada. Ya puede aplicarse." : `Aprobación registrada (${updated.approvals_count} de ${updated.approvals_required}). Falta otro aprobador.` };
      } else if (action === "reject") {
        await api.rejectCancellation(detail.id, text);
        result = { tone: "ok", text: "Solicitud de baja rechazada." };
      } else if (action === "withdraw") {
        await api.withdrawCancellation(detail.id, text || undefined);
        result = { tone: "ok", text: "Solicitud de baja retirada." };
      } else if (action === "reopen") {
        await api.reopenCancellation(detail.id, text);
        result = { tone: "ok", text: "Solicitud reabierta como aprobada. Aplíquela cuando esté lista." };
      } else {
        result = applyOutcomeNotice(await api.applyCancellation(detail.id, false));
      }
      setAction(null);
      setSimulation(null);
      setNotice(result);
      onChanged();
      reload();
      focusHeading();
    } catch (err) {
      const info = describeCancellationError(err, "No se pudo completar la acción. Reintente.");
      // Sin respuesta definitiva (red, 5xx sin código): la operación pudo haberse aplicado; no se ofrece reintentar a ciegas.
      const uncertain = (info.status === null || info.status >= 500) && !info.code;
      setDialogError(uncertain ? { ...info, message: "No se pudo confirmar el resultado de la operación. Revise el estado de la solicitud antes de reintentar: puede haberse aplicado." } : info);
      if (action === "apply" || action === "reopen" || info.status === 409 || info.status === 502 || info.status === 503 || info.code === "request_not_found") {
        onChanged();
        reload();
      }
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  const copy = action ? ACTION_COPY[action] : null;
  const applying = action === "apply";
  const confirmDisabled = busy !== null || (applying && (!simulation || !canConfirmApply(simulation, ack)));

  return (
    <>
      <div aria-live="polite">{notice ? <Notice tone={notice.tone} live>{notice.text}</Notice> : null}</div>
      {any ? (
        <div className="bx-actions" role="group" aria-label="Acciones de la solicitud de baja">
          {actions.approve ? <button className="bx-btn bx-btn-primary" onClick={() => openAction("approve")}>Aprobar</button> : null}
          {actions.apply ? <button className="bx-btn bx-btn-primary" onClick={() => openAction("apply")}>Aplicar</button> : null}
          {actions.reject ? <button className="bx-btn bx-btn-danger" onClick={() => openAction("reject")}>Rechazar</button> : null}
          {actions.withdraw ? <button className="bx-btn bx-btn-ghost" onClick={() => openAction("withdraw")}>Retirar</button> : null}
          {actions.reopen ? <button className="bx-btn bx-btn-ghost" onClick={() => openAction("reopen")}>Reabrir</button> : null}
        </div>
      ) : null}

      {action && copy ? (
        <Dialog title={copy.title} onClose={closeDialog} busy={busy !== null} wide={applying}>
          <p>{copy.help}</p>
          {copy.comment !== "none" ? (
            <label className="bx-form" style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>Comentario{copy.comment === "required" ? " (obligatorio)" : " (opcional)"}</span>
              <textarea
                value={comment} maxLength={2000} disabled={busy !== null} aria-required={copy.comment === "required"}
                aria-invalid={commentError ? true : undefined} aria-describedby={commentError ? "cx-comment-error" : undefined}
                onChange={(e) => { setComment(e.target.value); setCommentError(null); }}
              />
              {commentError ? <span id="cx-comment-error" className="bx-field-error" role="alert">{commentError}</span> : null}
            </label>
          ) : null}
          {applying ? (
            <>
              <div className="bx-actions">
                <button type="button" className="bx-btn bx-btn-ghost" disabled={busy !== null} onClick={() => void simulate()}>
                  {busy === "simulate" ? "Simulando…" : simulation ? "Simular de nuevo" : "Simular baja"}
                </button>
              </div>
              {simulation?.plan ? (
                <>
                  <ApplyPlanView plan={simulation.plan} />
                  {simulation.plan.irreversible ? (
                    <label className="bx-check">
                      <input type="checkbox" checked={ack} disabled={busy !== null} onChange={(e) => setAck(e.target.checked)} />
                      Entiendo que esta baja no se puede revertir en el proveedor.
                    </label>
                  ) : null}
                  {simulation.plan.steps_to_run.length > 0 ? null : <p className="bx-hint">No quedan pasos automáticos por hacer.</p>}
                </>
              ) : simulation ? <Notice tone="neutral">La simulación no devolvió un plan. Reintente.</Notice> : <p className="bx-hint">Debe simular antes de confirmar.</p>}
            </>
          ) : null}
          {dialogError ? (
            <Notice tone="error">
              {dialogError.message}
              {dialogError.step ? <> Paso: <strong>{stepText(dialogError.step)}</strong>{dialogError.stepCode ? <>. {codeText(dialogError.stepCode)}</> : null}</> : null}
            </Notice>
          ) : null}
          <div className="bx-dialog-actions">
            <button className="bx-btn bx-btn-ghost" onClick={closeDialog} disabled={busy !== null}>Cancelar</button>
            <button className={`bx-btn ${copy.danger ? "bx-btn-danger" : "bx-btn-primary"}`} onClick={() => void submit()} disabled={confirmDisabled}>
              {busy === "submit" ? copy.busy : copy.confirm}
            </button>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}
