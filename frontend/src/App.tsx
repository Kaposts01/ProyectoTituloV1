import { lazy, Suspense, useEffect, useState } from 'react'
import './App.css'
import './Staging.css'

const ChannelActivityChart = lazy(() => import('./ChannelActivityChart'))

type SyncRun = { status: string; records_processed: number }
type SourceSummary = { source: string; records: number; resources: Record<string, number>; last_sync: SyncRun | null }
type Summary = { sources: SourceSummary[] }
type StagingRecord = { id: string; source: string; resource_type: string; external_id: string; payload: Record<string, unknown> }
type StagingResponse = { items: StagingRecord[]; total: number }
type ProviderSection = { source: string; resource: string; label: string }
type TableColumn = { label: string; value: (record: StagingRecord) => string }
type Activity = { year: number; month: number; count: number; amount: number }
type ChannelDashboard = { source: string; records: number; resources: Record<string, number>; statuses: { resource: string; status: string; count: number }[]; activity_resource: string; activity: Activity[]; years: number[]; last_sync: SyncRun | null }
type VirtualPosClientDetail = { client: StagingRecord; subscriptions: StagingRecord[]; subscription_total: number }
type VirtualPosPlanDetail = { plan: StagingRecord; subscriptions: StagingRecord[]; subscription_total: number }
type VirtualPosSubscriptionDetail = { subscription: StagingRecord; payment_method: unknown; charges: StagingRecord[]; charge_total: number }
type RelatedRecords = { label: string; resource_type: string; items: StagingRecord[] }
type ProviderRecordDetail = { record: StagingRecord; related: RelatedRecords[] }

const providerGroups: { name: string; sections: ProviderSection[] }[] = [
  { name: 'VirtualPOS', sections: [{ source: 'virtualpos', resource: 'client', label: 'Clientes' }, { source: 'virtualpos', resource: 'plan', label: 'Planes' }, { source: 'virtualpos', resource: 'subscription', label: 'Subscripciones' }, { source: 'virtualpos', resource: 'charge', label: 'Cargos' }, { source: 'virtualpos', resource: 'payment', label: 'Transacciones' }] },
  { name: 'Toku', sections: [{ source: 'toku', resource: 'customer', label: 'Clientes' }, { source: 'toku', resource: 'subscription', label: 'Subscripciones' }, { source: 'toku', resource: 'payment_method', label: 'Metodos de pago' }, { source: 'toku', resource: 'invoice', label: 'Deudas' }, { source: 'toku', resource: 'transaction', label: 'Transacciones' }] },
  { name: 'Payku', sections: [{ source: 'payku', resource: 'client', label: 'Clientes' }, { source: 'payku', resource: 'subscription', label: 'Suscripciones' }, { source: 'payku', resource: 'transaction', label: 'Transacciones' }, { source: 'payku', resource: 'plan', label: 'Planes' }] },
]
const virtualPosMetrics = [{ resource: 'client', label: 'Clientes', tone: 'blue' }, { resource: 'plan', label: 'Planes', tone: 'violet' }, { resource: 'subscription', label: 'Subscripciones', tone: 'gold' }, { resource: 'charge', label: 'Cargos', tone: 'orange' }, { resource: 'payment', label: 'Transacciones', tone: 'green' }]
const tokuMetrics = [{ resource: 'customer', label: 'Clientes', tone: 'blue' }, { resource: 'subscription', label: 'Subscripciones', tone: 'violet' }, { resource: 'payment_method', label: 'Metodos de pago', tone: 'gold' }, { resource: 'invoice', label: 'Deudas', tone: 'orange' }, { resource: 'transaction', label: 'Transacciones', tone: 'green' }]
const paykuMetrics = [{ resource: 'client', label: 'Clientes', tone: 'blue' }, { resource: 'plan', label: 'Planes', tone: 'violet' }, { resource: 'subscription', label: 'Suscripciones', tone: 'gold' }, { resource: 'transaction', label: 'Transacciones', tone: 'green' }]
const months = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
const virtualPosClientFields = ['uuid', 'status', 'type', 'first_name', 'last_name', 'email', 'phone_number', 'social_id_type', 'social_id', 'birth_date', 'gender_id', 'created', 'updated']
const virtualPosPlanFields = ['id', 'name', 'description', 'is_active', 'amount', 'activation_amount', 'currency', 'trial_days', 'num_charges', 'frequency_type', 'return_url', 'suscription_url', 'type', 'fixed_amount_day_charge', 'automatic_renewal', 'show_in_terminal', 'created_at', 'shipping_address']
const virtualPosSubscriptionFields = ['status', 'id', 'plan_id', 'plan_name', 'suscription_date', 'canceled_at', 'currency', 'amount', 'renewal', 'channel']

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json() as Promise<T>
}

