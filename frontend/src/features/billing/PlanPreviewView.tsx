import { buildKeptRows, buildPlanRows, PLAN_KIND_LABEL, PLAN_KIND_TONE } from "./billingPlan";
import { formatClp, formatPct, formatSignedClp } from "./billingLabels";
import type { PlanPreview } from "./types";
import { Badge, Notice } from "./ui";

/** Vista previa del plan: totales, avisos, tabla por mes y cobros automáticos conservados fuera del horizonte. */
export function PlanPreviewView({ plan, title = "Vista previa del plan" }: { plan: PlanPreview | null | undefined; title?: string }) {
  if (!plan) return <p className="muted-copy">Sin vista previa disponible.</p>;
  const rows = buildPlanRows(plan);
  const kept = buildKeptRows(plan);
  const s = plan.summary;
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
      {(plan.errors ?? []).length > 0 ? (
        <Notice tone="error">
          Errores del plan:
          <ul>{plan.errors!.map((e, i) => <li key={i}>{e.month ? <><span className="mono">{e.month}</span>: </> : null}{e.message}</li>)}</ul>
        </Notice>
      ) : null}
      {(plan.warnings ?? []).length > 0 ? (
        <Notice tone="warning">
          Avisos:
          <ul>{plan.warnings!.map((w, i) => <li key={i}>{w.month ? <><span className="mono">{w.month}</span>: </> : null}{w.message}</li>)}</ul>
        </Notice>
      ) : null}
      {plan.noop ? <Notice tone="neutral">El plan no produce cambios.</Notice> : null}
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table className="bx-table">
            <caption className="bx-sr">Plan por mes</caption>
            <thead>
              <tr><th scope="col">Mes</th><th scope="col">Acción</th><th scope="col">Fecha de cobro</th><th scope="col" className="num">Monto</th><th scope="col">Detalle</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="mono">{r.month}</td>
                  <td><Badge tone={PLAN_KIND_TONE[r.kind]}>{PLAN_KIND_LABEL[r.kind]}</Badge></td>
                  <td className="mono">{r.date ?? "—"}</td>
                  <td className="mono num">{r.amount === null ? "—" : formatClp(r.amount)}</td>
                  <td>{r.note ? <span className="mono">{r.note}</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {kept.length > 0 ? (
        <>
          <h3>Cobros automáticos conservados fuera del horizonte</h3>
          <div className="table-wrap">
            <table className="bx-table">
              <thead><tr><th scope="col">Mes</th><th scope="col">Cobro</th><th scope="col">Fecha</th><th scope="col" className="num">Monto</th></tr></thead>
              <tbody>
                {kept.map((k) => (
                  <tr key={k.key}>
                    <td className="mono">{k.month}</td><td className="mono">{k.chargeId}</td><td className="mono">{k.date}</td><td className="mono num">{formatClp(k.amount)}</td>
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
