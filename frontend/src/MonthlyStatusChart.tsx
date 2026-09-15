import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartStatusColor } from './chartColors'

export type MonthlyStatusEntry = { year: number; month: number; status?: string | null; count: number; amount: number }
export type MonthlyEntry = { year: number; month: number; count: number; amount: number }

const MONTHS = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']

function monthLabel(month: number, year: number): string {
  return `${MONTHS[month - 1]} ${year}`
}

// Algunas series (p. ej. churn_monthly de VirtualPOS/Toku) llegan sin `status`.
// Sin este fallback el gráfico revienta al colorear la barra y deja la página en blanco.
const statusOf = (entry: { status?: string | null }): string =>
  String(entry.status ?? '').trim() || 'Sin estado'

const fmtVal = (v: unknown, mode: 'count' | 'amount') =>
  mode === 'amount' ? `$${Number(v).toLocaleString('es-CL')}` : Number(v).toLocaleString('es-CL')

export function MonthlyStatusChart({
  data,
  mode,
  year,
}: {
  data: MonthlyStatusEntry[]
  mode: 'count' | 'amount'
  year: number | null
}) {
  const filtered = year != null ? data.filter(d => d.year === year) : data
  const statusSet = [...new Set(filtered.map(statusOf))]
  const byKey = new Map<string, Record<string, unknown>>()
  for (const entry of filtered) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    if (!byKey.has(key)) byKey.set(key, { label: monthLabel(entry.month, entry.year) })
    const row = byKey.get(key)!
    const status = statusOf(entry)
    row[status] = entry.count
    row[`${status}_amount`] = entry.amount
  }
  const rows = [...byKey.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v)
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#e1e7e5" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        {statusSet.map((s, i) => (
          <Bar
            key={s}
            dataKey={mode === 'count' ? s : `${s}_amount`}
            name={s}
            stackId="a"
            fill={chartStatusColor(s)}
            radius={i === statusSet.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function MonthlySimpleChart({
  data,
  color,
  mode,
  year,
}: {
  data: MonthlyEntry[]
  color: string
  mode: 'count' | 'amount'
  year: number | null
}) {
  const rows = (year != null ? data.filter(d => d.year === year) : data)
    .map(d => ({ ...d, label: monthLabel(d.month, d.year) }))
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#e1e7e5" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <Bar dataKey={mode} fill={color} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
