import { label } from "../../i18n/label";
import { dashboardHref, METRIC_LABELS, readDashboardContext } from "./dashboardContext";
import { RECORD_COVERAGE } from "./dashboardLinks";
import { monthLabel } from "./summaryFormat";
import type { SummaryChannel } from "./summaryTypes";

export function DashboardContextNotice({ onOpenPath, canReturn }: { onOpenPath?: (path: string) => void; canReturn: boolean }) {
  const context = readDashboardContext(window.location.search);
  if (!context) return null;
  const channel = new URLSearchParams(window.location.search).get("canal");
  const href = dashboardHref(context.month, context.channels);
  return <aside className="dashboard-context" aria-label="Origen del Dashboard">
    <div><strong>Desde {METRIC_LABELS[context.metric]} · {monthLabel(context.month)}</strong>
      <p>Canales del Dashboard: {context.channels.map((c) => label("channel", c)).join(", ")}. Puedes ajustar los filtros de este listado.</p>
      <p>{context.metric === "members" ? "Se muestran suscripciones actuales; el listado no reconstruye la base histórica del indicador."
        : channel && Object.hasOwn(RECORD_COVERAGE, channel) ? RECORD_COVERAGE[channel as SummaryChannel] : "Registros relacionados; consulta la definición del indicador antes de comparar totales."}</p>
    </div>
    {canReturn ? <a href={href} onClick={(event) => {
      if (onOpenPath && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onOpenPath(href); }
    }}>Volver al Dashboard</a> : null}
  </aside>;
}
