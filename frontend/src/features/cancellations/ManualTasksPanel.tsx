import { useEffect, useRef, useState } from "react";
import { formatClp, formatDateTime } from "../billing/billingLabels";
import { Badge, Cell, Dialog, Notice } from "../billing/ui";
import { channelText } from "./cancellationLabels";
import * as mt from "./manualTasks";

const PAGE_SIZE = 25;
type View = "open" | "closed";
const VIEW_STATUSES: Record<View, mt.ManualTaskStatus[]> = { open: ["pending", "confirmed"], closed: ["verified", "dismissed"] };

type Props = { can: (permission: string) => boolean };
type Pending = { task: mt.ManualTask; kind: "confirm" | "dismiss" } | null;

/**
 * Bandeja de tareas manuales (MGT-11/13/14): medio de pago conservado, mandato TCH y monto de Payku. Quien tiene el
 * permiso de confirmación registra que hizo la acción manual (queda su usuario y la fecha) o la descarta con motivo.
 * Las de TCH y Payku las cierra el sistema al verificarlas (Excel / sincronización).
 */
export function ManualTasksPanel({ can }: Props) {
  const [view, setView] = useState<View>("open");
  const [offset, setOffset] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [result, setResult] = useState<{ key: string; data: mt.ManualTaskList | null; error: string | null }>({ key: "", data: null, error: null });
  const [pending, setPending] = useState<Pending>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);

  const key = `${view}|${offset}|${reloadKey}`;
  useEffect(() => {
    let alive = true;
    mt.fetchManualTasks(VIEW_STATUSES[view], offset, PAGE_SIZE).then((data) => {
      if (alive) setResult({ key, data, error: null });
    }).catch((err: unknown) => {
      if (alive) setResult((prev) => ({ key, data: prev.data, error: mt.taskErrorText(mt.errorCode(err), "No se pudieron cargar las tareas manuales.") }));
    });
    return () => { alive = false; };
  }, [view, offset, key]);

  const loading = result.key !== key;
  const items = result.data?.items ?? [];
  const total = result.data?.total ?? 0;
  const canConfirm = can(mt.PERM_MANUAL_TASKS_CONFIRM);

  async function act() {
    if (!pending || inFlight.current) return;
    if (pending.kind === "dismiss" && !comment.trim()) { setActionError("El comentario es obligatorio."); return; }
    inFlight.current = true;
    setBusy(true);
    setActionError(null);
    try {
      if (pending.kind === "confirm") {
        await mt.confirmManualTask(pending.task.id, comment.trim() || undefined);
        setNotice("Tarea confirmada: quedó registrado su usuario y la fecha.");
      } else {
        await mt.dismissManualTask(pending.task.id, comment.trim());
        setNotice("Tarea descartada.");
      }
      setPending(null);
      setComment("");
      setReloadKey((k) => k + 1);
    } catch (err) {
      setActionError(mt.taskErrorText(mt.errorCode(err), "No se pudo actualizar la tarea."));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function exportTch() {
    setActionError(null);
    try {
      await mt.downloadTchExport();
    } catch (err) {
      setActionError(mt.taskErrorText(mt.errorCode(err), "No se pudo descargar el archivo de bajas TCH."));
    }
  }

  return (
    <section aria-label="Tareas manuales" className="cx-tasks">
      <div className="bx-filters cx-task-toolbar">
        <label>Ver
          <select value={view} onChange={(e) => { setView(e.target.value as View); setOffset(0); }}>
            <option value="open">Abiertas</option>
            <option value="closed">Cerradas</option>
          </select>
        </label>
        {canConfirm ? <button type="button" className="bx-btn bx-btn-ghost" onClick={() => void exportTch()}>Descargar bajas TCH en trámite (CSV)</button> : null}
      </div>
      <p className="bx-hint">El CSV de TCH no incluye números de cuenta ni de tarjeta. Quien revoca el mandato en el banco confirma aquí que lo hizo.</p>
      <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
      {actionError && !pending ? <Notice tone="error">{actionError}</Notice> : null}
      {result.error && !loading ? <Notice tone="error">{result.error}</Notice> : null}
      <p className="bx-sr" role="status" aria-live="polite">{loading ? "Cargando tareas manuales…" : `${total} tareas.`}</p>
      {!loading && items.length === 0 && !result.error ? <div className="bx-notice"><p style={{ margin: 0 }}>No hay tareas manuales {view === "open" ? "abiertas" : "cerradas"}.</p></div> : null}
      {items.length > 0 ? (
        <div className="table-wrap" aria-busy={loading}>
          <table className="bx-table bx-stack" role="table">
            <caption className="bx-sr">Tareas manuales de suscripciones</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th role="columnheader" scope="col">Tarea</th><th role="columnheader" scope="col">Canal</th><th role="columnheader" scope="col">Suscripción</th>
                <th role="columnheader" scope="col">Responsable</th><th role="columnheader" scope="col">Estado</th><th role="columnheader" scope="col">Detalle</th>
                <th role="columnheader" scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {items.map((t) => {
                const actions = mt.taskActions(t, can);
                return (
                  <tr role="row" key={t.id}>
                    <Cell label="Tarea">{mt.taskTypeText(t.task_type)}</Cell>
                    <Cell label="Canal" className="bx-lbl">{channelText(t.channel)}</Cell>
                    <Cell label="Suscripción" className="mono">{t.subscription_external_id}</Cell>
                    <Cell label="Responsable" className="mono">{t.assigned_to ?? "—"}</Cell>
                    <Cell label="Estado"><Badge tone={mt.taskStatusTone(t.status)}>{mt.taskStatusText(t.status)}</Badge></Cell>
                    <Cell label="Detalle">
                      {t.task_type === "payku_amount_change" ? <span className="mono">{formatClp(t.previous_amount)} → {formatClp(t.target_amount)}</span> : mt.taskCodeText(t.code)}
                      {t.confirmed_by ? <div className="bx-hint">Confirmada por <span className="mono">{t.confirmed_by}</span> el <span className="mono">{formatDateTime(t.confirmed_at)}</span></div> : null}
                      {t.verified_at ? <div className="bx-hint">Verificada el <span className="mono">{formatDateTime(t.verified_at)}</span></div> : null}
                    </Cell>
                    <Cell label="Acciones">
                      {actions.confirm ? <button type="button" className="bx-btn bx-btn-primary" onClick={() => { setPending({ task: t, kind: "confirm" }); setComment(""); setActionError(null); }}>Confirmar que lo hice</button> : null}
                      {actions.dismiss ? <button type="button" className="bx-btn bx-btn-ghost" onClick={() => { setPending({ task: t, kind: "dismiss" }); setComment(""); setActionError(null); }}>Descartar</button> : null}
                      {!actions.confirm && !actions.dismiss ? "—" : null}
                    </Cell>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {total > PAGE_SIZE ? (
        <div className="bx-pagination">
          <button className="bx-btn bx-btn-ghost" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</button>
          <span className="mono">{offset + 1}-{Math.min(offset + PAGE_SIZE, total)} de {total}</span>
          <button className="bx-btn bx-btn-ghost" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</button>
        </div>
      ) : null}

      {pending ? (
        <Dialog title={pending.kind === "confirm" ? "Confirmar la acción manual" : "Descartar la tarea"} onClose={() => setPending(null)} busy={busy}>
          <form className="bx-form" noValidate onSubmit={(e) => { e.preventDefault(); void act(); }}>
            <p>{mt.taskTypeText(pending.task.task_type)} · <span className="mono">{pending.task.subscription_external_id}</span></p>
            {pending.kind === "confirm" ? <p className="bx-hint">Al confirmar queda registrado que usted hizo la acción manual, con su usuario y la fecha.</p> : null}
            <label>{pending.kind === "confirm" ? "Comentario (opcional)" : "Motivo (obligatorio)"}
              <textarea value={comment} maxLength={2000} disabled={busy} aria-required={pending.kind === "dismiss"} onChange={(e) => setComment(e.target.value)} />
            </label>
            {actionError ? <Notice tone="error">{actionError}</Notice> : null}
            <div className="bx-dialog-actions">
              <button type="button" className="bx-btn bx-btn-ghost" onClick={() => setPending(null)} disabled={busy}>Cancelar</button>
              <button type="submit" className="bx-btn bx-btn-primary" disabled={busy}>{pending.kind === "confirm" ? "Confirmar" : "Descartar"}</button>
            </div>
          </form>
        </Dialog>
      ) : null}
    </section>
  );
}
