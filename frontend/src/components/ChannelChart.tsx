import { useId, useMemo, useState, type KeyboardEvent, type ReactElement } from "react";
import { buildChartRows, buildCumulativeRows, pctOfTarget, type ChannelChartRow, type CumulativeRow } from "./chartRows";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FLOW_IN_COLOR, FLOW_OUT_COLOR } from "../chartColors";
import { CUM, fmt, has, NEG, PCT, RANGE, signed, waterfallFill, plotRowsFor } from "./chartModel";

export type { ChannelChartRow };
export type ChannelChartSeries = { key: string; label: string; color: string };
export type ChannelChartAnnotation = { from: { year: number; month: number }; to: { year: number; month: number }; label: string };
/** Línea de referencia punteada (meta). `value` está en las mismas unidades que las series (meta del mes). */
export type ChannelChartReference = { value: number; label: string };
/**
 * Tipos de gráfico (DEC-34: Recharts ampliado; matriz KPI a gráfico de la sección 3.6):
 * - bar / grouped / stacked / line / area: tendencia mensual.
 * - cumulative: real acumulado vs ritmo de la meta vs proyección.
 * - diverging: ganar o perder socios; la PRIMERA serie va hacia arriba y las demás hacia abajo (se muestran en valor absoluto).
 * - stacked100: reparto de cartera; cada mes suma 100 % (el valor absoluto sigue en el tooltip y la tabla).
 * - waterfall: variación del mes; la PRIMERA serie es el cambio de cada mes y la barra flota desde el acumulado anterior.
 */
export type ChannelChartKind = "bar" | "stacked" | "line" | "grouped" | "cumulative" | "area" | "diverging" | "stacked100" | "waterfall";
/** Unidad de las series: conteo, monto en pesos o porcentaje (p. ej. churn mensual). */
import type { ChannelChartMode } from "./chartModel";
export type { ChannelChartMode };

const MONO = "'JetBrains Mono', 'Courier New', monospace";
/** Ancho máximo de barra: con una sola categoría la barra no debe ocupar todo el gráfico. */
const MAX_BAR_SIZE = 56;
const tick = { fontFamily: MONO, fontSize: 11, fill: "var(--text-2)" };

/** Ancho del eje Y según la etiqueta más larga (monoespaciada de 11 px, ~7 px por carácter + holgura), nunca menos de `min`. */
const AXIS_CHAR_WIDTH = 7;
const yAxisWidth = (labels: string[], min: number) => Math.max(min, Math.max(0, ...labels.map((l) => l.length)) * AXIS_CHAR_WIDTH + 12);

type TooltipEntry = { name?: unknown; value?: unknown; color?: string; dataKey?: unknown; payload?: Record<string, unknown> };

/**
 * Contenido del tooltip único del gráfico (Recharts lo clona con active/payload/label). Es el mismo en todos los tipos.
 * - `showTotal` (apilado): suma de las fuentes y, con `reference`, «N % de la meta».
 * - `reference`: agrega la fila «<etiqueta>: valor».
 * - `cumulative`: agrega la brecha «Bajo/Sobre el ritmo por X» entre real y ritmo meta.
 * - `absolute` (divergente): muestra el valor absoluto de las series que se dibujan hacia abajo.
 * - `share` (apilada al 100 %): muestra «N % (valor)» con el valor original de la fila.
 * - `waterfall`: variación con signo y acumulado del mes.
 */
