import { ChurnKpiCard, KPI_EMPTY_CAPTION, KpiCard, type KpiChipStatus } from "../../components/KpiCard";
import type { KpiFormat } from "../../components/formatKpi";
import { churnHistory, netGrowthHistory, sparkValues } from "./summaryChartData";
import type { SummaryGoalStatus, SummaryKpi, SummaryUnit, UnifiedSummary } from "./summaryTypes";

const FORMAT: Record<SummaryUnit, KpiFormat> = { count: "count", clp: "clp", pct: "percent" };
const CHIP: Record<SummaryGoalStatus, KpiChipStatus> = { none: "none", met: "met", near: "off", off: "off" };

/** Definición del churn (D31 confirmada): siempre visible dentro de la tarjeta. */
export const CHURN_HELP = "Bajas del mes ÷ socios al inicio del mes";
const MEMBERS_NOTE = "Suma por canal, no deduplicada";
const ONLY_CURRENT_MONTH = "Solo disponible para el mes en curso";

/**
 * Props comunes de una tarjeta a partir de un KPI del modelo interno: variación, chip y, si hubiera meta, avance.
 * `partial` (QA-07): KPI de flujo de un mes en curso; comparar unos días contra un mes completo dibujaba una caída
 * que no ocurrió, así que no se muestra la variación (el aviso «mes en curso» lo explica arriba).
 */
function common(kpi: SummaryKpi, goodWhen: "up" | "down" = "up", partial = false) {
  return {
    value: kpi.value,
    format: FORMAT[kpi.unit],
    delta: partial ? undefined : { value: kpi.deltaVsPreviousMonth, goodWhen },
    chip: CHIP[kpi.goalStatus],
    goal: kpi.goal !== null ? { target: kpi.goal } : undefined,
  };
}

/**
 * Rejilla de KPIs del mes: 12 tarjetas. Cada una lleva variación contra el mes anterior y el chip de meta; mientras
 * no existan metas (D2 pendiente) el chip dice «sin meta» y no se dibuja barra de avance. Un KPI sin dato se ve «—».
 */
export function SummaryKpiGrid({ summary }: { summary: UnifiedSummary }) {
  const { kpis, series } = summary;
  const members = sparkValues(series.totalMembers);
  const activations = sparkValues(series.activations);
  const cancellations = sparkValues(series.cancellations);
  const revenue = series.revenueByChannel.flatMap((point) => (point.total === null ? [] : [point.total]));
  const membersCaption = kpis.totalMembers.note
    ? `${kpis.totalMembers.note.charAt(0).toUpperCase()}${kpis.totalMembers.note.slice(1)}${kpis.totalMembers.noteUnit ? ` (unidad: ${kpis.totalMembers.noteUnit})` : ""}`
    : MEMBERS_NOTE;
  const recurringEmpty = summary.isCurrentMonth ? KPI_EMPTY_CAPTION : ONLY_CURRENT_MONTH;
  // Flujos del mes (ingresos, altas, bajas…): parciales mientras el mes no cierra. Los stocks (socios, MRR, ARPU) y
  // las razones (cobrabilidad) sí se comparan.
  const flow = summary.isCurrentMonth;

  return (
    <section className="summary-kpi-grid" aria-label="Indicadores del mes">
      <KpiCard label="Ingreso total" variant="featured" {...common(kpis.totalRevenue, "up", flow)} caption="Cobros pagados del mes" emptyCaption={KPI_EMPTY_CAPTION} sparkline={revenue} />
      <KpiCard label="Acumulado del año" {...common(kpis.yearToDate, "up", flow)} caption="De enero al mes elegido" emptyCaption={KPI_EMPTY_CAPTION} />
      <KpiCard label="Socios totales" {...common(kpis.totalMembers)} caption={membersCaption} emptyCaption={KPI_EMPTY_CAPTION} sparkline={members} />
      <KpiCard label="Activaciones" {...common(kpis.activations, "up", flow)} caption="Altas del mes" emptyCaption={KPI_EMPTY_CAPTION} sparkline={activations} />
      <KpiCard label="Bajas" {...common(kpis.cancellations, "down", flow)} caption="Bajas del mes" emptyCaption={KPI_EMPTY_CAPTION} sparkline={cancellations} />
      <KpiCard label="Crecimiento neto" {...common(kpis.netGrowth, "up", flow)} caption="Activaciones menos bajas" emptyCaption={KPI_EMPTY_CAPTION} sparkline={netGrowthHistory(series)} />
      <ChurnKpiCard
        churnRate={kpis.churn.value}
        target={kpis.churn.goal}
        previous={flow ? null : kpis.churn.previousMonthValue}
        history={churnHistory(series)}
        windowLabel={kpis.churn.windowLabel ?? undefined}
        help={CHURN_HELP}
      />
      <KpiCard label="Cobrabilidad" {...common(kpis.collectability)} caption="Pagados ÷ (pagados + rechazados)" emptyCaption={KPI_EMPTY_CAPTION} />
      <KpiCard label="No cobrado" {...common(kpis.uncollected, "down", flow)} caption="Cobros rechazados del mes" emptyCaption={KPI_EMPTY_CAPTION} />
      <KpiCard label="Por cobrar" {...common(kpis.receivable, "up", flow)} caption="Pendientes con fecha dentro del mes" emptyCaption={KPI_EMPTY_CAPTION} />
      <KpiCard label="MRR" {...common(kpis.mrr)} caption="Ingreso mensual recurrente activo" emptyCaption={recurringEmpty} />
      <KpiCard label="ARPU" {...common(kpis.arpu)} caption="MRR ÷ clientes activos" emptyCaption={recurringEmpty} />
    </section>
  );
}

/** Esqueleto de carga de la rejilla (decorativo; el aviso accesible lo da el padre). */
export function SummaryKpiSkeleton() {
  return (
    <div className="summary-kpi-grid" aria-hidden="true">
      {Array.from({ length: 12 }, (_, index) => <div key={index} className="summary-skeleton" />)}
    </div>
  );
}
