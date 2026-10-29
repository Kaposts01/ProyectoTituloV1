import { formatKpi, hasKpiValue, type KpiFormat } from "./formatKpi";

export const KPI_EMPTY_CAPTION = "Sin base para calcular";

/**
 * Tarjeta de KPI. `null`/`undefined`/NaN se muestran como «—» con texto accesible «sin datos»
 * (el 0 es un valor real y se muestra como 0). Con valor ausente, `emptyCaption` reemplaza al
 * `caption` para no dejar un subtexto engañoso.
 */
export function KpiCard({ label, value, format, caption, emptyCaption }: {
  label: string;
  value: number | null | undefined;
  format: KpiFormat;
  caption?: string;
  emptyCaption?: string;
}) {
  const empty = !hasKpiValue(value);
  const sub = empty ? emptyCaption : caption;
  return (
    <article className="metric-card kpi-card">
      <p className="metric-label">{label}</p>
      <strong className="metric-value kpi-value mono" {...(empty ? { role: "img", "aria-label": "sin datos" } : {})}>{formatKpi(value, format)}</strong>
      {sub ? <span className="metric-amount">{sub}</span> : null}
    </article>
  );
}
