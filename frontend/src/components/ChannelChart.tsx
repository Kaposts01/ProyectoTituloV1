import { useMemo } from "react";
import { buildChartRows, type ChannelChartRow } from "./chartRows";
import type { ReactElement } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type { ChannelChartRow };
export type ChannelChartSeries = { key: string; label: string; color: string };
export type ChannelChartAnnotation = { from: { year: number; month: number }; to: { year: number; month: number }; label: string };

const MONO = "'JetBrains Mono', 'Courier New', monospace";
/** Ancho máximo de barra: con una sola categoría la barra no debe ocupar todo el gráfico. */
const MAX_BAR_SIZE = 56;
const tick = { fontFamily: MONO, fontSize: 11, fill: "var(--text-2)" };

const fmt = (value: unknown, mode: "count" | "amount") => {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  return mode === "amount" ? `$${n.toLocaleString("es-CL")}` : n.toLocaleString("es-CL");
};

export function ChannelChart({ series, data, kind, mode, year, ariaLabel = "Gráfico de evolución mensual del canal", legend = false, annotations = [] }: {
  series: ChannelChartSeries[];
  data: ChannelChartRow[];
  kind: "bar" | "stacked" | "line" | "grouped";
  mode: "count" | "amount";
  year: number | null;
  ariaLabel?: string;
  legend?: boolean;
  annotations?: ChannelChartAnnotation[];
}) {
  const rows = useMemo(() => buildChartRows(data, year), [data, year]);
  if (rows.length === 0) return <p className="empty-chart">Sin datos para el período.</p>;
  const ymId = (y: number, m: number) => y * 12 + m;
  const bands: ReactElement[] = [];
  annotations.forEach((a, i) => {
    const inRange = rows.filter((r) => ymId(r.year, r.month) >= ymId(a.from.year, a.from.month) && ymId(r.year, r.month) <= ymId(a.to.year, a.to.month));
    if (inRange.length === 0) return;
    bands.push(
      <ReferenceArea key={`ann-${i}`} x1={inRange[0].label} x2={inRange[inRange.length - 1].label} fill="var(--border)" fillOpacity={0.35} stroke="none"
        label={{ value: a.label, position: "insideTop", fill: "var(--text-2)", fontFamily: MONO, fontSize: 11 }} />,
    );
  });
  const axes = (
    <>
      <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={tick} />
      <YAxis tickLine={false} axisLine={false} width={56} tick={tick} tickFormatter={(v) => fmt(v, mode)} allowDecimals={mode !== "count"} />
      <Tooltip
        formatter={(value, name) => [fmt(value, mode), name]}
        contentStyle={{ fontFamily: MONO, fontSize: 12, background: "var(--bg-surface)", color: "var(--text-1)", border: "1px solid var(--border)" }}
        labelStyle={{ fontFamily: MONO, color: "var(--text-1)" }}
      />
      {legend && <Legend wrapperStyle={{ fontFamily: MONO, fontSize: 12, color: "var(--text-2)" }} />}
      {bands}
    </>
  );
  return (
    <div role="img" aria-label={ariaLabel}>
    <ResponsiveContainer width="100%" height={280}>
      {kind === "line" ? (
        <LineChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
          {axes}
          {series.map((s) => <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} />)}
        </LineChart>
      ) : (
        <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
          {axes}
          {series.map((s) => <Bar key={s.key} maxBarSize={MAX_BAR_SIZE} dataKey={s.key} name={s.label} fill={s.color} stackId={kind === "stacked" ? "a" : undefined} radius={kind === "bar" ? [4, 4, 0, 0] : undefined} />)}
        </BarChart>
      )}
    </ResponsiveContainer>
    </div>
  );
}
