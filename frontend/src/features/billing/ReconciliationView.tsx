import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./billingApi";
import { findingCharges, findingLabel, KIND_LABELS, severityTone, sortFindings } from "./billingConsistency";
import { describeBillingError } from "./billingErrors";
import { formatDateTime, platformLabel } from "./billingLabels";
import { PERM_APPROVE, type ConsistencyReport, type ManagedResolution, type ReconciliationItem, type ReconciliationQueue } from "./types";
import { Badge, Cell, Dialog, Notice } from "./ui";

type Props = {
  can: (permission: string) => boolean;
  onViewRequest: (requestId: string) => void;
};

/**
 * Sección «Conciliación» (BILL-10): cola de reconciliación (GB-CS-09) y controles de consistencia GB-CS-02..14.
 * Todo es de solo lectura salvo «Resolver», que solo registra lo verificado a mano en VirtualPOS (no escribe en el proveedor).
 */
export function ReconciliationView({ can, onViewRequest }: Props) {
  const [queue, setQueue] = useState<ReconciliationQueue | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [report, setReport] = useState<ConsistencyReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [resolving, setResolving] = useState<ReconciliationItem | null>(null);
  const [resolution, setResolution] = useState<ManagedResolution>("vigente");
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const seq = useRef(0);
  const canResolve = can(PERM_APPROVE);

  const loadQueue = useCallback(async () => {
    const mine = ++seq.current;
    setQueueError(null);
    try {
      const result = await api.fetchReconciliationQueue();
      if (mine === seq.current) setQueue(result);
    } catch (err) {
      if (mine === seq.current) setQueueError(describeBillingError(err, "No se pudo cargar la cola de conciliación.").message);
    }
  }, []);

  useEffect(() => { void loadQueue(); }, [loadQueue]);

  async function runChecks() {
    setChecking(true);
    setReportError(null);
    try {
      setReport(await api.fetchConsistency());
    } catch (err) {
      setReportError(describeBillingError(err, "No se pudieron ejecutar los controles de consistencia.").message);
    } finally {
      setChecking(false);
    }
  }

  function openResolve(item: ReconciliationItem) {
    setNotice(null);
    setResolving(item);
    setResolution("vigente");
    setComment("");
    setCommentError(null);
    setResolveError(null);
  }

  async function submitResolve() {
    if (!resolving) return;
    if (!comment.trim()) {
      setCommentError("El comentario es obligatorio.");
      return;
    }
    setBusy(true);
    setResolveError(null);
    try {
      await api.resolveManagedCharge(resolving.id, resolution, comment.trim());
      setResolving(null);
      setNotice("Cobro conciliado. La resolución quedó registrada en el historial de la solicitud.");
      await loadQueue();
    } catch (err) {
      setResolveError(describeBillingError(err, "No se pudo registrar la resolución.").message);
    } finally {
      setBusy(false);
    }
  }

  const items = queue?.items ?? [];
  const findings = report ? sortFindings(report.findings) : [];

  return (
    <section aria-labelledby="bx-recon-title">
      <h2 id="bx-recon-title" className="bx-section-title">Cola de conciliación</h2>
      <p className="muted-copy">
        Cada elemento bloquea su suscripción para nuevos cambios. Verifique el estado en VirtualPOS antes de resolver; el CRM no
        repone ni cancela cobros por su cuenta.
      </p>
      <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
      {queueError ? (
        <Notice tone="error">
          {queueError}{" "}
          <button className="bx-btn bx-btn-ghost" onClick={() => void loadQueue()}>Reintentar</button>
        </Notice>
      ) : null}
      {!queue && !queueError ? <p className="muted-copy">Cargando cola de conciliación…</p> : null}
      {queue && items.length === 0 ? <div className="bx-notice"><p style={{ margin: 0 }}>No hay nada pendiente de conciliación.</p></div> : null}
      {queue && queue.stale > 0 ? (
        <Notice tone="warning">
          {queue.stale === 1 ? "1 elemento lleva" : `${queue.stale} elementos llevan`} más de 24 horas en conciliación (criterio de abort del piloto).
        </Notice>
      ) : null}
      {items.length > 0 ? (
        <div className="table-wrap">
          <table className="bx-table bx-stack" role="table">
            <caption className="bx-sr">Elementos en conciliación</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th role="columnheader" scope="col">Suscripción</th><th role="columnheader" scope="col">Tipo</th>
                <th role="columnheader" scope="col">Cobro</th><th role="columnheader" scope="col">Desde</th><th role="columnheader" scope="col">Acción</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {items.map((item) => (
                <tr role="row" key={`${item.kind}-${item.id}`}>
                  <Cell label="Suscripción" className="bx-c-sub">
                    <span className="mono">{item.subscription_external_id}</span>
                    <div className="mono bx-platform">{platformLabel(item.platform)}</div>
                  </Cell>
                  <Cell label="Tipo">
                    {KIND_LABELS[item.kind] ?? item.kind}
                    {item.stale ? <div className="bx-sub"><Badge tone="error">Más de 24 h</Badge></div> : null}
                  </Cell>
                  <Cell label="Cobro" className="mono">{item.charge_id ? `${item.charge_id}${item.month ? ` · ${item.month}` : ""}` : "—"}</Cell>
                  <Cell label="Desde" className="mono bx-lbl">{formatDateTime(item.since)}</Cell>
                  <Cell label="Acción">
                    <div className="bx-row-actions">
                      {item.request_id ? (
                        <button className="bx-btn bx-btn-ghost" onClick={() => onViewRequest(item.request_id as string)}
                          aria-label={`Ver solicitud de la suscripción ${item.subscription_external_id}`}>Ver solicitud</button>
                      ) : null}
                      {item.kind === "managed_charge" && canResolve ? (
                        <button className="bx-btn bx-btn-primary" onClick={() => openResolve(item)}
                          aria-label={`Resolver el cobro ${item.charge_id ?? ""} de la suscripción ${item.subscription_external_id}`}>Resolver</button>
                      ) : null}
                    </div>
                  </Cell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <h2 className="bx-section-title">Controles de consistencia</h2>
      <p className="muted-copy">
        Revisan los cobros de las suscripciones gestionadas con los datos de la última sincronización (GB-CS-02 a GB-CS-14).
        Son de solo lectura: no cambian nada.
      </p>
      <button className="bx-btn bx-btn-ghost" onClick={() => void runChecks()} disabled={checking}>
        {checking ? "Revisando…" : report ? "Volver a revisar" : "Ejecutar controles"}
      </button>
      {reportError ? <Notice tone="error">{reportError}</Notice> : null}
      <p className="bx-sr" role="status" aria-live="polite">
        {checking ? "Ejecutando controles…" : report ? `${report.findings.length} hallazgos en ${report.subscriptions_checked} suscripciones.` : ""}
      </p>
      {report && report.ok ? (
        <Notice tone="ok">Sin hallazgos en {report.subscriptions_checked} suscripciones gestionadas.</Notice>
      ) : null}
      {findings.length > 0 ? (
        <div className="table-wrap">
          <table className="bx-table bx-stack" role="table">
            <caption className="bx-sr">Hallazgos de los controles de consistencia</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th role="columnheader" scope="col">Severidad</th><th role="columnheader" scope="col">Hallazgo</th>
                <th role="columnheader" scope="col">Suscripción</th><th role="columnheader" scope="col">Mes</th><th role="columnheader" scope="col">Cobros</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {findings.map((f, i) => (
                <tr role="row" key={`${f.code}-${f.platform}-${f.subscription_external_id}-${f.month ?? ""}-${i}`}>
                  <Cell label="Severidad"><Badge tone={severityTone(f.severity)}>{f.severity}</Badge></Cell>
                  <Cell label="Hallazgo">
                    {findingLabel(f.code)}
                    <div className="bx-sub mono">{f.scenario}{f.blocks ? " · bloquea" : ""}</div>
                  </Cell>
                  <Cell label="Suscripción" className="mono">{f.subscription_external_id}</Cell>
                  <Cell label="Mes" className="mono">{f.month ?? "—"}</Cell>
                  <Cell label="Cobros" className="mono">{findingCharges(f) || "—"}</Cell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {resolving ? (
        <Dialog title="Resolver cobro en conciliación" onClose={() => setResolving(null)} busy={busy} dirty={Boolean(comment.trim())}>
          <p>
            Cobro <span className="mono">{resolving.charge_id}</span> de la suscripción <span className="mono">{resolving.subscription_external_id}</span>.
            Indique lo que verificó en VirtualPOS. No se escribe nada en VirtualPOS.
          </p>
          <fieldset className="bx-form" style={{ display: "grid", gap: 5, border: 0, padding: 0 }}>
            <legend style={{ fontSize: 12, fontWeight: 600 }}>Estado verificado</legend>
            <label><input type="radio" name="bx-resolution" checked={resolution === "vigente"} disabled={busy} onChange={() => setResolution("vigente")} /> Vigente: el cobro existe y debe quedar</label>
            <label><input type="radio" name="bx-resolution" checked={resolution === "cancelado"} disabled={busy} onChange={() => setResolution("cancelado")} /> Cancelado: ya no existe en VirtualPOS</label>
          </fieldset>
          <label className="bx-form" style={{ display: "grid", gap: 5 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Comentario (obligatorio)</span>
            <textarea
              value={comment} maxLength={2000} disabled={busy} aria-required
              aria-invalid={commentError ? true : undefined} aria-describedby={commentError ? "bx-resolve-error" : undefined}
              onChange={(e) => { setComment(e.target.value); setCommentError(null); }}
            />
            {commentError ? <span id="bx-resolve-error" className="bx-field-error" role="alert">{commentError}</span> : null}
          </label>
          {resolveError ? <Notice tone="error">{resolveError}</Notice> : null}
          <div className="bx-dialog-actions">
            <button className="bx-btn bx-btn-ghost" onClick={() => setResolving(null)} disabled={busy}>Cancelar</button>
            <button className="bx-btn bx-btn-primary" onClick={() => void submitResolve()} disabled={busy}>{busy ? "Guardando…" : "Registrar resolución"}</button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
