import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartStatusColor } from './chartColors'

export type MonthlyStatusEntry = { year: number; month: number; status?: string | null; count: number; amount: number }
export type MonthlyEntry = { year: number; month: number; count: number; amount: number }

// Una sola categoría no debe ocupar todo el ancho del gráfico.
const MAX_BAR_SIZE = 56

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
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        {statusSet.map((s, i) => (
          <Bar
            key={s}
            maxBarSize={MAX_BAR_SIZE}
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
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey={mode} fill={color} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ActivationsVsChurnChart({
  activations,
  cancellations,
  year,
  mode,
}: {
  activations: MonthlyStatusEntry[]
  cancellations: MonthlyEntry[]
  year: number | null
  mode: 'count' | 'amount'
}) {
  const filtAct = (year != null ? activations.filter(d => d.year === year) : activations)
    .filter(d => String(d.status ?? '').toUpperCase() !== 'SUSCRIPCION_FALLIDA')
  const actByKey = new Map<string, number>()
  for (const entry of filtAct) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    actByKey.set(key, (actByKey.get(key) ?? 0) + (mode === 'amount' ? entry.amount : entry.count))
  }

  const filtChurn = year != null ? cancellations.filter(d => d.year === year) : cancellations
  const churnByKey = new Map<string, number>()
  for (const entry of filtChurn) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    churnByKey.set(key, mode === 'amount' ? entry.amount : entry.count)
  }

  const allKeys = [...new Set([...actByKey.keys(), ...churnByKey.keys()])].sort()
  const rows = allKeys.map(key => {
    const [yr, mo] = key.split('-').map(Number)
    return {
      label: monthLabel(mo, yr),
      activations: actByKey.get(key) ?? 0,
      cancellations: churnByKey.get(key) ?? 0,
    }
  })
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={rows} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="activations" name="Activaciones" fill="var(--series-1)" radius={[4, 4, 0, 0]} barSize={20} />
        <Line type="linear" dataKey="cancellations" name="Caídas" stroke="var(--status-rejected)" strokeWidth={2} dot={{ fill: 'var(--status-rejected)', r: 3 }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export function MonthlyGrowthChart({
  activations,
  cancellations,
  year,
  mode,
}: {
  activations: MonthlyStatusEntry[]
  cancellations: MonthlyEntry[]
  year: number | null
  mode: 'count' | 'amount'
}) {
  const filtAct = (year != null ? activations.filter(d => d.year === year) : activations)
    .filter(d => String(d.status ?? '').toUpperCase() !== 'SUSCRIPCION_FALLIDA')
  const actByKey = new Map<string, number>()
  for (const entry of filtAct) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    actByKey.set(key, (actByKey.get(key) ?? 0) + (mode === 'amount' ? entry.amount : entry.count))
  }

  const filtChurn = year != null ? cancellations.filter(d => d.year === year) : cancellations
  const churnByKey = new Map<string, number>()
  for (const entry of filtChurn) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    churnByKey.set(key, mode === 'amount' ? entry.amount : entry.count)
  }

  const allKeys = [...new Set([...actByKey.keys(), ...churnByKey.keys()])].sort()
  const rows = allKeys.map(key => {
    const [yr, mo] = key.split('-').map(Number)
    const net = (actByKey.get(key) ?? 0) - (churnByKey.get(key) ?? 0)
    return { label: monthLabel(mo, yr), net }
  })
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'} />
        <Tooltip formatter={(v: unknown) => fmtVal(v, mode)} />
        <ReferenceLine y={0} stroke="var(--status-neutral)" />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="net" name="Crecimiento neto" radius={[4, 4, 0, 0]}>
          {rows.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.net >= 0 ? 'var(--status-paid)' : 'var(--status-rejected)'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function MonthlyChurnChart({
  data,
  year,
}: {
  data: { year: number; month: number; rate: number }[]
  year: number | null
}) {
  const filtered = year != null ? data.filter(d => d.year === year) : data
  const rows = filtered.map(d => ({ label: monthLabel(d.month, d.year), rate: d.rate }))
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={52} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
        <Tooltip formatter={(v: unknown) => `${Number(v).toLocaleString('es-CL')}%`} />
        <ReferenceLine y={0} stroke="var(--status-neutral)" />
        <Line type="monotone" dataKey="rate" name="Churn mensual (%)" stroke="var(--status-pending)" strokeWidth={2} dot={{ fill: 'var(--status-pending)', r: 3 }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

const _PAID_KW = ['pagad', 'aceptad', 'accepted', 'paid', 'success', 'cobrad', 'aprobad']
const _isPaid = (s: string) => _PAID_KW.some(k => s.toLowerCase().includes(k))

export function TransactionsVsSubscriptionsChart({
  payments,
  activeSubs,
  collectableSubs,
  year,
  mode,
}: {
  payments: MonthlyStatusEntry[]
  activeSubs: { year: number; month: number; count: number }[]
  collectableSubs: { year: number; month: number; count: number }[]
  year: number | null
  mode: 'count' | 'amount'
}) {
  const filtPay = (year != null ? payments.filter(d => d.year === year) : payments)
    .filter(d => d.status != null && _isPaid(String(d.status)))
  const payByKey = new Map<string, number>()
  for (const e of filtPay) {
    const key = `${e.year}-${String(e.month).padStart(2, '0')}`
    payByKey.set(key, (payByKey.get(key) ?? 0) + (mode === 'amount' ? e.amount : e.count))
  }

  const activeByKey = new Map<string, number>()
  for (const e of (year != null ? activeSubs.filter(d => d.year === year) : activeSubs)) {
    activeByKey.set(`${e.year}-${String(e.month).padStart(2, '0')}`, e.count)
  }

  const collectableByKey = new Map<string, number>()
  for (const e of (year != null ? collectableSubs.filter(d => d.year === year) : collectableSubs)) {
    collectableByKey.set(`${e.year}-${String(e.month).padStart(2, '0')}`, e.count)
  }

  const allKeys = [...new Set([...payByKey.keys(), ...activeByKey.keys(), ...collectableByKey.keys()])].sort()
  const rows = allKeys.map(key => {
    const [yr, mo] = key.split('-').map(Number)
    return {
      label: monthLabel(mo, yr),
      transactions: payByKey.get(key) ?? 0,
      active: activeByKey.get(key) ?? 0,
      collectable: collectableByKey.get(key) ?? 0,
    }
  })
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>
  const subscriptionAxisMax = Math.max(
    1,
    Math.ceil(Math.max(...rows.map(row => Math.max(row.active, row.collectable))) / 1000) * 1000,
  )

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={rows} margin={{ top: 16, right: 40, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis yAxisId="tx" tickLine={false} axisLine={false} width={48} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'} />
        <YAxis
          yAxisId="subs"
          orientation="right"
          allowDecimals={false}
          domain={[0, subscriptionAxisMax]}
          tickLine={false}
          axisLine={false}
          width={48}
          tick={{ fontSize: 10 }}
        />
        <Tooltip formatter={(v: unknown, name: unknown) =>
          name === 'Transacciones pagadas' ? fmtVal(v, mode) : Number(v).toLocaleString('es-CL')
        } />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Bar maxBarSize={MAX_BAR_SIZE} yAxisId="tx" dataKey="transactions" name="Transacciones pagadas" fill="var(--series-1)" radius={[4, 4, 0, 0]} barSize={20} />
        <Line yAxisId="subs" type="linear" dataKey="active" name="Subs activas" stroke="var(--series-2)" strokeWidth={2} dot={{ fill: 'var(--series-2)', r: 3 }} />
        <Line yAxisId="subs" type="linear" dataKey="collectable" name="Subs cobrables" stroke="var(--series-4)" strokeWidth={2} dot={{ fill: 'var(--series-4)', r: 3 }} strokeDasharray="5 5" />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export type ChannelRow = { source: string; clients: number; active_subscriptions: number; accepted: number; amount: number }

export function ChannelKpiChart({ channels, mode }: { channels: ChannelRow[]; mode: 'count' | 'amount' }) {
  const rows = channels.map(c => ({
    name: c.source,
    subscriptions: c.active_subscriptions,
    accepted: mode === 'amount' ? c.amount : c.accepted,
    clients: c.clients,
  }))
  if (!rows.length) return <p className="empty-chart">Sin datos por canal.</p>
  const COLOR = ['var(--series-1)', 'var(--series-2)', 'var(--series-4)', 'var(--series-3)']
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
        <CartesianGrid stroke="var(--border-subtle)" horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'}
          tickFormatter={(v: number) => mode === 'amount' ? `$${(v / 1000).toFixed(0)}k` : v.toLocaleString('es-CL')} />
        <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={72} />
        <Tooltip formatter={(v: unknown) => mode === 'amount' ? `$${Number(v).toLocaleString('es-CL')}` : Number(v).toLocaleString('es-CL')} />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="accepted" name={mode === 'amount' ? 'Recaudación' : 'Transacciones aceptadas'} radius={[0, 4, 4, 0]}>
          {rows.map((_, i) => <Cell key={i} fill={COLOR[i % COLOR.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function MonthlyRevenueChart({ data, year }: { data: MonthlyStatusEntry[]; year: number | null }) {
  const filtered = year != null ? data.filter(d => d.year === year) : data
  const channels = [...new Set(filtered.map(e => String(e.status ?? '')))]
  const byKey = new Map<string, Record<string, unknown>>()
  for (const e of filtered) {
    const key = `${e.year}-${String(e.month).padStart(2, '0')}`
    if (!byKey.has(key)) byKey.set(key, { label: monthLabel(e.month, e.year) })
    const ch = String(e.status ?? '')
    const row = byKey.get(key)!
    row[ch] = (Number(row[ch] ?? 0)) + e.amount
  }
  const rows = [...byKey.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v)
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>
  const COLORS: Record<string, string> = { VirtualPOS: 'var(--series-1)', Toku: 'var(--series-2)', Payku: 'var(--series-4)', TCH: 'var(--series-3)' }
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <defs>
          {channels.map(ch => (
            <linearGradient key={ch} id={`grad-${ch}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS[ch] ?? 'var(--status-neutral)'} stopOpacity={0.3} />
              <stop offset="95%" stopColor={COLORS[ch] ?? 'var(--status-neutral)'} stopOpacity={0.05} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={60} tick={{ fontSize: 10 }}
          tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
        <Tooltip formatter={(v: unknown) => `$${Number(v).toLocaleString('es-CL')}`} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        {channels.map(ch => (
          <Area key={ch} type="linear" dataKey={ch} name={ch}
            stroke={COLORS[ch] ?? 'var(--status-neutral)'} fill={`url(#grad-${ch})`} strokeWidth={2} stackId="1" />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}
