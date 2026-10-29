import { useId, useMemo, useState } from "react";
import { buildChartRows, buildCumulativeRows, pctOfTarget, type ChannelChartRow, type CumulativeRow } from "./chartRows";
import type { ReactElement } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type { ChannelChartRow };
export type ChannelChartSeries = { key: string; label: string; color: string };
export type ChannelChartAnnotation = { from: { year: number; month: number }; to: { year: number; month: number }; label: string };
/** Línea de referencia punteada (meta). `value` está en las mismas unidades que las series (meta del mes). */
export type ChannelChartReference = { value: number; label: string };
export type ChannelChartKind = "bar" | "stacked" | "line" | "grouped" | "cumulative";

const MONO = "'JetBrains Mono', 'Courier New', monospace";
/** Ancho máximo de barra: con una sola categoría la barra no debe ocupar todo el gráfico. */
const MAX_BAR_SIZE = 56;
const tick = { fontFamily: MONO, fontSize: 11, fill: "var(--text-2)" };

const fmt = (value: unknown, mode: "count" | "amount") => {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  if (mode === "amount") return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("es-CL")}`;
  return n.toLocaleString("es-CL");
};

type TooltipEntry = { name?: unknown; value?: unknown; color?: string; dataKey?: unknown; payload?: Record<string, unknown> };

/**
 * Contenido del tooltip único del gráfico (Recharts lo clona con active/payload/label).
 * - `showTotal` (apilado): suma de las fuentes y, con `reference`, «N % de la meta».
 * - `reference`: agrega la fila «<etiqueta>: valor».
 * - `cumulative`: agrega la brecha «Bajo/Sobre el ritmo por X» entre real y ritmo meta.
 */
export function ChartTooltipContent({ active, payload, label, mode, showTotal = false, reference, cumulative = false }: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: unknown;
  mode: "count" | "amount";
  showTotal?: boolean;
  reference?: ChannelChartReference;
  cumulative?: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const entries = payload.filter((p) => p.value !== null && p.value !== undefined);
  if (entries.length === 0) return null;
  const total = entries.reduce((acc, p) => acc + (Number.isFinite(Number(p.value)) ? Number(p.value) : 0), 0);
  const pct = showTotal && reference ? pctOfTarget(total, reference.value) : null;
  let gap: { dir: "Bajo" | "Sobre"; amount: number } | null = null;
  if (cumulative) {
    const row = payload[0]?.payload as { real?: number | null; pace?: number | null } | undefined;
    if (row && typeof row.real === "number" && typeof row.pace === "number" && row.real !== row.pace) {
      gap = { dir: row.real < row.pace ? "Bajo" : "Sobre", amount: Math.abs(row.real - row.pace) };
    }
  }
  return (
    <div className="chart-tooltip" style={{ fontFamily: MONO, fontSize: 12, background: "var(--bg-surface)", color: "var(--text-1)", border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{String(label ?? "")}</div>
      {reference ? <div>{reference.label}: {fmt(reference.value, mode)}</div> : null}
      {entries.map((p, i) => (
        <div key={`${String(p.dataKey ?? i)}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flex: "none" }} />
          {String(p.name ?? p.dataKey)}: {fmt(p.value, mode)}
        </div>
      ))}
      {showTotal ? (
        <div style={{ fontWeight: 700, marginTop: 4 }}>
          Total: {fmt(total, mode)}{pct !== null ? ` · ${pct} % de la meta` : ""}
        </div>
      ) : null}
      {gap ? <div style={{ fontWeight: 700, marginTop: 4 }}>{gap.dir} el ritmo por {fmt(gap.amount, mode)}</div> : null}
    </div>
  );
}

/** Marcas del eje Y en múltiplos de 25 %/50 %/100 % de la base, hasta cubrir `max`. */
function percentTicks(base: number, max: number): number[] {
  let step = base * 0.25;
  while (max / step > 8) step *= 2;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(6)));
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

type TableModel = { head: string[]; rows: Array<{ id: string; label: string; cells: string[] }> };

/**
 * Gráfico de evolución (Recharts, DEC-34 A).
 *
 * Además de bar / stacked / line / grouped admite `kind="cumulative"` (real acumulado vs ritmo de la
 * meta anual vs proyección por promedio) y, opcionalmente:
 * - `reference`: meta del mes como línea punteada (--chart-ref) y, en apilado, «% de la meta» en el tooltip.
 * - `percentAxis`: eje Y en % de la meta (`reference.value`, o `cumulative.annualTarget`); se ignora sin meta.
 * - `showDataToggle`: botón «Ver datos» que muestra una tabla accesible equivalente al gráfico.
 * El selector de rango es un componente aparte (`ChartRangeSelector` + `filterByRange`).
 */
