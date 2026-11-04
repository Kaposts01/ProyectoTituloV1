import { buildKeptRows, buildPlanRows, PLAN_KIND_LABEL, PLAN_KIND_TONE, planIssueText, reconcilePlan } from "./billingPlan";
import { formatClp, formatPct, formatSignedClp } from "./billingLabels";
import type { PlanPreview } from "./types";
import { Badge, Cell, Notice } from "./ui";

/** Vista previa del plan: totales, avisos, tabla por mes y cobros automáticos conservados fuera del horizonte. */
export function PlanPreviewView({ plan, title = "Vista previa del plan" }: { plan: PlanPreview | null | undefined; title?: string }) {
  if (!plan) return <p className="muted-copy">Sin vista previa disponible.</p>;
  const rows = buildPlanRows(plan);
  const kept = buildKeptRows(plan);
  const dueToday = (plan.kept_due_today ?? []).filter((m): m is string => typeof m === "string");
  const s = plan.summary;
  const recon = reconcilePlan(plan);
  return (
    <div>
      <h3>{title}</h3>
      {s ? (
        <dl className="bx-totals" aria-label="Totales del plan">
          <div><dt>Cobros a crear</dt><dd className="mono">{s.creates}</dd></div>
          <div><dt>Cobros a cancelar</dt><dd className="mono">{s.cancels}</dd></div>
          <div><dt>Meses cubiertos</dt><dd className="mono">{s.covered_months}</dd></div>
          <div><dt>Revisión manual</dt><dd className="mono">{s.manual_review_months}</dd></div>
          {s.previous_amount !== null || s.new_amount !== null ? (
            <div><dt>Monto mensual</dt><dd className="mono">{formatClp(s.previous_amount)} → {formatClp(s.new_amount)}</dd></div>
          ) : null}
          <div><dt>Diferencia total</dt><dd className="mono">{formatSignedClp(s.total_delta)}</dd></div>
          <div><dt>Variación</dt><dd className="mono">{formatPct(s.variation_pct)}</dd></div>
          {s.horizon_start ? <div><dt>Horizonte</dt><dd className="mono">{s.horizon_start} a {s.horizon_end ?? "—"}</dd></div> : null}
        </dl>
      ) : null}
      {recon.text ? <p className="bx-recon" data-testid="plan-reconciliation">{recon.text}</p> : null}
      {(plan.errors ?? []).length > 0 ? (
        <Notice tone="error">
          Errores del plan:
          <ul>{plan.errors!.map((e, i) => <li key={i}>{e.month ? <><span className="mono">{e.month}</span>: </> : null}{planIssueText(e.code, "error")}</li>)}</ul>
        </Notice>
      ) : null}
      {(plan.warnings ?? []).length > 0 ? (
        <Notice tone="warning">
          Avisos:
          <ul>{plan.warnings!.map((w, i) => <li key={i}>{w.month ? <><span className="mono">{w.month}</span>: </> : null}{planIssueText(w.code, "warning")}</li>)}</ul>
        </Notice>
      ) : null}
      {plan.noop ? <Notice tone="neutral">El plan no produce cambios.</Notice> : null}
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table className="bx-table bx-stack bx-stack-plan" role="table">
            <caption className="bx-sr">Plan por mes</caption>
            <thead role="rowgroup">
              <tr role="row"><th role="columnheader" scope="col">Mes</th><th role="columnheader" scope="col">Acción</th><th role="columnheader" scope="col">Fecha de cobro</th><th role="columnheader" scope="col" className="num">Monto</th><th role="columnheader" scope="col">Detalle</th></tr>
            </thead>
            <tbody role="rowgroup">
              {rows.map((r) => (
                <tr role="row" key={r.key}>
                  <Cell label="Mes" className="mono bx-c-month">{r.month}</Cell>
                  <Cell label="Acción" className="bx-c-kind"><Badge tone={PLAN_KIND_TONE[r.kind]}>{PLAN_KIND_LABEL[r.kind]}</Badge></Cell>
                  <Cell label="Fecha de cobro" className="mono bx-c-date bx-lbl">{r.date ?? "—"}</Cell>
                  <Cell label="Monto" className="mono num bx-c-amount">{r.amount === null ? "—" : formatClp(r.amount)}</Cell>
                  <Cell label="Detalle" className="bx-c-note" title={r.note ?? undefined}>{r.showMultiplePending ? <Badge tone="warning">Más de un cobro pendiente</Badge> : null}
                    {r.sharedCancels ? <span className="bx-shared">Uno de {r.sharedCancels} cobros pendientes del mes</span> : null}
                    {r.note ? <span className="mono">{r.note}</span> : null}
                  </Cell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {dueToday.length > 0 ? (
        <>
          <h3>Cobros de hoy conservados</h3>
          <p className="muted-copy">Hay un cobro pendiente fechado hoy en estos meses: no se toca, para evitar un doble cobro.</p>
          <ul>{dueToday.map((m) => <li key={m} className="mono">{m}</li>)}</ul>
        </>
      ) : null}
      {kept.length > 0 ? (
        <>
          <h3>Cobros automáticos conservados fuera del horizonte</h3>
          <div className="table-wrap">
            <table className="bx-table bx-stack bx-stack-kept" role="table">
              <caption className="bx-sr">Cobros automáticos conservados fuera del horizonte</caption>
              <thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">Mes</th><th role="columnheader" scope="col">Cobro</th><th role="columnheader" scope="col">Fecha</th><th role="columnheader" scope="col" className="num">Monto</th></tr></thead>
              <tbody role="rowgroup">
                {kept.map((k) => (
                  <tr role="row" key={k.key}>
                    <Cell label="Mes" className="mono bx-c-month">{k.month}</Cell>
                    <Cell label="Cobro" className="mono bx-c-charge bx-lbl">{k.chargeId}</Cell>
                    <Cell label="Fecha" className="mono bx-c-date bx-lbl">{k.date}</Cell>
                    <Cell label="Monto" className="mono num bx-c-amount">{formatClp(k.amount)}</Cell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
