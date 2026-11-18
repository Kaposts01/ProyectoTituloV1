import { useEffect, useRef } from "react";
import { formatKpi } from "../../components/formatKpi";
import { label } from "../../i18n/label";
import { METRIC_LABELS, type PrimaryMetric } from "./dashboardContext";
import { metricRecordLinks } from "./dashboardLinks";
import { formatDataDate, monthLabel } from "./summaryFormat";
import type { UnifiedSummary } from "./summaryTypes";

const DEFINITIONS: Record<PrimaryMetric, string> = {
  revenue: "Importe pagado registrado en el mes, con fecha hasta el último cálculo. Los valores por canal provienen de la misma respuesta del Dashboard.",
  members: "Suscripciones al cierre del mes, sumadas por canal y sin deduplicar. No equivale a personas únicas; los listados disponibles muestran el estado actual.",
  collectability: "Número de cobros pagados ÷ (pagados + rechazados), multiplicado por 100, según la clasificación del Dashboard. Es una proporción de cobros, no de montos.",
  uncollected: "Importe rechazado o no cobrado del mes, con fecha hasta el último cálculo. En Toku incluye facturas impagas o parcialmente pagadas vencidas.",
};

export function SummaryMetricDetail({ summary, metric, can, onClose, onOpenPath }: {
  summary: UnifiedSummary; metric: PrimaryMetric; can: (permission: string) => boolean;
  onClose: () => void; onOpenPath?: (path: string) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView?.({ block: "nearest" }); }, [metric]);
  const kpi = { revenue: summary.kpis.totalRevenue, members: summary.kpis.totalMembers,
    collectability: summary.kpis.collectability, uncollected: summary.kpis.uncollected }[metric];
  const value = formatKpi(kpi.value, kpi.unit === "clp" ? "clp" : kpi.unit === "pct" ? "percent" : "count");
  const links = metricRecordLinks(summary, metric, can);
  return <section id="summary-metric-detail" className="summary-metric-detail" aria-labelledby="summary-detail-heading"
    onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); onClose(); } }}>
    <div className="summary-section-head">
      <h2 id="summary-detail-heading" ref={heading} tabIndex={-1} className="summary-section-title">Detalle de {METRIC_LABELS[metric]}</h2>
      <button type="button" className="secondary-button" onClick={onClose}>Cerrar detalle</button>
    </div>
    <p>{monthLabel(summary.month)} · {summary.channels.map((c) => label("channel", c)).join(", ")}</p>
    <strong className="summary-detail-value mono">{value}</strong>
    <p>Fecha de cálculo: {formatDataDate(summary.generatedAt) ?? "no disponible"} (hora de Chile).</p>
    <p>{DEFINITIONS[metric]}</p>
    {kpi.value === null ? <p>No hay base disponible para calcular este indicador. No representa un valor cero.</p> : null}
    {summary.isCurrentMonth ? <p className="muted-copy">Mes en curso: información parcial al último cálculo.</p> : null}
    {metric === "revenue" ? <div className="table-wrap"><table>
      <caption>Ingreso por canal del mes seleccionado (CLP)</caption>
      <thead><tr><th scope="col">Canal</th><th scope="col" className="num">Ingreso pagado</th></tr></thead>
      <tbody>{summary.channels.map((c) => <tr key={c}><th scope="row">{label("channel", c)}</th><td className="num mono">{formatKpi(summary.kpis.revenueByChannel[c]?.value, "clp")}</td></tr>)}</tbody>
      <tfoot><tr><th scope="row">Ingreso total del Dashboard</th><td className="num mono">{value}</td></tr></tfoot>
    </table></div> : null}
    {links.length > 0 ? <div className="summary-related-records"><h3>Consultar registros relacionados</h3>
      <p className="muted-copy">Los accesos respetan tus permisos. Revisa la cobertura indicada antes de comparar el listado con el indicador.</p>
      <ul>{links.map((link) => <li key={link.channel}>
        <a href={link.href} onClick={(event) => {
          if (onOpenPath && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onOpenPath(link.href); }
        }}>{metric === "members" ? "Consultar suscripciones actuales de" : "Consultar movimientos de"} {label("channel", link.channel)}</a>
        <p>{link.note}</p>
      </li>)}</ul>
    </div> : <p className="muted-copy">No hay accesos a listados habilitados para este período y tus permisos. Puedes consultar aquí el valor y su definición.</p>}
  </section>;
}
