import { useRef, useState } from "react";
import { label } from "../../i18n/label";
import { Dialog, Notice } from "../billing/ui";
import { CascadePreviewView } from "./CascadeView";
import * as api from "./cancellationsApi";
import { describeCancellationError, type CancellationErrorInfo } from "./cancellationErrors";
import {
  EMPTY_CANCELLATION_FORM, REASON_CODES, validateCancellationForm, type CancellationFormErrors, type CancellationFormValues,
} from "./cancellationForm";
import { channelText, reasonText, statusText, stopModeText } from "./cancellationLabels";
import { CHANNELS } from "./cancellationsQuery";
import { searchSubscriptions, type SearchField, type SubscriptionOption } from "./subscriptionSearch";
import type { CancellationChannel, CancellationDetail, CancellationReason, PreviewResponse, TokuStopMode } from "./types";
import "./cancellations.css";

type Props = {
  onClose: () => void;
  onCreated: (created: CancellationDetail) => void;
  /** Abre la solicitud abierta que ya existe para esa suscripción (cierra el diálogo). */
  onOpenExisting: (id: string) => void;
};

/**
 * Formulario de «Solicitar baja». Primero se calcula la vista previa (POST /preview, no guarda nada); solo con una
 * vista previa vigente se habilita «Enviar solicitud». Editar cualquier campo la invalida.
 */