export function ChartTooltipContent({ active, payload, label, mode, showTotal = false, reference, cumulative = false, absolute = false, share = false, waterfall = false }: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: unknown;
  mode: ChannelChartMode;
  showTotal?: boolean;
  reference?: ChannelChartReference;
  cumulative?: boolean;
  absolute?: boolean;
  share?: boolean;
  waterfall?: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const entries = payload.filter((p) => p.value !== null && p.value !== undefined);
  if (entries.length === 0) return null;
  const row = payload[0]?.payload ?? {};
  const shown = (p: TooltipEntry): string => {
    const key = String(p.dataKey ?? "");
    if (share && key.startsWith(PCT)) return `${fmt(p.value, "percent")} (${fmt(row[key.slice(PCT.length)], mode)})`;
    if (absolute) return fmt(Math.abs(Number(p.value)), mode);
    return fmt(p.value, mode);
  };
  const total = entries.reduce((acc, p) => acc + (Number.isFinite(Number(p.value)) ? Number(p.value) : 0), 0);
  const pct = showTotal && reference ? pctOfTarget(total, reference.value) : null;
  let gap: { dir: "Bajo" | "Sobre"; amount: number } | null = null;
  if (cumulative) {
    const r = row as { real?: number | null; pace?: number | null };
    if (typeof r.real === "number" && typeof r.pace === "number" && r.real !== r.pace) {
      gap = { dir: r.real < r.pace ? "Bajo" : "Sobre", amount: Math.abs(r.real - r.pace) };
    }
  }
  return (
    <div className="chart-tooltip" style={{ fontFamily: MONO, fontSize: 12, background: "var(--bg-surface)", color: "var(--text-1)", border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{String(label ?? "")}</div>
      {reference ? <div>{reference.label}: {fmt(reference.value, mode)}</div> : null}
      {waterfall ? (
        <>
          <div>Variación: {signed(Number(row.__delta), mode)}</div>
          <div style={{ fontWeight: 700, marginTop: 4 }}>Acumulado: {fmt(row[CUM], mode)}</div>
        </>
      ) : entries.map((p, i) => (
        <div key={`${String(p.dataKey ?? i)}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flex: "none" }} />
          {String(p.name ?? p.dataKey)}: {shown(p)}
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
 * Gráfico de evolución mensual (Recharts, DEC-34 A). Ver `ChannelChartKind` para los tipos.
 *
 * Opciones:
 * - `mode="percent"`: series en porcentaje (p. ej. churn); eje, tooltip y tabla en «N %».
 * - `reference`: meta del mes como línea punteada (--chart-ref) y, en apilado, «% de la meta» en el tooltip.
 * - `percentAxis`: eje Y en % de la meta (`reference.value`, o `cumulative.annualTarget`); se ignora sin meta.
 * - `showDataToggle`: botón «Ver datos» que muestra una tabla accesible equivalente al gráfico.
 * - `overlayLine`: línea encima de las barras (p. ej. crecimiento neto); admite negativos.
 * - `waterfallStart`: valor inicial del waterfall (por defecto 0).
 * Teclado: el gráfico es una parada de Tab; ←/→ (o ↑/↓) recorren los meses, Inicio/Fin van al primero y al último y
 * Escape suelta la selección. El mes elegido se marca en el gráfico y se lee en voz alta (región `aria-live`).
 * El selector de rango es un componente aparte (`ChartRangeSelector` + `filterByRange`).
 */
export function ChannelChart({ series, data, kind, mode, year, ariaLabel = "Gráfico de evolución mensual del canal", legend = false, annotations = [], reference, percentAxis = false, cumulative, showDataToggle = false, overlayLine, waterfallStart = 0 }: {
  series: ChannelChartSeries[];
  data: ChannelChartRow[];
  kind: ChannelChartKind;
  mode: ChannelChartMode;
  year: number | null;
  ariaLabel?: string;
  legend?: boolean;
  annotations?: ChannelChartAnnotation[];
  reference?: ChannelChartReference;
  percentAxis?: boolean;
  /** Solo con kind="cumulative": meta anual (null/ausente = sin serie de ritmo). Las `series` indican qué claves se suman. */
  cumulative?: { annualTarget?: number | null };
  showDataToggle?: boolean;
  /** Línea superpuesta a las barras (kind bar/grouped/stacked/diverging). Su clave va en las filas como las demás series. */
  overlayLine?: ChannelChartSeries;
  waterfallStart?: number;
}) {
  const isCum = kind === "cumulative";
  const annualTarget = cumulative?.annualTarget ?? null;
  const rows = useMemo(() => (isCum ? [] : buildChartRows(data, year)), [data, year, isCum]);
  const cumRows = useMemo<CumulativeRow[]>(
    () => (isCum ? buildCumulativeRows(data, series.map((s) => s.key), { year, annualTarget }) : []),
    [data, year, isCum, series, annualTarget],
  );
  const plotRows = useMemo(() => (isCum ? [] : plotRowsFor(kind, rows, series, waterfallStart)), [isCum, kind, rows, series, waterfallStart]);
  const [showTable, setShowTable] = useState(false);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  const tableId = useId();
  const hintId = useId();
  const length = isCum ? cumRows.length : rows.length;
  if (length === 0) return <p className="empty-chart">Sin datos para el período.</p>;

  const hasPace = isCum && cumRows.some((r) => r.pace !== null);
  const refValue = isCum ? (hasPace ? (annualTarget as number) : null) : reference?.value ?? null;
  const pctAxis = percentAxis && refValue !== null && refValue > 0 && kind !== "stacked100";
  const unitMode: ChannelChartMode = kind === "stacked100" ? "percent" : mode;

  // valores dibujados (para el ancho del eje y el dominio)
  const plotted: number[] = isCum
    ? cumRows.flatMap((r) => [r.real, r.pace, r.projection]).filter((v): v is number => v !== null)
    : kind === "stacked" ? rows.map((r) => series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0))
    : kind === "stacked100" ? [0, 100]
    : kind === "waterfall" ? plotRows.flatMap((r) => r[RANGE] as number[])
    : kind === "diverging" ? plotRows.flatMap((r) => [Number(r[series[0]?.key ?? ""]) || 0, ...series.slice(1).map((s) => Number(r[`${NEG}${s.key}`]) || 0)])
    : rows.flatMap((r) => series.map((s) => Number(r[s.key]) || 0));
  if (overlayLine) plotted.push(...rows.map((r) => Number(r[overlayLine.key]) || 0));
  const peak = Math.max(0, ...plotted);
  const floor = Math.min(0, ...plotted);
  const ticks = pctAxis ? percentTicks(refValue as number, Math.max(peak, (refValue as number) * (isCum ? 1 : 1.1))) : undefined;
  const yDomain: [number, number | "auto"] | undefined = kind === "stacked100" ? [0, 100] : ticks ? [0, ticks[ticks.length - 1]] : reference ? [0, Math.max(peak, reference.value * 1.1)] : undefined;
  const yFormat = (v: unknown) => (pctAxis ? `${Math.round((Number(v) / (refValue as number)) * 100)} %` : kind === "diverging" ? fmt(Math.abs(Number(v)), unitMode) : fmt(v, unitMode));

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
  const labels = isCum ? cumRows.map((r) => r.label) : rows.map((r) => r.label);
  const focusLabel = focusIdx !== null ? labels[Math.min(focusIdx, labels.length - 1)] : null;
  const yWidth = yAxisWidth([...(ticks ?? []), peak, floor].map((v) => yFormat(v)), pctAxis ? 52 : 56);
  const axes = (
    <>
      <CartesianGrid stroke="var(--chart-grid, var(--border-subtle))" vertical={false} />
      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={tick} interval="preserveStartEnd" minTickGap={24} />
      <YAxis tickLine={false} axisLine={false} width={yWidth} tick={tick} tickFormatter={yFormat} allowDecimals={mode !== "count" || pctAxis}
        {...(ticks ? { ticks } : {})} {...(yDomain ? { domain: yDomain } : {})} />
      <Tooltip content={
        <ChartTooltipContent mode={mode} showTotal={kind === "stacked"} reference={isCum ? undefined : reference} cumulative={isCum}
          absolute={kind === "diverging"} share={kind === "stacked100"} waterfall={kind === "waterfall"} />
      } />
      {legend && kind !== "waterfall" && <Legend wrapperStyle={{ fontFamily: MONO, fontSize: 12, color: "var(--text-2)" }} />}
      {!isCum && reference ? (
        <ReferenceLine y={reference.value} stroke="var(--chart-ref)" strokeWidth={2} strokeDasharray="6 4"
          label={{ value: reference.label, position: "insideTopRight", fill: "var(--text-1)", fontFamily: MONO, fontSize: 11 }} />
      ) : null}
      {kind === "diverging" || kind === "waterfall" || floor < 0 ? <ReferenceLine y={0} stroke="var(--text-3)" /> : null}
      {focusLabel !== null ? <ReferenceLine x={focusLabel} stroke="var(--color-accent)" strokeWidth={2} strokeDasharray="3 3" className="chart-focus-marker" /> : null}
      {bands}
    </>
  );

  const margin = { top: 16, right: 8, left: 0, bottom: 0 };
  const a11y = { accessibilityLayer: false } as const; // la navegación por teclado la da el contenedor (una sola parada de Tab)
  let chart: ReactElement;
  if (isCum) {
    chart = (
      <LineChart data={cumRows} margin={margin} {...a11y}>
        {axes}
        <Line type="linear" dataKey="real" name="Real acumulado" stroke={series[0]?.color ?? "var(--series-1)"} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
        {hasPace ? <Line type="linear" dataKey="pace" name="Ritmo meta" stroke="var(--chart-ref)" strokeWidth={2} strokeDasharray="6 4" dot={false} /> : null}
        <Line type="linear" dataKey="projection" name="Proyección" stroke="var(--series-6)" strokeWidth={2} strokeDasharray="2 4" dot={false} connectNulls={false} />
      </LineChart>
    );
  } else if (kind === "area") {
    chart = (
      <AreaChart data={plotRows} margin={margin} {...a11y}>
        {axes}
        {series.map((s) => <Area key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} fill="var(--series-muted)" fillOpacity={0.9} dot={{ r: 3 }} connectNulls={false} />)}
      </AreaChart>
    );
  } else if (kind === "line") {
    chart = (
      <LineChart data={plotRows} margin={margin} {...a11y}>
        {axes}
        {series.map((s) => <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={rows.length <= 1 ? { r: 3 } : false} connectNulls={false} />)}
      </LineChart>
    );
  } else if (kind === "waterfall") {
    chart = (
      <BarChart data={plotRows} margin={margin} {...a11y}>
        {axes}
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey={RANGE} name={series[0]?.label ?? "Variación"} radius={2}>
          {plotRows.map((r, i) => <Cell key={`wf-${i}`} fill={waterfallFill(Number(r.__delta))} />)}
        </Bar>
      </BarChart>
    );
  } else {
    const bars = series.map((s, i) => {
      if (kind === "diverging") {
        return <Bar key={s.key} maxBarSize={MAX_BAR_SIZE} dataKey={i === 0 ? s.key : `${NEG}${s.key}`} name={s.label} fill={s.color} stackId="d" />;
      }
      if (kind === "stacked100") return <Bar key={s.key} maxBarSize={MAX_BAR_SIZE} dataKey={`${PCT}${s.key}`} name={s.label} fill={s.color} stackId="p" />;
      return <Bar key={s.key} maxBarSize={MAX_BAR_SIZE} dataKey={s.key} name={s.label} fill={s.color} stackId={kind === "stacked" ? "a" : undefined} radius={kind === "bar" ? [4, 4, 0, 0] : undefined} />;
    });
    chart = overlayLine ? (
      <ComposedChart data={plotRows} margin={margin} stackOffset={kind === "diverging" ? "sign" : undefined} {...a11y}>
        {axes}
        {bars}
        <Line type="linear" dataKey={overlayLine.key} name={overlayLine.label} stroke={overlayLine.color} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
      </ComposedChart>
    ) : (
      <BarChart data={plotRows} margin={margin} stackOffset={kind === "diverging" ? "sign" : undefined} {...a11y}>
        {axes}
        {bars}
      </BarChart>
    );
  }

  // tabla alternativa: mismos datos que el gráfico, en texto (también alimenta la lectura por teclado)
  let table: TableModel;
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
  } else if (kind === "waterfall") {
    table = {
      head: ["Período", series[0]?.label ?? "Variación", "Acumulado"],
      rows: plotRows.map((r) => ({ id: `${r.year}-${r.month}`, label: r.label, cells: [signed(Number(r.__delta), mode), fmt(r[CUM], mode)] })),
    };
  } else if (kind === "stacked100") {
    table = {
      head: ["Período", ...series.flatMap((s) => [s.label, `${s.label} (%)`]), "Total"],
      rows: plotRows.map((r) => {
        const hasAny = series.some((s) => has(r[s.key]));
        const total = hasAny ? series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0) : null;
        return {
          id: `${r.year}-${r.month}`,
          label: r.label,
          cells: [...series.flatMap((s) => [fmt(r[s.key], mode), fmt(r[`${PCT}${s.key}`], "percent")]), fmt(total, mode)],
        };
      }),
    };
  } else {
    const withTotal = kind === "stacked";
    const withPct = withTotal && reference !== undefined;
    table = {
      head: ["Período", ...series.map((s) => s.label), ...(withTotal ? ["Total"] : []), ...(withPct ? ["% de la meta"] : []), ...(overlayLine ? [overlayLine.label] : [])],
      rows: rows.map((r) => {
        // Total sin ningún dato en el mes: «—», no 0.
        const hasAny = series.some((s) => r[s.key] !== undefined && r[s.key] !== null);
        const total = hasAny ? series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0) : null;
        const pct = withPct && total !== null ? pctOfTarget(total, reference?.value) : null;
        return {
          id: `${r.year}-${r.month}`,
          label: r.label,
          cells: [
            ...series.map((s) => fmt(r[s.key], mode)),
            ...(withTotal ? [fmt(total, mode)] : []),
            ...(withPct ? [pct === null ? "—" : `${pct} %`] : []),
            ...(overlayLine ? [fmt(r[overlayLine.key], mode)] : []),
          ],
        };
      }),
    };
  }

  const focused = focusIdx !== null ? table.rows[Math.min(focusIdx, table.rows.length - 1)] : null;
  const readout = focused ? `${focused.label}: ${focused.cells.map((c, i) => `${table.head[i + 1]} ${c}`).join(" · ")}` : "";
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const last = length - 1;
    const cur = focusIdx;
    let next: number | null | undefined;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = cur === null ? 0 : Math.min(last, cur + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = cur === null ? last : Math.max(0, cur - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else if (e.key === "Escape") next = null;
    if (next === undefined) return;
    e.preventDefault();
    setFocusIdx(next);
  };

  return (
    <div className="channel-chart">
      <div className="chart-plot" tabIndex={0} role="group" aria-roledescription="gráfico" aria-label={`${ariaLabel} (recorrer con flechas)`} aria-describedby={hintId} onKeyDown={onKeyDown}>
        <div role="img" aria-label={ariaLabel}>
          <ResponsiveContainer width="100%" height={280}>
            {chart}
          </ResponsiveContainer>
        </div>
      </div>
      <p id={hintId} className="sr-only">Flechas izquierda y derecha: mes anterior o siguiente. Inicio y Fin: primer y último mes. Escape: soltar.</p>
      {kind === "waterfall" && legend ? (
        <p className="chart-legend" aria-hidden="true">
          <span><i style={{ background: FLOW_IN_COLOR }} />Sube</span>
          <span><i style={{ background: FLOW_OUT_COLOR }} />Baja</span>
        </p>
      ) : null}
      <p className="chart-readout mono" aria-live="polite" aria-atomic="true">{readout}</p>
      {showDataToggle ? (
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
