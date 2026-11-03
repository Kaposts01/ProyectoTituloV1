import { useId, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltipContent, fmt, type ChannelChartMode } from "./ChannelChart";

export type RankingItem = { key: string; label: string; value: number | null; color?: string };

const MONO = "'JetBrains Mono', 'Courier New', monospace";
const tick = { fontFamily: MONO, fontSize: 11, fill: "var(--text-2)" };

/** Ítems con dato, ordenados de mayor a menor (empate: por etiqueta); los sin dato no se dibujan. */
export function rankItems(items: RankingItem[]): RankingItem[] {
  return items
    .filter((i) => i.value !== null && Number.isFinite(i.value))
    .sort((a, b) => (b.value as number) - (a.value as number) || a.label.localeCompare(b.label, "es"));
}

/**
 * Ranking (matriz KPI a gráfico: canales, motivos de rechazo): barras HORIZONTALES ordenadas de mayor a menor, con
 * la etiqueta a la izquierda y el valor en JetBrains Mono. Variante de la familia `ChannelChart` (VIZ-04) para datos
 * por categoría, no por mes. Trae la misma tabla alternativa «Ver datos» y el mismo tooltip único.
 */
export function RankingChart({ items, mode, ariaLabel, color = "var(--series-1)", showDataToggle = false, valueLabel = "Valor" }: {
  items: RankingItem[];
  mode: ChannelChartMode;
  ariaLabel: string;
  color?: string;
  showDataToggle?: boolean;
  valueLabel?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const ranked = rankItems(items);
  if (ranked.length === 0) return <p className="empty-chart">Sin datos para comparar.</p>;
  const rows = ranked.map((i) => ({ name: i.label, value: i.value as number, color: i.color ?? color }));
  const labelWidth = Math.min(160, Math.max(56, ...rows.map((r) => r.name.length * 7 + 12)));
  const height = Math.max(120, rows.length * 36 + 24);
  return (
    <div className="channel-chart">
      <div role="img" aria-label={ariaLabel}>
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, left: 0, bottom: 4 }} accessibilityLayer={false}>
            <CartesianGrid stroke="var(--chart-grid, var(--border-subtle))" horizontal={false} />
            <XAxis type="number" tickLine={false} axisLine={false} tick={tick} allowDecimals={mode !== "count"} tickFormatter={(v) => fmt(v, mode)} />
            <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ ...tick, fill: "var(--text-1)" }} width={labelWidth} />
            <Tooltip content={<ChartTooltipContent mode={mode} />} cursor={{ fill: "var(--bg-hover)" }} />
            <Bar dataKey="value" name={valueLabel} maxBarSize={28} radius={[0, 4, 4, 0]}>
              {rows.map((r, i) => <Cell key={i} fill={r.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {showDataToggle ? (
        <>
          <button type="button" className="chart-data-toggle" aria-expanded={showTable} aria-controls={tableId} onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Ocultar datos" : "Ver datos"}
          </button>
          <div id={tableId} className="chart-data" role="region" aria-label={`${ariaLabel}: datos`} tabIndex={0} hidden={!showTable}>
            {showTable ? (
              <table className="chart-data-table">
                <caption className="sr-only">{ariaLabel}: tabla de datos</caption>
                <thead><tr><th scope="col">Posición</th><th scope="col">Categoría</th><th scope="col">{valueLabel}</th></tr></thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.name}><td className="mono">{i + 1}</td><th scope="row">{r.name}</th><td className="mono">{fmt(r.value, mode)}</td></tr>
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
