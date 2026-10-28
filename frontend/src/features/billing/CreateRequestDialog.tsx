import { useRef, useState } from "react";
import * as api from "./billingApi";
import { describeBillingError, type BillingErrorInfo } from "./billingErrors";
import { EMPTY_FORM, validateChangeForm, type ChangeFormValues, type FormErrors } from "./billingForm";
import { formatClp, PLATFORM_LABELS, REQUEST_TYPES, TYPE_LABELS } from "./billingLabels";
import { PlanPreviewView } from "./PlanPreviewView";
import type { BillingRequestDetail, Platform, PreviewResponse, RequestType } from "./types";
import { Dialog, Notice } from "./ui";

/** Datos de una tarea de renovación: tipo, plataforma y suscripción quedan fijos (solo lectura). */
export type RenewalPrefill = { platform: Platform; subscription: string; scheduledAmount: number | null };

type Props = {
  prefill?: RenewalPrefill;
  onClose: () => void;
  onCreated: (created: BillingRequestDetail) => void;
};

/**
 * Formulario de nueva solicitud. Primero se calcula la vista previa (POST /changes/preview, sin guardar nada);
 * solo con una vista previa vigente se habilita «Enviar solicitud». Editar cualquier campo la invalida.
 */
export function CreateRequestDialog({ prefill, onClose, onCreated }: Props) {
  const [values, setValues] = useState<ChangeFormValues>(() => (prefill
    ? { ...EMPTY_FORM, requestType: "renew_calendar", platform: prefill.platform, subscription: prefill.subscription }
    : EMPTY_FORM));
  const [errors, setErrors] = useState<FormErrors>({});
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "submit" | null>(null);
  const [apiError, setApiError] = useState<BillingErrorInfo | null>(null);
  const inFlight = useRef(false);

  function setField<K extends keyof ChangeFormValues>(key: K, value: ChangeFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    setPreview(null);
    setApiError(null);
  }

  async function runPreview() {
    if (inFlight.current) return;
    const { errors: found, body } = validateChangeForm(values);
    setErrors(found);
    if (!body) return;
    inFlight.current = true;
    setBusy("preview");
    setApiError(null);
    setPreview(null);
    try {
      setPreview(await api.previewChange(body));
    } catch (err) {
      setApiError(describeBillingError(err, "No se pudo calcular la vista previa."));
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function send() {
    if (inFlight.current || !preview) return;
    const { body } = validateChangeForm(values);
    if (!body) return;
    inFlight.current = true;
    setBusy("submit");
    setApiError(null);
    try {
      const created = await api.createChange(body);
      onCreated(created);
    } catch (err) {
      setApiError(describeBillingError(err, "No se pudo enviar la solicitud."));
      setPreview(null);
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  const disabled = busy !== null;
  const type = values.requestType;
  const needsAmount = type === "change_amount" || type === "one_off_charge";
  const errProps = (key: keyof FormErrors) => (errors[key] ? { "aria-invalid": true as const, "aria-describedby": `bx-err-${key}` } : {});
  const errMsg = (key: keyof FormErrors) => (errors[key] ? <span id={`bx-err-${key}`} className="bx-field-error" role="alert">{errors[key]}</span> : null);

  const locked = Boolean(prefill);
  return (
    <Dialog title={locked ? "Solicitar renovación de calendario" : "Nueva solicitud de cambio de cobro"} onClose={onClose} busy={disabled} wide>
      <form className="bx-form" noValidate onSubmit={(e) => { e.preventDefault(); void runPreview(); }}>
        <div className="bx-form-grid">
          {locked ? (
            <>
              <label>Tipo de cambio
                <input value={TYPE_LABELS[type]} readOnly />
              </label>
              <label>Plataforma
                <input value={PLATFORM_LABELS[values.platform] ?? values.platform} readOnly />
              </label>
            </>
          ) : (
            <>
          <label>Tipo de cambio
            <select value={type} disabled={disabled} onChange={(e) => setField("requestType", e.target.value as RequestType)}>
              {REQUEST_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
            </select>
          </label>
          <label>Plataforma
            <select value={values.platform} disabled={disabled} onChange={(e) => setField("platform", e.target.value as Platform)}>
              {Object.entries(PLATFORM_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
            </>
          )}
          <div className="wide">
            <label>ID de suscripción
            <input className="mono" value={values.subscription} disabled={disabled} readOnly={locked} maxLength={255} autoComplete="off" {...errProps("subscription")} onChange={(e) => setField("subscription", e.target.value)} />
            </label>
            {errMsg("subscription")}
          </div>
          {needsAmount ? (
            <div>
              <label>Monto (CLP)
              <input className="mono" inputMode="numeric" value={values.amount} disabled={disabled} {...errProps("amount")} onChange={(e) => setField("amount", e.target.value)} />
              </label>
              {errMsg("amount")}
            </div>
          ) : null}
          {type === "change_date" ? (
            <div>
              <label>Nuevo día de cobro (1-31)
              <input className="mono" inputMode="numeric" value={values.chargeDay} disabled={disabled} {...errProps("chargeDay")} onChange={(e) => setField("chargeDay", e.target.value)} />
              </label>
              {errMsg("chargeDay")}
            </div>
          ) : null}
          {type === "one_off_charge" ? (
            <>
              <div>
                <label>Fecha del cobro
                <input className="mono" type="date" value={values.chargeDate} disabled={disabled} {...errProps("chargeDate")} onChange={(e) => setField("chargeDate", e.target.value)} />
                </label>
                {errMsg("chargeDate")}
              </div>
              <div>
                <label>Referencia de tarea (opcional)
                <input className="mono" value={values.taskRef} disabled={disabled} maxLength={100} {...errProps("taskRef")} onChange={(e) => setField("taskRef", e.target.value)} />
                </label>
                {errMsg("taskRef")}
              </div>
            </>
          ) : null}
          {type === "renew_calendar" ? <p className="bx-hint wide">Se recalcula el calendario de cobros del horizonte vigente con el monto actual de la suscripción.</p> : null}
          {prefill ? (
            <p className="bx-hint wide">Último monto programado: <span className="mono">{formatClp(prefill.scheduledAmount)}</span> (referencia; no se envía, la renovación usa el monto actual de la suscripción).</p>
          ) : null}
          <div className="wide">
            <label>Comentario (opcional)
            <textarea value={values.comment} disabled={disabled} maxLength={2000} {...errProps("comment")} onChange={(e) => setField("comment", e.target.value)} />
            </label>
            {errMsg("comment")}
          </div>
        </div>

        {apiError ? (
          <Notice tone="error">
            {apiError.message}
            {apiError.planErrors?.length ? <ul>{apiError.planErrors.map((e, i) => <li key={i}>{e.message}</li>)}</ul> : null}
          </Notice>
        ) : null}

        <div aria-live="polite">
          {busy === "preview" ? <p className="muted-copy" role="status">Calculando vista previa…</p> : null}
          {preview ? (
            <div>
              <Notice tone={preview.would_self_approve ? "warning" : "neutral"} live>
                {preview.would_self_approve
                  ? "Al enviar, esta solicitud se autoaprobará (queda registrada en la auditoría) y luego podrá aplicarse."
                  : "Al enviar, la solicitud quedará pendiente de aprobación por otro usuario."}
                {preview.approvals_required > 1 ? " Requiere doble aprobación." : ""}
                {" "}Vence a los <span className="mono">{preview.expires_in_days}</span> días.
              </Notice>
              {preview.open_request ? <Notice tone="warning">Ya existe una solicitud abierta para esta suscripción (estado: {preview.open_request.status}); el envío será rechazado.</Notice> : null}
              <PlanPreviewView plan={preview.plan_preview} />
            </div>
          ) : null}
        </div>

        <div className="bx-dialog-actions">
          <button type="button" className="bx-btn bx-btn-ghost" onClick={onClose} disabled={disabled}>Cancelar</button>
          <button type="submit" className="bx-btn bx-btn-ghost" disabled={disabled}>{busy === "preview" ? "Calculando…" : preview ? "Recalcular vista previa" : "Calcular vista previa"}</button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => void send()} disabled={disabled || !preview}>
            {busy === "submit" ? "Enviando…" : "Enviar solicitud"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
