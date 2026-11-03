import { useRef, useState } from "react";
import { formatClp, formatPct } from "../billing/billingLabels";
import { Dialog, Notice } from "../billing/ui";
import { channelText } from "./cancellationLabels";
import * as mt from "./manualTasks";

type AmountChannel = "virtualpos1" | "virtualpos2" | "toku" | "payku" | "tch";
const CHANNELS: AmountChannel[] = ["virtualpos1", "virtualpos2", "toku", "payku", "tch"];

type Props = {
  onClose: () => void;
  /** Aviso para la bandeja tras registrar el cambio (Toku: solicitud en Cambios de cobro; Payku: tarea manual). */
  onDone: (message: string) => void;
};

/**
 * «Cambiar monto» por canal (MGT-15). VirtualPOS sigue en «Cambios de cobro» (Opción A). Toku crea una solicitud en esa
 * misma bandeja con sus aprobadores (MGT-12; vista previa obligatoria). Payku no tiene API: registra una tarea manual
 * que la sincronización cierra al ver el monto nuevo (MGT-14). TCH no admite el cambio desde el CRM.
 */
export function ChangeAmountDialog({ onClose, onDone }: Props) {
  const [channel, setChannel] = useState<AmountChannel>("toku");
  const [subscription, setSubscription] = useState("");
  const [amountText, setAmountText] = useState("");
  const [comment, setComment] = useState("");
  const [preview, setPreview] = useState<mt.TokuAmountPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const amount = mt.parseAmount(amountText);
  const formReady = subscription.trim() !== "" && amount !== null;
  const reset = () => { setPreview(null); setError(null); };

  async function run(action: () => Promise<void>, fallback: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(mt.taskErrorText(mt.errorCode(err), fallback));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const runPreview = () => run(async () => {
    if (!formReady) return;
    setPreview(await mt.previewTokuAmount(subscription.trim(), amount!));
  }, "No se pudo calcular la vista previa del cambio de monto.");

  const submit = () => run(async () => {
    if (!formReady) return;
    if (channel === "toku") {
      const created = await mt.createTokuAmount(subscription.trim(), amount!, comment.trim() || undefined);
      onDone(created.status === "aprobada"
        ? "Cambio de monto de Toku creado y autoaprobado en «Cambios de cobro». Ya puede aplicarse."
        : "Cambio de monto de Toku creado en «Cambios de cobro», pendiente de aprobación.");
    } else {
      await mt.createPaykuAmountTask(subscription.trim(), amount!, comment.trim() || undefined);
      onDone("Tarea manual registrada: cambie el monto en el portal de Payku y confírmelo; la sincronización la cerrará.");
    }
  }, "No se pudo registrar el cambio de monto.");

  const summary = preview?.summary ?? null;
  const toku = preview?.plan_preview?.toku;
  const supported = channel === "toku" || channel === "payku";

  return (
    <Dialog title="Cambiar monto" onClose={onClose} busy={busy} dirty={subscription !== "" || amountText !== ""}>
      <form className="bx-form" noValidate onSubmit={(e) => { e.preventDefault(); if (channel === "toku") void runPreview(); else void submit(); }}>
        <div className="bx-form-grid">
          <label>Canal
            <select value={channel} disabled={busy} onChange={(e) => { setChannel(e.target.value as AmountChannel); reset(); }}>
              {CHANNELS.map((c) => <option key={c} value={c}>{channelText(c)}</option>)}
            </select>
          </label>
          {channel === "virtualpos1" || channel === "virtualpos2" ? (
            <div className="wide"><Notice tone="neutral">En VirtualPOS el monto se cambia en «Cambios de cobro» (Operación), con su vista previa del calendario de cobros.</Notice></div>
          ) : null}
          {channel === "tch" ? (
            <div className="wide"><Notice tone="neutral">TCH no permite cambiar el monto desde el CRM: se gestiona con el banco y se refleja en el siguiente Excel.</Notice></div>
          ) : null}
          {supported ? (
            <>
              <label>ID de la suscripción
                <input className="mono" value={subscription} maxLength={255} autoComplete="off" aria-required="true" disabled={busy}
                  onChange={(e) => { setSubscription(e.target.value); reset(); }} />
              </label>
              <label>Monto nuevo (CLP)
                <input className="mono" inputMode="numeric" value={amountText} maxLength={14} aria-required="true" disabled={busy}
                  aria-invalid={amountText !== "" && amount === null}
                  onChange={(e) => { setAmountText(e.target.value); reset(); }} />
              </label>
              <div className="wide">
                <label>Comentario (opcional)
                  <textarea value={comment} maxLength={2000} disabled={busy} onChange={(e) => setComment(e.target.value)} />
                </label>
              </div>
              {channel === "payku" ? (
                <div className="wide"><Notice tone="neutral">Payku no tiene API para cambiar el monto: se registra una tarea manual. Cambie el monto en el portal de Payku y confírmelo en «Tareas manuales»; la sincronización la cierra al ver el monto nuevo.</Notice></div>
              ) : null}
            </>
          ) : null}
        </div>

        {channel === "toku" && summary ? (
          <div className="cx-confirm-box" aria-live="polite">
            <p>Monto vigente: <span className="mono">{formatClp(summary.previous_amount)}</span> → nuevo: <span className="mono">{formatClp(summary.new_amount)}</span> (variación <span className="mono">{formatPct(summary.variation_pct)}</span>).</p>
            {toku ? <p>Cuotas impagas que se actualizarán: <span className="mono">{toku.invoices_to_update}</span>.</p> : null}
            {toku && toku.invoices_in_progress_skipped > 0
              ? <Notice tone="warning">Hay {toku.invoices_in_progress_skipped} cuota(s) en proceso de cobro: no se modifican y se cobrarán con el monto anterior.</Notice>
              : null}
            {preview?.would_self_approve
              ? <Notice tone="ok">Al enviar, la solicitud quedará autoaprobada (la política lo permite).</Notice>
              : <Notice tone="neutral">Quedará pendiente de aprobación en «Cambios de cobro».</Notice>}
          </div>
        ) : null}
        {error ? <Notice tone="error">{error}</Notice> : null}

        <div className="bx-dialog-actions">
          <button type="button" className="bx-btn bx-btn-ghost" onClick={onClose} disabled={busy}>Cancelar</button>
          {channel === "toku" ? (
            <>
              <button type="submit" className="bx-btn bx-btn-ghost" disabled={busy || !formReady}>Ver vista previa</button>
              <button type="button" className="bx-btn bx-btn-primary" disabled={busy || !preview} onClick={() => void submit()}>Enviar solicitud</button>
            </>
          ) : null}
          {channel === "payku" ? (
            <button type="submit" className="bx-btn bx-btn-primary" disabled={busy || !formReady}>Registrar tarea manual</button>
          ) : null}
        </div>
      </form>
    </Dialog>
  );
}
