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

export function ActivacionCaidaChart({
  activaciones,
  caidas,
  year,
  mode,
}: {
  activaciones: MonthlyStatusEntry[]
  caidas: MonthlyEntry[]
  year: number | null
  mode: 'count' | 'amount'
}) {
  const filtAct = (year != null ? activaciones.filter(d => d.year === year) : activaciones)
    .filter(d => String(d.status ?? '').toUpperCase() !== 'SUSCRIPCION_FALLIDA')
  const actByKey = new Map<string, number>()
  for (const entry of filtAct) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    actByKey.set(key, (actByKey.get(key) ?? 0) + (mode === 'amount' ? entry.amount : entry.count))
  }

  const filtChurn = year != null ? caidas.filter(d => d.year === year) : caidas
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
      activaciones: actByKey.get(key) ?? 0,
      caidas: churnByKey.get(key) ?? 0,
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
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="activaciones" name="Activaciones" fill="#2563EB" radius={[4, 4, 0, 0]} barSize={20} />
        <Line type="linear" dataKey="caidas" name="Caídas" stroke="#DC2626" strokeWidth={2} dot={{ fill: '#DC2626', r: 3 }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export function CrecimientoMensualChart({
  activaciones,
  caidas,
  year,
  mode,
}: {
  activaciones: MonthlyStatusEntry[]
  caidas: MonthlyEntry[]
  year: number | null
  mode: 'count' | 'amount'
}) {
  const filtAct = (year != null ? activaciones.filter(d => d.year === year) : activaciones)
    .filter(d => String(d.status ?? '').toUpperCase() !== 'SUSCRIPCION_FALLIDA')
  const actByKey = new Map<string, number>()
  for (const entry of filtAct) {
    const key = `${entry.year}-${String(entry.month).padStart(2, '0')}`
    actByKey.set(key, (actByKey.get(key) ?? 0) + (mode === 'amount' ? entry.amount : entry.count))
  }

  const filtChurn = year != null ? caidas.filter(d => d.year === year) : caidas
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
        <ReferenceLine y={0} stroke="#94a3b8" />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="net" name="Crecimiento neto" radius={[4, 4, 0, 0]}>
          {rows.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.net >= 0 ? '#16A34A' : '#DC2626'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ChurnMensualChart({
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
        <CartesianGrid stroke="#e1e7e5" vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
        <YAxis tickLine={false} axisLine={false} width={52} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} />
        <Tooltip formatter={(v: unknown) => `${Number(v).toLocaleString('es-CL')}%`} />
        <ReferenceLine y={0} stroke="#94a3b8" />
        <Line type="monotone" dataKey="rate" name="Churn mensual (%)" stroke="#D97706" strokeWidth={2} dot={{ fill: '#D97706', r: 3 }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

const _PAID_KW = ['pagad', 'aceptad', 'accepted', 'paid', 'success', 'cobrad', 'aprobad']
const _isPaid = (s: string) => _PAID_KW.some(k => s.toLowerCase().includes(k))

export function TransaccionesSuscripcionesChart({
  payments,
  activeSubs,
  cobrableSubs,
  year,
  mode,
}: {
  payments: MonthlyStatusEntry[]
  activeSubs: { year: number; month: number; count: number }[]
  cobrableSubs: { year: number; month: number; count: number }[]
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

  const cobrableByKey = new Map<string, number>()
  for (const e of (year != null ? cobrableSubs.filter(d => d.year === year) : cobrableSubs)) {
    cobrableByKey.set(`${e.year}-${String(e.month).padStart(2, '0')}`, e.count)
  }

  const allKeys = [...new Set([...payByKey.keys(), ...activeByKey.keys(), ...cobrableByKey.keys()])].sort()
  const rows = allKeys.map(key => {
    const [yr, mo] = key.split('-').map(Number)
    return {
      label: monthLabel(mo, yr),
      transacciones: payByKey.get(key) ?? 0,
      activas: activeByKey.get(key) ?? 0,
      cobrables: cobrableByKey.get(key) ?? 0,
    }
  })
  if (!rows.length) return <p className="empty-chart">Sin datos para este período.</p>
  const subscriptionAxisMax = Math.max(
    1,
    Math.ceil(Math.max(...rows.map(row => Math.max(row.activas, row.cobrables))) / 1000) * 1000,
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
        <Bar maxBarSize={MAX_BAR_SIZE} yAxisId="tx" dataKey="transacciones" name="Transacciones pagadas" fill="#2563EB" radius={[4, 4, 0, 0]} barSize={20} />
        <Line yAxisId="subs" type="linear" dataKey="activas" name="Subs activas" stroke="#16A34A" strokeWidth={2} dot={{ fill: '#16A34A', r: 3 }} />
        <Line yAxisId="subs" type="linear" dataKey="cobrables" name="Subs cobrables" stroke="#D97706" strokeWidth={2} dot={{ fill: '#D97706', r: 3 }} strokeDasharray="5 5" />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export type ChannelRow = { source: string; clients: number; active_subscriptions: number; accepted: number; amount: number }

export function ChannelKpiChart({ channels, mode }: { channels: ChannelRow[]; mode: 'count' | 'amount' }) {
  const rows = channels.map(c => ({
    name: c.source,
    suscripciones: c.active_subscriptions,
    aceptadas: mode === 'amount' ? c.amount : c.accepted,
    clientes: c.clients,
  }))
  if (!rows.length) return <p className="empty-chart">Sin datos por canal.</p>
  const COLOR = ['#2563EB', '#16A34A', '#D97706', '#7C3AED']
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
        <CartesianGrid stroke="var(--border-subtle)" horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} allowDecimals={mode !== 'count'}
          tickFormatter={(v: number) => mode === 'amount' ? `$${(v / 1000).toFixed(0)}k` : v.toLocaleString('es-CL')} />
        <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={72} />
        <Tooltip formatter={(v: unknown) => mode === 'amount' ? `$${Number(v).toLocaleString('es-CL')}` : Number(v).toLocaleString('es-CL')} />
        <Bar maxBarSize={MAX_BAR_SIZE} dataKey="aceptadas" name={mode === 'amount' ? 'Recaudación' : 'Transacciones aceptadas'} radius={[0, 4, 4, 0]}>
          {rows.map((_, i) => <Cell key={i} fill={COLOR[i % COLOR.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function IngresosMensualesChart({ data, year }: { data: MonthlyStatusEntry[]; year: number | null }) {
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
  const COLORS: Record<string, string> = { VirtualPOS: '#2563EB', Toku: '#16A34A', Payku: '#D97706', TCH: '#7C3AED' }
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <defs>
          {channels.map(ch => (
            <linearGradient key={ch} id={`grad-${ch}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS[ch] ?? '#94a3b8'} stopOpacity={0.3} />
              <stop offset="95%" stopColor={COLORS[ch] ?? '#94a3b8'} stopOpacity={0.05} />
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
            stroke={COLORS[ch] ?? '#94a3b8'} fill={`url(#grad-${ch})`} strokeWidth={2} stackId="1" />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}