export function RequestCancellationDialog({ onClose, onCreated, onOpenExisting }: Props) {
  const [values, setValues] = useState<CancellationFormValues>(EMPTY_CANCELLATION_FORM);
  const [errors, setErrors] = useState<CancellationFormErrors>({});
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "submit" | null>(null);
  const [apiError, setApiError] = useState<CancellationErrorInfo | null>(null);
  const [searchField, setSearchField] = useState<SearchField>("id");
  const [searchText, setSearchText] = useState("");
  const [options, setOptions] = useState<SubscriptionOption[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const inFlight = useRef(false);

  function setField<K extends keyof CancellationFormValues>(key: K, value: CancellationFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    setPreview(null);
    setApiError(null);
  }

  function changeChannel(channel: CancellationChannel) {
    setValues((current) => ({ ...current, channel, subscription: "", confirmIrreversible: false }));
    setOptions(null);
    setSearchError(null);
    setPreview(null);
    setApiError(null);
  }

  async function runSearch() {
    if (!searchText.trim() || searching) return;
    setSearching(true);
    setSearchError(null);
    try {
      setOptions(await searchSubscriptions(values.channel, searchField, searchText));
    } catch {
      setOptions(null);
      setSearchError("No se pudo buscar suscripciones. Puede escribir el identificador directamente.");
    } finally {
      setSearching(false);
    }
  }

  async function runPreview() {
    if (inFlight.current) return;
    const { errors: found, body } = validateCancellationForm(values);
    setErrors(found);
    if (!body) return;
    inFlight.current = true;
    setBusy("preview");
    setApiError(null);
    setPreview(null);
    try {
      setPreview(await api.previewCancellation(body));
    } catch (err) {
      setApiError(describeCancellationError(err, "No se pudo calcular la vista previa."));
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function send() {
    if (inFlight.current || !preview || preview.open_request) return;
    const { body } = validateCancellationForm(values);
    if (!body) return;
    inFlight.current = true;
    setBusy("submit");
    setApiError(null);
    try {
      onCreated(await api.createCancellation(body));
    } catch (err) {
      setApiError(describeCancellationError(err, "No se pudo enviar la solicitud de baja."));
      setPreview(null);
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  const disabled = busy !== null;
  const dirty = JSON.stringify(values) !== JSON.stringify(EMPTY_CANCELLATION_FORM);
  const errProps = (key: keyof CancellationFormErrors) => (errors[key] ? { "aria-invalid": true as const, "aria-describedby": `cx-err-${key}` } : {});
  const errMsg = (key: keyof CancellationFormErrors) => (errors[key] ? <span id={`cx-err-${key}`} className="bx-field-error" role="alert">{errors[key]}</span> : null);
  const blockers = preview?.cascade_preview.blockers ?? [];

  return (
    <Dialog title="Solicitar baja de suscripción" onClose={onClose} busy={disabled} dirty={dirty} wide>
      <form className="bx-form" noValidate onSubmit={(e) => { e.preventDefault(); void runPreview(); }}>
        <div className="bx-form-grid">
          <label>Canal
            <select value={values.channel} disabled={disabled} onChange={(e) => changeChannel(e.target.value as CancellationChannel)}>
              {CHANNELS.map((c) => <option key={c} value={c}>{channelText(c)}</option>)}
            </select>
          </label>
          <div>
            <label>Motivo de la baja
              <select value={values.reasonCode} disabled={disabled} aria-required="true" {...errProps("reasonCode")} onChange={(e) => setField("reasonCode", e.target.value as CancellationReason | "")}>
                <option value="">Elija un motivo…</option>
                {REASON_CODES.map((r) => <option key={r} value={r}>{reasonText(r)}</option>)}
              </select>
            </label>
            {errMsg("reasonCode")}
          </div>

          <fieldset className="bx-group wide">
            <legend>Suscripción</legend>
            <div className="bx-form-grid">
              <div className="wide">
                <label>{values.channel === "tch" ? "Número de ficha" : "ID de la suscripción"}
                  <input className="mono" value={values.subscription} disabled={disabled} maxLength={255} autoComplete="off" aria-required="true"
                    {...errProps("subscription")} onChange={(e) => setField("subscription", e.target.value)} />
                </label>
                {errMsg("subscription")}
              </div>
              <label>Buscar por
                <select value={searchField} disabled={disabled} onChange={(e) => { setSearchField(e.target.value as SearchField); setOptions(null); }}>
                  <option value="id">{values.channel === "tch" ? "Número de ficha" : "ID de la suscripción"}</option>
                  <option value="rut">RUT del cliente</option>
                </select>
              </label>
              <label>Texto a buscar
                <input className="mono" value={searchText} disabled={disabled} maxLength={100} autoComplete="off"
                  onChange={(e) => setSearchText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void runSearch(); } }} />
              </label>
              <div className="wide">
                <button type="button" className="bx-btn bx-btn-ghost" disabled={disabled || searching || !searchText.trim()} onClick={() => void runSearch()}>
                  {searching ? "Buscando…" : "Buscar suscripciones"}
                </button>
              </div>
              <div className="wide" aria-live="polite">
                {searchError ? <Notice tone="warning">{searchError}</Notice> : null}
                {options && options.length === 0 ? <p className="bx-hint">No se encontraron suscripciones activas con ese texto en este canal.</p> : null}
                {options && options.length > 0 ? (
                  <ul className="cx-search-results" aria-label="Resultados de la búsqueda">
                    {options.map((option) => (
                      <li key={option.id}>
                        <button type="button" disabled={disabled} onClick={() => { setField("subscription", option.id); setErrors((e) => ({ ...e, subscription: undefined })); }}>
                          <span className="mono">{option.id}</span>
                          {option.status ? <> · {label("status", option.status)}</> : null}
                          {option.clientName ? <> · {option.clientName}</> : null}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </fieldset>

          {values.channel === "toku" ? (
            <>
              <label>Forma de baja en Toku
                <select value={values.tokuStopMode} disabled={disabled} onChange={(e) => setField("tokuStopMode", e.target.value as TokuStopMode)}>
                  <option value="paused">{stopModeText("paused")}</option>
                  <option value="end_date">{stopModeText("end_date")}</option>
                </select>
              </label>
              {values.tokuStopMode === "end_date" ? (
                <div>
                  <label>Fecha de término
                    <input className="mono" type="date" value={values.tokuEndDate} disabled={disabled} {...errProps("tokuEndDate")} onChange={(e) => setField("tokuEndDate", e.target.value)} />
                  </label>
                  {errMsg("tokuEndDate")}
                </div>
              ) : null}
            </>
          ) : null}

          {values.channel === "payku" ? (
            <div className="wide">
              <label className="bx-check">
                <input type="checkbox" checked={values.confirmIrreversible} disabled={disabled} aria-required="true" {...errProps("confirmIrreversible")}
                  onChange={(e) => setField("confirmIrreversible", e.target.checked)} />
                Entiendo que la baja en Payku es irreversible y la confirmo de forma explícita.
              </label>
              {errMsg("confirmIrreversible")}
            </div>
          ) : null}

          <div className="wide">
            <label>Comentario del motivo (obligatorio)
              <textarea value={values.comment} maxLength={2000} disabled={disabled} aria-required="true" {...errProps("comment")} onChange={(e) => setField("comment", e.target.value)} />
            </label>
            {errMsg("comment")}
          </div>
        </div>

        {preview ? (
          <div className="cx-confirm-box">
            <CascadePreviewView preview={preview.cascade_preview} />
            {preview.open_request ? (
              <Notice tone="warning">
                Ya existe una solicitud de baja abierta para esta suscripción (estado: {statusText(preview.open_request.status)}); no se puede crear otra.{" "}
                <button type="button" className="bx-btn bx-btn-ghost" onClick={() => onOpenExisting(preview.open_request!.id)}>Ver la solicitud abierta</button>
              </Notice>
            ) : null}
            {blockers.length > 0 ? <Notice tone="warning">Mientras ese bloqueo siga, la baja se negará al aplicarla.</Notice> : null}
            {preview.would_self_approve
              ? <Notice tone="ok">Al enviar, la solicitud quedará autoaprobada y lista para aplicarse (la política lo permite).</Notice>
              : <Notice tone="neutral">Quedará pendiente de aprobación ({preview.approvals_required} {preview.approvals_required === 1 ? "aprobación requerida" : "aprobaciones requeridas"}) y vence en {preview.expires_in_days} días.</Notice>}
          </div>
        ) : null}
        {apiError ? (
          <Notice tone="error">
            {apiError.message}
            {apiError.openRequestId ? <>{" "}<button type="button" className="bx-btn bx-btn-ghost" onClick={() => onOpenExisting(apiError.openRequestId!)}>Ver la solicitud abierta</button></> : null}
          </Notice>
        ) : null}

        <div className="bx-dialog-actions">
          <button type="button" className="bx-btn bx-btn-ghost" onClick={onClose} disabled={disabled}>Cancelar</button>
          <button type="submit" className="bx-btn bx-btn-ghost" disabled={disabled}>{busy === "preview" ? "Calculando…" : "Ver vista previa"}</button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => void send()} disabled={disabled || !preview || Boolean(preview.open_request)}>
            {busy === "submit" ? "Enviando…" : "Enviar solicitud"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