function text(value: unknown, fallback = 'Sin dato'): string {
  if (value === null || value === undefined || value === '') return fallback
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function nested(payload: Record<string, unknown>, key: string, child: string): unknown {
  const value = payload[key]
  return value && typeof value === 'object' ? (value as Record<string, unknown>)[child] : undefined
}

function objectEntries(value: unknown): [string, unknown][] {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value as Record<string, unknown>) : []
}

function virtualPosClientName(record: StagingRecord): string {
  const client = record.payload.client
  if (!client || typeof client !== 'object') return 'Sin dato'
  const payload = client as Record<string, unknown>
  return `${text(payload.first_name, '')} ${text(payload.last_name, '')}`.trim() || 'Sin dato'
}

function active(value: unknown): string {
  return String(value).toLowerCase() === 'true' ? 'Activo' : 'Inactivo'
}

function paid(value: unknown): string {
  if (value === true || String(value).toLowerCase() === 'true') return 'Pagado'
  if (value === false || String(value).toLowerCase() === 'false') return 'No pagado'
  return 'Sin dato'
}

function title(source: string): string {
  return source === 'virtualpos' ? 'VirtualPOS' : source[0].toUpperCase() + source.slice(1)
}

function resourceTitle(resource: string): string {
  return { customer: 'Cliente', client: 'Cliente', subscription: 'Subscripción', payment_method: 'Método de pago', invoice: 'Deuda', transaction: 'Transacción', plan: 'Plan' }[resource] ?? resource
}

function virtualPosColumns(resource: string): TableColumn[] {
  const clientRut = (record: StagingRecord) => text(nested(record.payload, 'client', 'social_id') ?? record.payload.social_id)
  if (resource === 'client') return [{ label: 'UUID', value: (record) => text(record.payload.uuid, record.external_id) }, { label: 'RUT', value: (record) => text(record.payload.social_id) }, { label: 'Nombre', value: (record) => `${text(record.payload.first_name, '')} ${text(record.payload.last_name, '')}`.trim() || 'Sin dato' }, { label: 'Email', value: (record) => text(record.payload.email) }, { label: 'Telefono', value: (record) => text(record.payload.phone_number) }, { label: 'Estado', value: (record) => text(record.payload.status) }]
  if (resource === 'plan') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Nombre', value: (record) => text(record.payload.name) }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'Renovacion', value: (record) => active(record.payload.automatic_renewal) }, { label: 'Estado', value: (record) => active(record.payload.is_active) }, { label: 'Activo en POS', value: (record) => active(record.payload.show_in_terminal) }]
  if (resource === 'subscription') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'RUT cliente', value: clientRut }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'F. Inicio', value: (record) => text(record.payload.suscription_date) }, { label: 'F. Cancelacion', value: (record) => text(record.payload.canceled_at) }]
  if (resource === 'charge') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'RUT cliente', value: clientRut }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'Fecha de cargo', value: (record) => text(record.payload.charge_date) }]
  return [{ label: 'UUID', value: (record) => text(nested(record.payload, 'order', 'uuid') ?? record.external_id) }, { label: 'Estado', value: (record) => text(nested(record.payload, 'order', 'status')) }, { label: 'RUT cliente', value: clientRut }, { label: 'Monto', value: (record) => text(nested(record.payload, 'order', 'amount')) }, { label: 'F. Pago', value: (record) => text(nested(record.payload, 'order', 'authorized_at')) }]
}

