import { label } from "../../i18n/label";
import { formatDateTime } from "../billing/billingLabels";
import { Badge, Notice } from "../billing/ui";
import { actionText, codeText, manualText, stepStatusText, stepText, stepTone, stopModeText } from "./cancellationLabels";
import type { ApplyPlan, CascadePreview, PreviewStep, StepResult } from "./types";
import "./cancellations.css";

const SAFE_TECH_RE = /^[A-Za-z0-9_]{1,60}$/;

/** Cantidades que algunos pasos guardan al terminar; el texto lo fija el catálogo de la pantalla, no el servidor. */
const STEP_COUNTS: Array<{ key: string; text: string }> = [
  { key: "voided", text: "Facturas anuladas" },
  { key: "closed_requests", text: "Solicitudes de cambio de cobro cerradas" },
  { key: "pending", text: "Cobros pendientes que quedaron" },
  { key: "processing", text: "Cobros en procesamiento que quedaron" },
];

function countOf(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value < 1_000_000 ? value : null;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Texto de lo que hace un paso previsto: la acción del catálogo y, si es de cobros, cuántos. */
function previewStepDetail(step: PreviewStep): string {
  const action = actionText(step.action);
  const count = countOf(step.count);
  if (step.step === "cancel_pending_charges" && count !== null) return `${action}: ${plural(count, "cobro pendiente", "cobros pendientes")}.`;
  return action;
}

/** Vista previa de la cascada: qué se cancelará (suscripción, cobros pendientes, medio de pago) y qué queda manual. */
export function CascadePreviewView({ preview, title = "Vista previa de la cascada" }: { preview: CascadePreview | null | undefined; title?: string }) {
  const steps = preview?.steps ?? [];
  if (!preview || steps.length === 0) return <div><h3>{title}</h3><p className="muted-copy">Sin vista previa disponible.</p></div>;
  const blockers = (preview.blockers ?? []).filter((b): b is string => typeof b === "string");
  const pending = countOf(preview.pending_charges);
  const processing = countOf(preview.processing_charges);
  const inProgress = countOf(preview.in_progress_invoices);
  return (
    <div className="cx-cascade">
      <h3>{title}</h3>
      {blockers.length > 0 ? (
        <Notice tone="error">
          La baja se negaría por este motivo:
          <ul>{blockers.map((code) => <li key={code}>{codeText(code)}</li>)}</ul>
        </Notice>
      ) : null}
      {preview.irreversible ? <Notice tone="warning">Esta baja no se puede revertir en el proveedor una vez aplicada.</Notice> : null}
      <dl className="bx-totals" aria-label="Situación actual de la suscripción">
        {preview.subscription_status ? <div><dt>Estado actual</dt><dd>{label("status", preview.subscription_status)}</dd></div> : null}
        {pending !== null ? <div><dt>Cobros pendientes</dt><dd className="mono">{pending}</dd></div> : null}
        {processing !== null && processing > 0 ? <div><dt>Cobros en procesamiento</dt><dd className="mono">{processing}</dd></div> : null}
        {inProgress !== null && inProgress > 0 ? <div><dt>Facturas en proceso de cobro</dt><dd className="mono">{inProgress}</dd></div> : null}
      </dl>
      <ol className="cx-steps" aria-label="Pasos de la cascada">
        {steps.map((step, index) => {
          const manual = step.action === "manual_task";
          return (
            <li key={step.step} className="cx-step">
              <span className="cx-step-head">
                <strong><span className="mono">{index + 1}.</span> {stepText(step.step)}</strong>
                {manual ? <Badge tone="warning">Paso manual</Badge> : <Badge tone="neutral">Automático</Badge>}
              </span>
              {manual
                ? <span className="cx-step-detail">{step.reason ? manualText(step.reason) : actionText(step.action)}</span>
                : <span className="cx-step-detail">{previewStepDetail(step)}</span>}
            </li>
          );
        })}
      </ol>
      <p className="bx-hint">Calculada con la última sincronización local. Al aplicar, el sistema vuelve a leer el proveedor antes de actuar.</p>
    </div>
  );
}

function stepNotes(step: StepResult): string[] {
  const notes: string[] = [];
  for (const { key, text } of STEP_COUNTS) {
    const value = countOf(step[key]);
    if (value !== null) notes.push(`${text}: ${value}`);
  }
  if (step.mode === "paused" || step.mode === "end_date") {
    const end = typeof step.end_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(step.end_date) ? ` (${step.end_date})` : "";
    notes.push(`${stopModeText(step.mode)}${end}`);
  }
  if (step.irreversible === true) notes.push("Acción irreversible en el proveedor.");
  if (step.remote_cancelled === true || step.remote_stopped === true || step.remote_deleted === true) {
    notes.push("El proveedor ya hizo el cambio.");
  }
  return notes;
}

/** Resultado por paso de lo ya ejecutado. Los pasos manuales van rotulados y con su instrucción. */
export function StepResultsView({ steps, title = "Resultado por paso" }: { steps: StepResult[]; title?: string }) {
  if (steps.length === 0) return null;
  return (
    <div className="cx-results">
      <h3>{title}</h3>
      <ol className="cx-steps" aria-label="Resultado de cada paso">
        {steps.map((step) => {
          const manual = step.status === "manual";
          const failed = step.status === "failed";
          const code = typeof step.code === "string" && step.code ? step.code : null;
          const tech = typeof step.error === "string" && SAFE_TECH_RE.test(step.error) ? step.error : null;
          return (
            <li key={step.step} className="cx-step" data-status={step.status}>
              <span className="cx-step-head">
                <strong>{stepText(step.step)}</strong>
                <Badge tone={stepTone(step.status)}>{stepStatusText(step.status)}</Badge>
                {manual ? <Badge tone="warning">Paso manual</Badge> : null}
              </span>
              {manual && code ? <span className="cx-step-detail">{manualText(code)}</span> : null}
              {manual && typeof step.task === "string" ? <span className="cx-step-detail cx-task">Tarea: {manualText(step.task)}</span> : null}
              {!manual && code ? <span className={`cx-step-detail${failed ? " cx-failed" : ""}`}>{codeText(code)}</span> : null}
              {stepNotes(step).map((note) => <span key={note} className="cx-step-detail">{note}</span>)}
              {tech ? <span className="bx-hint" data-raw-text>Código técnico: <span className="mono">{tech}</span></span> : null}
              {step.at ? <span className="mono bx-ev-time">{formatDateTime(step.at)}</span> : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Resultado de la simulación (`dry_run`): pasos por hacer, ya hechos, bloqueos y facturas por anular. Nada se escribió. */
export function ApplyPlanView({ plan }: { plan: ApplyPlan }) {
  const toRun = plan.steps_to_run ?? [];
  const done = plan.steps_done ?? [];
  const blockers = plan.blockers ?? [];
  const toVoid = countOf(plan.invoices_to_void);
  return (
    <div className="cx-plan">
      <p className="bx-hint">Simulación: no se escribió nada en el proveedor ni en el CRM.</p>
      {blockers.length > 0 ? (
        <Notice tone="error">
          La baja no podría aplicarse ahora:
          <ul>{blockers.map((code) => <li key={code}>{codeText(code)}</li>)}</ul>
        </Notice>
      ) : <Notice tone="ok">Sin bloqueos: la baja puede aplicarse.</Notice>}
      {plan.irreversible ? <Notice tone="warning">Al aplicar, la baja no se podrá revertir en el proveedor.</Notice> : null}
      {toVoid !== null && toVoid > 0 ? <p>Se anularán {plural(toVoid, "factura impaga", "facturas impagas")} (irreversible).</p> : null}
      <dl className="bx-totals" aria-label="Pasos de la simulación">
        <div><dt>Pasos por hacer</dt><dd>{toRun.length ? toRun.map((s) => stepText(s)).join(", ") : "Ninguno"}</dd></div>
        <div><dt>Pasos ya hechos</dt><dd>{done.length ? done.map((s) => stepText(s)).join(", ") : "Ninguno"}</dd></div>
      </dl>
      <CascadePreviewView preview={plan.preview} title="Cascada recalculada" />
    </div>
  );
}
