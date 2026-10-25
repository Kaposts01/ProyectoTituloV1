import { useMemo } from "react";
import { buildChartRows, type ChannelChartRow } from "./chartRows";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type { ChannelChartRow };
export type ChannelChartSeries = { key: string; label: string; color: string };

const MONO = "'JetBrains Mono', 'Courier New', monospace";
const tick = { fontFamily: MONO, fontSize: 11, fill: "var(--text-2)" };

const fmt = (value: unknown, mode: "count" | "amount") => {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  return mode === "amount" ? `$${n.toLocaleString("es-CL")}` : n.toLocaleString("es-CL");
};

export function ChannelChart({ series, data, kind, mode, year, ariaLabel = "Gráfico de evolución mensual del canal" }: {
  series: ChannelChartSeries[];
  data: ChannelChartRow[];
  kind: "bar" | "stacked" | "line";
  mode: "count" | "amount";
  year: number | null;
  ariaLabel?: string;
}) {
  const rows = useMemo(() => buildChartRows(data, year), [data, year]);
  if (rows.length === 0) return <p className="empty-chart">Sin datos para el período.</p>;
  const axes = (
    <>
      <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={tick} />
      <YAxis tickLine={false} axisLine={false} width={56} tick={tick} tickFormatter={(v) => fmt(v, mode)} />
      <Tooltip
        formatter={(value, name) => [fmt(value, mode), name]}
        contentStyle={{ fontFamily: MONO, fontSize: 12, background: "var(--bg-surface)", color: "var(--text-1)", border: "1px solid var(--border)" }}
        labelStyle={{ fontFamily: MONO, color: "var(--text-1)" }}
      />
    </>
  );
  return (
    <div role="img" aria-label={ariaLabel}>
    <ResponsiveContainer width="100%" height={280}>
      {kind === "line" ? (
        <LineChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
          {axes}
          {series.map((s) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} />)}
        </LineChart>
      ) : (
        <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
          {axes}
          {series.map((s) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} stackId={kind === "stacked" ? "a" : undefined} radius={kind === "bar" ? [4, 4, 0, 0] : undefined} />)}
        </BarChart>
      )}
    </ResponsiveContainer>
    </div>
  );
}