function tokuColumns(resource: string): TableColumn[] {
  if (resource === 'customer') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'RUT', value: (record) => record.external_id }, { label: 'Nombre', value: (record) => text(record.payload.name) }, { label: 'Mail', value: (record) => text(record.payload.mail) }, { label: 'Telefono', value: (record) => text(record.payload.phone_number) }]
  if (resource === 'subscription') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'ID cliente', value: (record) => text(record.payload.customer) }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'F. Inicio', value: (record) => text(record.payload.anchor) }, { label: 'F. Cancelacion', value: (record) => text(record.payload.end_date) }]
  if (resource === 'payment_method') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'F. Creacion', value: (record) => text(record.payload.created_at) }, { label: 'Banco', value: (record) => text(record.payload.bank_name) }, { label: 'Tipo tarjeta', value: (record) => text(record.payload.card_type) }, { label: 'ID cliente', value: (record) => text(record.payload.customer_id) }, { label: 'RUT', value: (record) => record.external_id }, { label: 'Subscripciones', value: (record) => text(record.payload.subscription_ids) }]
  if (resource === 'invoice') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Cliente', value: (record) => text(record.payload.customer) }, { label: 'Subscripcion', value: (record) => text(record.payload.subscription) }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'Pagado', value: (record) => paid(record.payload.is_paid) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'Fecha limite', value: (record) => text(record.payload.due_date) }]
  return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'ID cliente', value: (record) => text(record.payload.customer_id) }, { label: 'ID subscripcion', value: (record) => text(record.payload.subscription_id) }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'Fecha transaccion', value: (record) => text(record.payload.transaction_date) }]
}

function paykuColumns(resource: string): TableColumn[] {
  if (resource === 'client') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'RUT', value: (record) => text(record.payload.rut) }, { label: 'Nombre', value: (record) => `${text(record.payload.first_name, '')} ${text(record.payload.last_name, '')}`.trim() || text(record.payload.name) }, { label: 'Email', value: (record) => text(record.payload.email) }, { label: 'Telefono', value: (record) => text(record.payload.phone) }]
  if (resource === 'plan') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'Nombre', value: (record) => text(record.payload.name) }]
  if (resource === 'subscription') return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'RUT', value: (record) => text(nested(record.payload, 'client', 'rut')) }, { label: 'F. Inicio', value: (record) => text(record.payload.start) }, { label: 'F. Cancelacion', value: (record) => text(record.payload.end) }]
  return [{ label: 'ID', value: (record) => text(record.payload.id, record.external_id) }, { label: 'Estado', value: (record) => text(record.payload.status) }, { label: 'ID subscripciones', value: (record) => text(record.payload.subscriptions) }, { label: 'Monto', value: (record) => text(record.payload.amount) }, { label: 'F. Pago', value: (record) => text(record.payload.created_at) }]
}

function Sidebar({ activeSection, channel, openProvider, onDashboard, onChannel, onSection, onToggle }: { activeSection: ProviderSection | null; channel: string | null; openProvider: string | null; onDashboard: () => void; onChannel: (source: string) => void; onSection: (section: ProviderSection) => void; onToggle: (provider: string) => void }) {
  return <aside className="sidebar"><button className="sidebar-brand" onClick={onDashboard}><span>CRM</span><strong>Suscripciones</strong></button><nav className="sidebar-nav" aria-label="Navegacion principal"><button className={!activeSection && !channel ? 'sidebar-item active' : 'sidebar-item'} onClick={onDashboard}>Dashboard</button>{providerGroups.map((group) => <section className="sidebar-group" key={group.name}><div className="channel-heading"><button className={channel === group.sections[0].source ? 'channel-dashboard active' : 'channel-dashboard'} onClick={() => onChannel(group.sections[0].source)}>{group.name}</button><button className="sidebar-expand" aria-label={`Expandir ${group.name}`} aria-expanded={openProvider === group.name} onClick={() => onToggle(group.name)}>{openProvider === group.name ? '-' : '+'}</button></div>{openProvider === group.name ? group.sections.map((section) => <button className={activeSection?.source === section.source && activeSection.resource === section.resource ? 'sidebar-item nested active' : 'sidebar-item nested'} key={section.resource} onClick={() => onSection(section)}>{section.label}</button>) : null}</section>)}<section className="sidebar-group"><button className="sidebar-toggle" disabled>TCH <span>+</span></button></section></nav></aside>
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <article className="metric-card"><span className={`metric-dot ${tone}`} /><p>{label}</p><strong>{value}</strong></article>
}

