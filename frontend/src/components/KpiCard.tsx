import { formatKpi, type KpiFormat } from "./formatKpi";

export function KpiCard({ label, value, format, caption }: {
  label: string;
  value: number | null;
  format: KpiFormat;
  caption?: string;
}) {
  return (
    <article className="metric-card kpi-card">
      <p className="metric-label">{label}</p>
      <strong className="metric-value kpi-value mono">{formatKpi(value, format)}</strong>
      {caption ? <span className="metric-amount">{caption}</span> : null}
    </article>
  );
}
