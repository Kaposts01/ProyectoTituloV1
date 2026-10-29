import { KpiCard, KPI_EMPTY_CAPTION } from "../../components/KpiCard";
import { rejectionRate, type GeneralKpiData } from "./generalKpiData";

const text = (value: unknown): string | null => (typeof value === "string" && value.trim() !== "" ? value.trim() : null);

export function GeneralKpis({ data, rejectedCount, acceptedCount }: {
  data: GeneralKpiData;
  rejectedCount: number;
  acceptedCount: number;
  selectedYear?: number | null;
}) {
  const pendingLabel = text(data.pending_payments_label);
  const basis = text(data.transactions?.basis_label);
  const churnWindow = text(data.churn_window_label);
  return (
    <section className="metrics kpi-metrics" aria-label="KPIs generales">
      <KpiCard label="Cargos rechazados" value={rejectedCount} format="count" caption={basis ?? "Cargos rechazados hasta hoy · no incluye cancelados"} />
      <KpiCard label="Tasa de rechazo" value={rejectionRate(rejectedCount, acceptedCount)} format="percent" caption="Tasa de rechazo · rechazados / (pagados + rechazados)" emptyCaption={KPI_EMPTY_CAPTION} />
      <KpiCard
        label={pendingLabel ?? "Pagos pendientes"}
        value={data.pending_payments ?? null}
        format="count"
        caption={pendingLabel ? undefined : "Cobros sin estado terminal"}
      />
      <KpiCard label="Tasa de sync" value={data.sync_success_rate_pct ?? null} format="percent" caption="Últimos 30 días" />
      <KpiCard label="Churn" value={data.churn_rate_pct ?? null} format="percent" caption={churnWindow ?? undefined} emptyCaption={KPI_EMPTY_CAPTION} />
    </section>
  );
}