function ChannelDashboardView({ data, mode, year, onMode, onYear, onOpenResource }: { data: ChannelDashboard; mode: 'count' | 'amount'; year: number | null; onMode: (mode: 'count' | 'amount') => void; onYear: (year: number) => void; onOpenResource: (resource: string) => void }) {
  const metrics = data.source === 'virtualpos' ? virtualPosMetrics : data.source === 'toku' ? tokuMetrics : paykuMetrics
  const chartData = data.activity.filter((entry) => year === null || entry.year === year).map((entry) => ({ ...entry, label: months[entry.month - 1] }))
  const dataKey = mode
  const activityTitle = data.source === 'toku' ? 'Actividad de deudas' : 'Actividad de cobros'
  const metricSections = providerGroups.find((group) => group.sections[0].source === data.source)?.sections ?? []
  return <main className="app-shell channel-dashboard-page"><p className="eyebrow">{title(data.source).toUpperCase()} / STAGING</p><header className="channel-hero"><div><h2>Resumen operativo</h2><p>Datos locales sincronizados, pendientes de consolidación en BD_Central.</p></div><div className={`sync-state ${data.last_sync?.status === 'completed' ? 'ready' : 'attention'}`}><span />{data.last_sync?.status ?? 'Sin sincronización'}</div></header><section className={`metrics provider-metrics ${data.source === 'payku' ? 'payku-metrics' : ''}`} aria-label={`Metricas ${title(data.source)}`}>{metrics.map((metric) => <Metric key={metric.resource} label={metric.label} value={data.resources[metric.resource] ?? 0} tone={metric.tone} />)}</section><section className="channel-workspace"><article className="panel chart-panel"><div className="panel-heading"><div><p className="eyebrow">{activityTitle.toUpperCase()}</p><h3>Serie mensual</h3></div><div className="dashboard-controls"><div className="mode-switch"><button className={mode === 'count' ? 'active' : ''} onClick={() => onMode('count')}>Cantidad</button><button className={mode === 'amount' ? 'active' : ''} onClick={() => onMode('amount')}>Monto</button></div>{data.years.length ? <select aria-label="Año" value={year ?? data.years[0]} onChange={(event) => onYear(Number(event.target.value))}>{data.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}</select> : null}</div></div>{chartData.length ? <Suspense fallback={<p className="empty-chart">Cargando gráfico...</p>}><ChannelActivityChart data={chartData} mode={dataKey} /></Suspense> : <p className="empty-chart">Sin fechas y montos suficientes para construir una serie mensual.</p>}</article><article className="panel status-panel"><p className="eyebrow">ESTADOS</p><h3>Distribución disponible</h3>{data.statuses.length ? <div className="status-list">{data.statuses.map((entry) => <div key={`${entry.resource}-${entry.status}`}><span>{entry.resource}</span><strong>{entry.status}</strong><b>{entry.count}</b></div>)}</div> : <p className="empty-chart">Este canal no entrega estados normalizados.</p>}</article></section><section className="panel channel-resources"><div><p className="eyebrow">EXPLORAR STAGING</p><h3>Recursos del canal</h3></div><div>{metricSections.map((section) => <button key={section.resource} onClick={() => onOpenResource(section.resource)}>{section.label}<span>{data.resources[section.resource] ?? 0}</span></button>)}</div></section></main>
}

