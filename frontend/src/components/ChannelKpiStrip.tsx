import { KpiCard, KPI_EMPTY_CAPTION } from "./KpiCard";
import type { ChannelKpis } from "../features/shared/kpis";

export function ChannelKpiStrip({ kpis, ariaLabel = "KPIs del canal" }: { kpis: ChannelKpis | null; ariaLabel?: string }) {
  const k = kpis;
  const clients = k?.activeClients;
  const rejectedAmount = k?.rejectedCharges.amount;
  const r = k?.recaudoMensual;
  return (
    <>
      {r ? <p className="eyebrow">Mandatos vigentes</p> : null}
      <section className="metrics kpi-metrics kpi-strip" aria-label={ariaLabel}>
        <KpiCard label="MRR" value={k?.mrr ?? null} format="clp" caption="Ingreso mensual recurrente activo" />
        <KpiCard label="ARPU" value={k?.arpu ?? null} format="clp" emptyCaption={KPI_EMPTY_CAPTION} caption={clients != null ? `${clients.toLocaleString("es-CL")} cliente${clients !== 1 ? "s" : ""} con subs activas` : undefined} />
        <KpiCard label="Suscriptores activos" value={k?.activeSubscribers ?? null} format="count" />
        <KpiCard label="Churn" value={k?.churnRate ?? null} format="percent" caption={k?.churnWindowLabel ?? undefined} emptyCaption={KPI_EMPTY_CAPTION} />
        <KpiCard label="Cargos rechazados" value={k?.rejectedCharges.count ?? null} format="count" caption={rejectedAmount != null ? `$${Math.round(rejectedAmount).toLocaleString("es-CL")}` : undefined} />
      </section>
      {r ? (
        <>
          <p className="eyebrow">Recaudo aceptado del mes{r.period ? ` (período ${r.period})` : ""}</p>
          <section className="metrics kpi-metrics kpi-strip" aria-label={`${ariaLabel} · recaudo aceptado`}>
            <KpiCard label="MRR recaudado" value={r.mrr} format="clp" caption="Recaudo aceptado del período" />
            <KpiCard label="Transacciones aceptadas" value={r.acceptedTransactions} format="count" caption="Recaudo del período" />
            <KpiCard label="ARPU" value={r.arpu} format="clp" emptyCaption={KPI_EMPTY_CAPTION} caption="Por transacción aceptada" />
          </section>
        </>
      ) : null}
      {k?.note ? <p className="kpi-note muted-copy">{k.note}</p> : null}
    </>
  );
}
