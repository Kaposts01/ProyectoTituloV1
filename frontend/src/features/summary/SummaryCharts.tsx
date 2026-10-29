import { useMemo, useState, type ReactNode } from "react";
import { ChannelChart, type ChannelChartRow, type ChannelChartSeries } from "../../components/ChannelChart";
import { ChartRangeSelector } from "../../components/ChartRangeSelector";
import { filterByRange, type ChartRange } from "../../components/chartRows";
import { chartStatusColor } from "../../chartColors";
import { label } from "../../i18n/label";
import { flowRows, membersRows, parseMonth, revenueRows } from "./summaryChartData";
import type { UnifiedSummary } from "./summaryTypes";

const MEMBER_SERIES: ChannelChartSeries[] = [{ key: "members", label: "Socios totales (suma por canal)", color: "var(--series-1)" }];
const FLOW_SERIES: ChannelChartSeries[] = [
  { key: "activations", label: "Activaciones", color: "var(--series-1)" },
  { key: "cancellations", label: "Bajas", color: "var(--status-rejected)" },
];
const NET_SERIES: ChannelChartSeries = { key: "net", label: "Crecimiento neto", color: "var(--series-2)" };

function Panel({ id, title, note, children }: { id: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="summary-chart-card" aria-labelledby={id}>
      <h3 id={id} className="summary-chart-title">{title}</h3>
      {note ? <p className="summary-chart-note">{note}</p> : null}
      {children}
    </section>
  );
}

/**
 * Gráficos de evolución del resumen. Todas las series salen de `series` del endpoint (12 meses terminando en el mes
 * elegido); el selector de rango solo recorta lo ya recibido. «Año» = el año del último mes y «Todo» = los 12 meses
 * recibidos (el endpoint no entrega más historia). `tchDataDate` es la fecha del último dato de TCH (viene de Excel).
 */
export function SummaryCharts({ summary, tchDataDate }: { summary: UnifiedSummary; tchDataDate: string | null }) {
  const [range, setRange] = useState<ChartRange>("12m");
  const { series, channels } = summary;
  const revenueSeries = useMemo<ChannelChartSeries[]>(
    () => channels.map((channel) => ({ key: channel, label: label("channel", channel), color: chartStatusColor(channel) })),
    [channels],
  );
  const revenue = useMemo(() => filterByRange(revenueRows(series, channels), range), [series, channels, range]);
  const members = useMemo(() => filterByRange(membersRows(series), range), [series, range]);
  const flow = useMemo<ChannelChartRow[]>(() => filterByRange(flowRows(series), range), [series, range]);
  const lastYear = parseMonth(series.months[series.months.length - 1] ?? "")?.year;

  return (
    <section className="summary-charts" aria-labelledby="summary-charts-title">
      <div className="summary-section-head">
        <h2 id="summary-charts-title" className="summary-section-title">Evolución</h2>
        <ChartRangeSelector value={range} onChange={setRange} yearLabel={lastYear ? `Año ${lastYear}` : "Año"} ariaLabel="Rango de los gráficos" />
      </div>
      <Panel
        id="summary-chart-revenue"
        title="Ingreso por canal"
        note={channels.includes("tch") ? (tchDataDate ? `TCH viene de reportes Excel: Dato al ${tchDataDate}.` : "TCH viene de reportes Excel: sin fecha de dato disponible.") : undefined}
      >
        <ChannelChart series={revenueSeries} data={revenue} kind="stacked" mode="amount" year={null} legend showDataToggle ariaLabel="Ingreso por canal: barras apiladas por mes" />
      </Panel>
      <div className="summary-chart-pair">
        <Panel id="summary-chart-members" title="Socios totales" note="Al cierre de cada mes. Suma por canal, no deduplicada.">
          <ChannelChart series={MEMBER_SERIES} data={members} kind="area" mode="count" year={null} showDataToggle ariaLabel="Socios totales al cierre de cada mes" />
        </Panel>
        <Panel id="summary-chart-flow" title="Activaciones y bajas" note="Barras por mes y línea de crecimiento neto (activaciones menos bajas).">
          <ChannelChart series={FLOW_SERIES} data={flow} kind="grouped" mode="count" year={null} legend overlayLine={NET_SERIES} showDataToggle ariaLabel="Activaciones, bajas y crecimiento neto por mes" />
        </Panel>
      </div>
    </section>
  );
}