export function ChannelChart({ series, data, kind, mode, year, ariaLabel = "Gráfico de evolución mensual del canal", legend = false, annotations = [], reference, percentAxis = false, cumulative, showDataToggle = false }: {
  series: ChannelChartSeries[];
  data: ChannelChartRow[];
  kind: ChannelChartKind;
  mode: "count" | "amount";
  year: number | null;
  ariaLabel?: string;
  legend?: boolean;
  annotations?: ChannelChartAnnotation[];
  reference?: ChannelChartReference;
  percentAxis?: boolean;
  /** Solo con kind="cumulative": meta anual (null/ausente = sin serie de ritmo). Las `series` indican qué claves se suman. */
  cumulative?: { annualTarget?: number | null };
  showDataToggle?: boolean;
}) {
  const isCum = kind === "cumulative";
  const annualTarget = cumulative?.annualTarget ?? null;
  const rows = useMemo(() => (isCum ? [] : buildChartRows(data, year)), [data, year, isCum]);
  const cumRows = useMemo<CumulativeRow[]>(
    () => (isCum ? buildCumulativeRows(data, series.map((s) => s.key), { year, annualTarget }) : []),
    [data, year, isCum, series, annualTarget],
  );
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const length = isCum ? cumRows.length : rows.length;
  if (length === 0) return <p className="empty-chart">Sin datos para el período.</p>;

  const hasPace = isCum && cumRows.some((r) => r.pace !== null);
  const refValue = isCum ? (hasPace ? (annualTarget as number) : null) : reference?.value ?? null;
  const pctAxis = percentAxis && refValue !== null && refValue > 0;

  // dominio y marcas del eje Y
  const peak = isCum
    ? Math.max(...cumRows.flatMap((r) => [r.real, r.pace, r.projection]).filter((v): v is number => v !== null))
    : Math.max(...rows.map((r) => (kind === "stacked" ? series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0) : Math.max(...series.map((s) => Number(r[s.key]) || 0)))));
  const ticks = pctAxis ? percentTicks(refValue as number, Math.max(peak, (refValue as number) * (isCum ? 1 : 1.1))) : undefined;
  const yDomain: [number, number | "auto"] | undefined = ticks ? [0, ticks[ticks.length - 1]] : reference ? [0, Math.max(peak, reference.value * 1.1)] : undefined;
  const yFormat = (v: unknown) => (pctAxis ? `${Math.round((Number(v) / (refValue as number)) * 100)} %` : fmt(v, mode));

  const ymId = (y: number, m: number) => y * 12 + m;
  const bands: ReactElement[] = [];
  if (!isCum) {
    annotations.forEach((a, i) => {
      const inRange = rows.filter((r) => ymId(r.year, r.month) >= ymId(a.from.year, a.from.month) && ymId(r.year, r.month) <= ymId(a.to.year, a.to.month));
      if (inRange.length === 0) return;
      bands.push(
        <ReferenceArea key={`ann-${i}`} x1={inRange[0].label} x2={inRange[inRange.length - 1].label} fill="var(--border)" fillOpacity={0.35} stroke="none"
          label={{ value: a.label, position: "insideTop", fill: "var(--text-2)", fontFamily: MONO, fontSize: 11 }} />,
      );
    });
  }
  const customTooltip = kind === "stacked" || isCum || reference !== undefined;
  const axes = (
    <>
      <CartesianGrid stroke="var(--chart-grid, var(--border-subtle))" vertical={false} />
      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={tick} />
      <YAxis tickLine={false} axisLine={false} width={pctAxis ? 52 : 56} tick={tick} tickFormatter={yFormat} allowDecimals={mode !== "count" || pctAxis}
        {...(ticks ? { ticks } : {})} {...(yDomain ? { domain: yDomain } : {})} />
      {customTooltip ? (
        <Tooltip content={<ChartTooltipContent mode={mode} showTotal={kind === "stacked"} reference={isCum ? undefined : reference} cumulative={isCum} />} />
      ) : (
        <Tooltip
          formatter={(value, name) => [fmt(value, mode), name]}
          contentStyle={{ fontFamily: MONO, fontSize: 12, background: "var(--bg-surface)", color: "var(--text-1)", border: "1px solid var(--border)" }}
          labelStyle={{ fontFamily: MONO, color: "var(--text-1)" }}
        />
      )}
      {legend && <Legend wrapperStyle={{ fontFamily: MONO, fontSize: 12, color: "var(--text-2)" }} />}
      {!isCum && reference ? (
        <ReferenceLine y={reference.value} stroke="var(--chart-ref)" strokeWidth={2} strokeDasharray="6 4"
          label={{ value: reference.label, position: "insideTopRight", fill: "var(--text-1)", fontFamily: MONO, fontSize: 11 }} />
      ) : null}
      {bands}
    </>
  );

  const margin = { top: 16, right: 8, left: 0, bottom: 0 };
  let chart: ReactElement;
  if (isCum) {
    chart = (
      <LineChart data={cumRows} margin={margin} accessibilityLayer>
        {axes}
        <Line type="linear" dataKey="real" name="Real acumulado" stroke={series[0]?.color ?? "var(--series-1)"} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
        {hasPace ? <Line type="linear" dataKey="pace" name="Ritmo meta" stroke="var(--chart-ref)" strokeWidth={2} strokeDasharray="6 4" dot={false} /> : null}
        <Line type="linear" dataKey="projection" name="Proyección" stroke="var(--series-6)" strokeWidth={2} strokeDasharray="2 4" dot={false} connectNulls={false} />
      </LineChart>
    );
  } else if (kind === "line") {
    chart = (
      <LineChart data={rows} margin={margin} accessibilityLayer>
        {axes}
        {series.map((s) => <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} />)}
      </LineChart>
    );
  } else {
    chart = (
      <BarChart data={rows} margin={margin} accessibilityLayer>
        {axes}
        {series.map((s) => <Bar key={s.key} maxBarSize={MAX_BAR_SIZE} dataKey={s.key} name={s.label} fill={s.color} stackId={kind === "stacked" ? "a" : undefined} radius={kind === "bar" ? [4, 4, 0, 0] : undefined} />)}
      </BarChart>
    );
  }

  // tabla alternativa: mismos datos que el gráfico, en texto
  let table: TableModel | null = null;
  if (showDataToggle) {
    if (isCum) {
      table = {
        head: ["Período", "Real acumulado", ...(hasPace ? ["Ritmo meta"] : []), "Proyección", ...(hasPace ? ["Diferencia vs ritmo"] : [])],
        rows: cumRows.map((r) => ({
          id: `${r.year}-${r.month}`,
          label: r.label,
          cells: [
            fmt(r.real, mode),
            ...(hasPace ? [fmt(r.pace, mode)] : []),
            fmt(r.projection, mode),
            ...(hasPace ? [r.real !== null && r.pace !== null ? fmt(r.real - r.pace, mode) : "—"] : []),
          ],
        })),
      };
    } else {
      const withTotal = kind === "stacked";
      const withPct = withTotal && reference !== undefined;
      table = {
        head: ["Período", ...series.map((s) => s.label), ...(withTotal ? ["Total"] : []), ...(withPct ? ["% de la meta"] : [])],
        rows: rows.map((r) => {
          const total = series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0);
          const pct = withPct ? pctOfTarget(total, reference?.value) : null;
          return {
            id: `${r.year}-${r.month}`,
            label: r.label,
            cells: [...series.map((s) => fmt(r[s.key], mode)), ...(withTotal ? [fmt(total, mode)] : []), ...(withPct ? [pct === null ? "—" : `${pct} %`] : [])],
          };
        }),
      };
    }
  }

  return (
    <div className="channel-chart">
      <div role="img" aria-label={ariaLabel}>
        <ResponsiveContainer width="100%" height={280}>
          {chart}
        </ResponsiveContainer>
      </div>
      {table ? (
        <>
          <button type="button" className="chart-data-toggle" aria-expanded={showTable} aria-controls={tableId} onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Ocultar datos" : "Ver datos"}
          </button>
          <div id={tableId} className="chart-data" role="region" aria-label={`${ariaLabel}: datos`} tabIndex={0} hidden={!showTable}>
            {showTable ? (
              <table className="chart-data-table">
                <caption className="sr-only">{ariaLabel}: tabla de datos</caption>
                <thead>
                  <tr>{table.head.map((h) => <th key={h} scope="col">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {table.rows.map((r) => (
                    <tr key={r.id}>
                      <th scope="row">{r.label}</th>
                      {r.cells.map((c, i) => <td key={i} className="mono">{c}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