function App() {
  const [summary, setSummary] = useState<Summary>({ sources: [] })
  const [activeSection, setActiveSection] = useState<ProviderSection | null>(null)
  const [channel, setChannel] = useState<string | null>(null)
  const [channelData, setChannelData] = useState<ChannelDashboard | null>(null)
  const [openProvider, setOpenProvider] = useState<string | null>('VirtualPOS')
  const [records, setRecords] = useState<StagingResponse>({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [channelLoading, setChannelLoading] = useState(false)
  const [clientDetail, setClientDetail] = useState<VirtualPosClientDetail | null>(null)
  const [planDetail, setPlanDetail] = useState<VirtualPosPlanDetail | null>(null)
  const [subscriptionDetail, setSubscriptionDetail] = useState<VirtualPosSubscriptionDetail | null>(null)
  const [providerRecordDetail, setProviderRecordDetail] = useState<ProviderRecordDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'count' | 'amount'>('count')
  const [year, setYear] = useState<number | null>(null)

  useEffect(() => {
    let mounted = true
    getJson<Summary>('/api/v1/staging/summary').then((data) => { if (mounted) setSummary(data) }).catch(() => { if (mounted) setError('No se pudo cargar el resumen de staging local.') }).finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (!activeSection) return
    let mounted = true
    const path = `/api/v1/staging/records?source=${activeSection.source}&resource_type=${activeSection.resource}&limit=100`
    getJson<StagingResponse>(path).then((data) => { if (mounted) setRecords(data) }).catch(() => { if (mounted) setError('No se pudieron cargar los registros de staging local.') }).finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [activeSection])

  useEffect(() => {
    if (!channel) return
    let mounted = true
    getJson<ChannelDashboard>(`/api/v1/staging/dashboard/${channel}`).then((data) => { if (mounted) { setChannelData(data); setYear(data.years[0] ?? null) } }).catch(() => { if (mounted) setError('No se pudo cargar el mini dashboard del canal.') }).finally(() => { if (mounted) setChannelLoading(false) })
    return () => { mounted = false }
  }, [channel])

  function clearDetails() { setClientDetail(null); setPlanDetail(null); setSubscriptionDetail(null); setProviderRecordDetail(null) }
  function showDashboard() { clearDetails(); setActiveSection(null); setChannel(null); setError(null) }
  function showChannel(source: string) { clearDetails(); setActiveSection(null); setChannelData(null); setChannelLoading(true); setError(null); setYear(null); setChannel(source); setOpenProvider(title(source)) }
  function showSection(section: ProviderSection) { clearDetails(); setChannel(null); setLoading(true); setError(null); setActiveSection(section); setOpenProvider(title(section.source)) }
  function openChannelResource(resource: string) { const section = providerGroups.flatMap((group) => group.sections).find((entry) => entry.source === channel && entry.resource === resource); if (section) showSection(section) }
  async function openVirtualPosClient(record: StagingRecord) { setPlanDetail(null); setSubscriptionDetail(null); setDetailLoading(true); setError(null); try { setClientDetail(await getJson<VirtualPosClientDetail>(`/api/v1/staging/virtualpos/clients/${encodeURIComponent(record.external_id)}`)) } catch { setError('No se pudo cargar la ficha del cliente.') } finally { setDetailLoading(false) } }
  async function openVirtualPosPlan(record: StagingRecord) { setClientDetail(null); setSubscriptionDetail(null); setDetailLoading(true); setError(null); try { setPlanDetail(await getJson<VirtualPosPlanDetail>(`/api/v1/staging/virtualpos/plans/${encodeURIComponent(record.external_id)}`)) } catch { setError('No se pudo cargar la ficha del plan.') } finally { setDetailLoading(false) } }
  async function openVirtualPosSubscription(record: StagingRecord) { setClientDetail(null); setPlanDetail(null); setDetailLoading(true); setError(null); try { setSubscriptionDetail(await getJson<VirtualPosSubscriptionDetail>(`/api/v1/staging/virtualpos/subscriptions/${encodeURIComponent(record.external_id)}`)) } catch { setError('No se pudo cargar la ficha de la subscripción.') } finally { setDetailLoading(false) } }
  async function openProviderRecord(source: string, resource: string, record: StagingRecord) { clearDetails(); setDetailLoading(true); setError(null); try { setProviderRecordDetail(await getJson<ProviderRecordDetail>(`/api/v1/staging/${source}/${resource}/${encodeURIComponent(record.external_id)}`)) } catch { setError('No se pudo cargar la ficha del registro.') } finally { setDetailLoading(false) } }

  const columns: TableColumn[] = activeSection?.source === 'virtualpos' ? virtualPosColumns(activeSection.resource) : activeSection?.source === 'toku' ? tokuColumns(activeSection.resource) : activeSection?.source === 'payku' ? paykuColumns(activeSection.resource) : []
  const clientDetailView = clientDetail ? <main className="app-shell detail-page"><button className="back-button" onClick={() => setClientDetail(null)}>Volver a clientes VirtualPOS</button><p className="eyebrow">VIRTUALPOS / CLIENTE</p><h2>{text(clientDetail.client.payload.first_name, '')} {text(clientDetail.client.payload.last_name, '')}</h2><section className="panel"><p className="eyebrow">FICHA DEL CLIENTE</p><dl className="field-list">{virtualPosClientFields.map((field) => <div key={field}><dt>{field}</dt><dd>{field === 'uuid' ? text(clientDetail.client.payload.uuid, clientDetail.client.external_id) : text(clientDetail.client.payload[field])}</dd></div>)}</dl></section><section className="panel client-subscriptions"><div className="panel-heading"><div><p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p><h3>Relacionadas por RUT</h3></div><span>{clientDetail.subscription_total} total</span></div><div className="table-wrap"><table><thead><tr><th>ID Sub</th><th>Status</th><th>Monto</th><th>F. Inicio</th></tr></thead><tbody>{clientDetail.subscriptions.map((subscription) => <tr key={subscription.id}><td>{text(subscription.payload.id, subscription.external_id)}</td><td>{text(subscription.payload.status)}</td><td>{text(subscription.payload.amount)}</td><td>{text(subscription.payload.suscription_date)}</td></tr>)}{clientDetail.subscriptions.length === 0 ? <tr><td colSpan={4}>Sin suscripciones asociadas por RUT.</td></tr> : null}</tbody></table></div></section></main> : null
  const planDetailView = planDetail ? <main className="app-shell detail-page"><button className="back-button" onClick={() => setPlanDetail(null)}>Volver a planes VirtualPOS</button><p className="eyebrow">VIRTUALPOS / PLAN</p><h2>{text(planDetail.plan.payload.name, planDetail.plan.external_id)}</h2><section className="panel"><p className="eyebrow">FICHA DEL PLAN</p><dl className="field-list">{virtualPosPlanFields.map((field) => <div key={field}><dt>{field}</dt><dd>{field === 'id' ? text(planDetail.plan.payload.id, planDetail.plan.external_id) : text(planDetail.plan.payload[field])}</dd></div>)}</dl></section><section className="panel client-subscriptions"><div className="panel-heading"><div><p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p><h3>Asociadas al plan</h3></div><span>{planDetail.subscription_total} total</span></div><div className="table-wrap"><table><thead><tr><th>ID Sub</th><th>Nombre cliente</th><th>Monto</th><th>Status</th></tr></thead><tbody>{planDetail.subscriptions.map((subscription) => <tr key={subscription.id}><td><button className="record-link" onClick={() => void openVirtualPosSubscription(subscription)}>{text(subscription.payload.id, subscription.external_id)}</button></td><td>{virtualPosClientName(subscription)}</td><td>{text(subscription.payload.amount)}</td><td>{text(subscription.payload.status)}</td></tr>)}{planDetail.subscriptions.length === 0 ? <tr><td colSpan={4}>Sin suscripciones asociadas al plan.</td></tr> : null}</tbody></table></div></section></main> : null
  const subscriptionDetailView = subscriptionDetail ? <main className="app-shell detail-page"><button className="back-button" onClick={() => setSubscriptionDetail(null)}>Volver al listado VirtualPOS</button><p className="eyebrow">VIRTUALPOS / SUBSCRIPCIÓN</p><h2>{text(subscriptionDetail.subscription.payload.plan_name, subscriptionDetail.subscription.external_id)}</h2><section className="panel"><p className="eyebrow">FICHA DE LA SUBSCRIPCIÓN</p><dl className="field-list">{virtualPosSubscriptionFields.map((field) => <div key={field}><dt>{field}</dt><dd>{field === 'id' ? text(subscriptionDetail.subscription.payload.id, subscriptionDetail.subscription.external_id) : text(subscriptionDetail.subscription.payload[field])}</dd></div>)}</dl></section><section className="panel client-subscriptions"><p className="eyebrow">MÉTODO DE PAGO</p>{objectEntries(subscriptionDetail.payment_method).length ? <dl className="field-list">{objectEntries(subscriptionDetail.payment_method).map(([field, value]) => <div key={field}><dt>{field}</dt><dd>{text(value)}</dd></div>)}</dl> : <p>Sin método de pago disponible en staging.</p>}</section><section className="panel client-subscriptions"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Asociados a la subscripción</h3></div><span>{subscriptionDetail.charge_total} total</span></div><div className="table-wrap"><table><thead><tr><th>ID Cargo</th><th>Estado</th><th>Monto</th><th>Fecha de cargo</th></tr></thead><tbody>{subscriptionDetail.charges.map((charge) => <tr key={charge.id}><td>{text(charge.payload.id, charge.external_id)}</td><td>{text(charge.payload.status)}</td><td>{text(charge.payload.amount)}</td><td>{text(charge.payload.charge_date)}</td></tr>)}{subscriptionDetail.charges.length === 0 ? <tr><td colSpan={4}>Sin cargos asociados a la subscripción.</td></tr> : null}</tbody></table></div></section></main> : null
  const providerRecordDetailView = providerRecordDetail ? <main className="app-shell detail-page"><button className="back-button" onClick={() => setProviderRecordDetail(null)}>Volver al listado {title(providerRecordDetail.record.source)}</button><p className="eyebrow">{title(providerRecordDetail.record.source).toUpperCase()} / {resourceTitle(providerRecordDetail.record.resource_type).toUpperCase()}</p><h2>{text(providerRecordDetail.record.payload.name, text(providerRecordDetail.record.payload.id, providerRecordDetail.record.external_id))}</h2><section className="panel"><p className="eyebrow">FICHA COMPLETA</p><dl className="field-list">{Object.entries(providerRecordDetail.record.payload).map(([field, value]) => <div key={field}><dt>{field}</dt><dd>{text(value)}</dd></div>)}</dl></section>{providerRecordDetail.related.map((group) => <section className="panel client-subscriptions" key={group.resource_type}><div className="panel-heading"><div><p className="eyebrow">{group.label.toUpperCase()}</p><h3>Registros relacionados</h3></div><span>{group.items.length} total</span></div>{group.items.length ? <div className="table-wrap"><table><thead><tr><th>ID</th><th>Nombre</th><th>Estado</th><th>Monto</th></tr></thead><tbody>{group.items.map((item) => <tr key={item.id}><td><button className="record-link" onClick={() => void openProviderRecord(item.source, group.resource_type, item)}>{text(item.payload.id, item.external_id)}</button></td><td>{text(item.payload.name, text(nested(item.payload, 'client', 'name')))}</td><td>{text(item.payload.status)}</td><td>{text(item.payload.amount)}</td></tr>)}</tbody></table></div> : <p>Sin registros relacionados.</p>}</section>)}</main> : null
  const providerDetail = activeSection ? <main className="app-shell detail-page provider-page"><button className="back-button" onClick={() => showChannel(activeSection.source)}>Volver al resumen {title(activeSection.source)}</button><p className="eyebrow">{title(activeSection.source).toUpperCase()} / STAGING</p><h2>{activeSection.label}</h2><section className="panel provider-panel"><div className="panel-heading"><div><p className="eyebrow">SOURCE RECORDS</p><h3>Payloads saneados almacenados localmente</h3></div><span>{loading ? 'Cargando' : `${records.total} registros`}</span></div>{error ? <p className="error-message">{error}</p> : null}{!loading && !error && records.items.length === 0 ? <p>Sin registros sincronizados para este recurso.</p> : null}{records.items.length > 0 ? <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column.label}>{column.label}</th>)}</tr></thead><tbody>{records.items.map((record) => <tr key={record.id}>{columns.map((column) => <td key={column.label}>{activeSection.source === 'virtualpos' && activeSection.resource === 'client' && column.label === 'UUID' ? <button className="record-link" aria-label={`Ver ficha de cliente ${column.value(record)}`} onClick={() => void openVirtualPosClient(record)}>{column.value(record)}</button> : activeSection.source === 'virtualpos' && activeSection.resource === 'plan' && column.label === 'ID' ? <button className="record-link" aria-label={`Ver ficha de plan ${column.value(record)}`} onClick={() => void openVirtualPosPlan(record)}>{column.value(record)}</button> : activeSection.source === 'virtualpos' && activeSection.resource === 'subscription' && column.label === 'ID' ? <button className="record-link" aria-label={`Ver ficha de subscripción ${column.value(record)}`} onClick={() => void openVirtualPosSubscription(record)}>{column.value(record)}</button> : (activeSection.source === 'toku' || activeSection.source === 'payku') && column.label === 'ID' ? <button className="record-link" aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`} onClick={() => void openProviderRecord(activeSection.source, activeSection.resource, record)}>{column.value(record)}</button> : column.value(record)}</td>)}</tr>)}</tbody></table></div> : null}</section></main> : null
  const globalDashboard = <main className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark">CRM</span><div><p className="eyebrow">OPERACIONES RECURRENTES</p><h1>CRM Suscripciones</h1></div></div><div className="sync-state ready"><span />Staging local</div></header><section className="hero-panel"><div><p className="eyebrow">RESUMEN OPERATIVO</p><h2>Datos por canal,<br />antes de la BD Central.</h2></div><p className="sync-copy">Selecciona VirtualPOS, Toku o Payku para abrir su mini dashboard operativo.</p></section>{error ? <p className="error-message">{error}</p> : null}<section className="metrics" aria-label="Resumen de staging">{summary.sources.map((source, index) => <Metric key={source.source} label={title(source.source)} value={source.records} tone={['blue', 'violet', 'gold'][index]} />)}</section><section className="source-summary">{summary.sources.map((source) => <article className="panel" key={source.source}><div className="panel-heading"><div><p className="eyebrow">{title(source.source).toUpperCase()}</p><h3>{source.records} registros staging</h3></div><span className={`status-pill ${source.last_sync?.status === 'completed' ? '' : 'status-attention'}`}>{source.last_sync?.status ?? 'Sin sync'}</span></div><p className="resource-copy">{Object.entries(source.resources).map(([resource, count]) => `${resource}: ${count}`).join(' · ') || 'Sin recursos sincronizados.'}</p></article>)}</section></main>
  const content = detailLoading ? <main className="app-shell"><p className="muted-copy">Cargando ficha...</p></main> : clientDetailView ?? planDetailView ?? subscriptionDetailView ?? providerRecordDetailView ?? providerDetail ?? (channel ? channelLoading || !channelData ? <main className="app-shell"><p className="muted-copy">Cargando mini dashboard...</p></main> : <ChannelDashboardView data={channelData} mode={mode} year={year} onMode={setMode} onYear={setYear} onOpenResource={openChannelResource} /> : globalDashboard)

  return <div className="app-layout"><Sidebar activeSection={activeSection} channel={channel} openProvider={openProvider} onDashboard={showDashboard} onChannel={showChannel} onSection={showSection} onToggle={(provider) => setOpenProvider((open) => open === provider ? null : provider)} />{content}</div>
}

export default App
