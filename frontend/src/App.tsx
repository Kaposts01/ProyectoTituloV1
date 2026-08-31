import { type ReactNode, useEffect, useState } from 'react'
import './App.css'

type CardSummary = { reference_id?: string; status?: string; brand?: string; card_type?: string; issuer?: string; last4?: string }
type RecordItem = Record<string, unknown> & { id: string; external_id: string }
type SyncRun = { id: string; status: string; finished_at?: string; records_processed: number }
type ResourceKey = 'clients' | 'plans' | 'subscriptions' | 'charges' | 'payments'
type DashboardData = { clients: RecordItem[]; plans: RecordItem[]; subscriptions: RecordItem[]; charges: RecordItem[]; payments: RecordItem[]; syncRuns: SyncRun[] }
type SubscriptionDetail = { subscription: RecordItem; plan: RecordItem | null; charges: RecordItem[]; charge_total: number }
type RecordColumn = { label: string; value: (record: RecordItem) => string }
type ProviderRecord = Record<string, unknown>

const emptyDashboard: DashboardData = { clients: [], plans: [], subscriptions: [], charges: [], payments: [], syncRuns: [] }
const resources: { key: ResourceKey; label: string }[] = [
  { key: 'clients', label: 'Clientes' }, { key: 'plans', label: 'Planes' }, { key: 'subscriptions', label: 'Subscripciones' }, { key: 'charges', label: 'Cargos' }, { key: 'payments', label: 'Transacciones' },
]
const labels: Record<string, string> = {
  id: 'UUID interno', source: 'Fuente', external_id: 'UUID VirtualPOS', source_record_id: 'Registro staging', first_name: 'Nombre', last_name: 'Apellido', social_id: 'RUT', email: 'Correo', phone_number: 'Telefono', status: 'Estado', gender_id: 'Sexo', birth_date: 'Fecha nacimiento', provider_created_at: 'Fecha creacion', created_at: 'Creado', updated_at: 'Actualizado', name: 'Nombre', description: 'Descripcion', amount: 'Monto', currency: 'Moneda', plan_type: 'Tipo de plan', is_active: 'Activo en POS', service_id: 'Servicio', plan_external_id: 'Plan', automatic_renewal: 'Renovacion automatica', suscription_date: 'Fecha de inicio', canceled_at: 'Fecha de cancelacion', subscription_external_id: 'Suscripcion', charge_external_id: 'Cargo', charge_date: 'Fecha de cargo', payment_date: 'Fecha de pago', cards: 'Tarjetas',
}
const providerEndpoints: Record<string, string> = {
  'Toku / Clientes': '/api/v1/toku/customers',
  'Toku / Subscripciones': '/api/v1/toku/subscriptions',
  'Toku / Metodos de pago': '/api/v1/toku/payment-methods',
  'Toku / Deudas': '/api/v1/toku/invoices',
  'Toku / Transacciones': '/api/v1/toku/transactions',
  'Payku / Customers': '/api/v1/payku/clients',
  'Payku / Sususcription': '/api/v1/payku/subscriptions',
  'Payku / Sutransaction': '/api/v1/payku/transactions',
  'Payku / Suplan': '/api/v1/payku/plans',
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json() as Promise<T>
}

function text(value: unknown, fallback = 'Sin dato'): string {
  if (value === null || value === undefined || value === '') return fallback
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function clientName(client: RecordItem): string {
  return [text(client.first_name, ''), text(client.last_name, '')].filter(Boolean).join(' ') || text(client.external_id)
}

function amount(record: RecordItem): string {
  return record.amount ? `${text(record.amount)} ${text(record.currency, '')}` : 'Sin dato'
}

function activeLabel(value: unknown): string {
  return String(value).toLowerCase() === 'true' ? 'Activo' : 'Inactivo'
}

function activeInPos(value: unknown): string {
  return String(value).toLowerCase() === 'true' ? 'Si' : 'No'
}

function recordColumns(resource: ResourceKey): RecordColumn[] {
  const reference = (record: RecordItem) => text(record.name, text(record.service_id, text(record.external_id)))
  const status = (record: RecordItem) => text(record.status)
  if (resource === 'clients') return [{ label: 'Referencia', value: clientName }, { label: 'Estado', value: status }, { label: 'Correo', value: (record) => text(record.email) }, { label: 'Telefono', value: (record) => text(record.phone_number) }]
  if (resource === 'plans') return [{ label: 'Referencia', value: reference }, { label: 'Estado', value: (record) => activeLabel(record.is_active) }, { label: 'Monto', value: amount }, { label: 'Activo en POS', value: (record) => activeInPos(record.is_active) }]
  if (resource === 'subscriptions') return [{ label: 'ID', value: (record) => text(record.external_id) }, { label: 'Referencia', value: reference }, { label: 'Estado', value: status }, { label: 'Fecha de inicio', value: (record) => text(record.suscription_date) }, { label: 'Fecha de cancelacion', value: (record) => text(record.canceled_at) }]
  if (resource === 'charges') return [{ label: 'Referencia', value: reference }, { label: 'Estado', value: status }, { label: 'Monto', value: amount }, { label: 'Fecha de cargo', value: (record) => text(record.charge_date) }]
  return [{ label: 'Referencia', value: reference }, { label: 'Estado', value: status }, { label: 'Monto', value: amount }, { label: 'Fecha de pago', value: (record) => text(record.payment_date) }]
}

function providerRecords(payload: unknown): ProviderRecord[] {
  if (Array.isArray(payload)) return payload.filter((record): record is ProviderRecord => typeof record === 'object' && record !== null)
  if (!payload || typeof payload !== 'object') return []
  const response = payload as ProviderRecord
  const records = Object.values(response).find((value) => Array.isArray(value))
  return Array.isArray(records) ? records.filter((record): record is ProviderRecord => typeof record === 'object' && record !== null) : []
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <article className="metric-card"><span className={`metric-dot ${tone}`} /><p>{label}</p><strong>{value}</strong></article>
}

function BackButton({ onClick }: { onClick: () => void }) {
  return <button className="back-button" onClick={onClick}>Volver al dashboard</button>
}

function FieldList({ record, omit = [] }: { record: RecordItem; omit?: string[] }) {
  return <dl className="field-list">{Object.entries(record).filter(([key]) => !omit.includes(key)).map(([key, value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{text(value)}</dd></div>)}</dl>
}

function Sidebar({ futureSection, openProvider, onDashboard, onResource, onFuture, onToggleProvider }: { futureSection: string | null; openProvider: string | null; onDashboard: () => void; onResource: (resource: ResourceKey) => void; onFuture: (section: string) => void; onToggleProvider: (provider: string) => void }) {
  const virtualPosItems: { label: string; resource: ResourceKey }[] = [{ label: 'Clientes', resource: 'clients' }, { label: 'Planes', resource: 'plans' }, { label: 'Subscripciones', resource: 'subscriptions' }, { label: 'Cargos', resource: 'charges' }, { label: 'Transacciones', resource: 'payments' }]
  const futureGroups = [{ name: 'Toku', items: ['Clientes', 'Subscripciones', 'Metodos de pago', 'Deudas', 'Transacciones'] }, { name: 'Payku', items: ['Customers', 'Sususcription', 'Sutransaction', 'Suplan'] }, { name: 'TCH', items: ['Clientes', 'Subcripciones', 'Cobros'] }]
  return <aside className="sidebar"><button className="sidebar-brand" onClick={onDashboard}><span>VP</span><strong>CRM</strong></button><nav className="sidebar-nav" aria-label="Navegacion principal"><button className={!futureSection ? 'sidebar-item active' : 'sidebar-item'} onClick={onDashboard}>Dashboard</button><section className="sidebar-group"><button className="sidebar-toggle" aria-expanded={openProvider === 'VirtualPOS'} onClick={() => onToggleProvider('VirtualPOS')}>VirtualPOS <span>{openProvider === 'VirtualPOS' ? '-' : '+'}</span></button>{openProvider === 'VirtualPOS' ? virtualPosItems.map((item) => <button className="sidebar-item nested" key={item.resource} onClick={() => onResource(item.resource)}>{item.label}</button>) : null}</section>{futureGroups.map((group) => <section className="sidebar-group" key={group.name}><button className="sidebar-toggle" aria-expanded={openProvider === group.name} onClick={() => onToggleProvider(group.name)}>{group.name}<span>{openProvider === group.name ? '-' : '+'}</span></button>{openProvider === group.name ? group.items.map((item) => { const section = `${group.name} / ${item}`; return <button className={futureSection === section ? 'sidebar-item nested active' : 'sidebar-item nested'} key={section} onClick={() => onFuture(section)}>{item}</button> }) : null}</section>)}<button className={futureSection === 'Configuracion' ? 'sidebar-item active sidebar-config' : 'sidebar-item sidebar-config'} onClick={() => onFuture('Configuracion')}>Configuracion</button></nav></aside>
}

function App() {
  const [dashboard, setDashboard] = useState(emptyDashboard)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeResource, setActiveResource] = useState<ResourceKey>('clients')
  const [showRecords, setShowRecords] = useState(false)
  const [selectedClient, setSelectedClient] = useState<RecordItem | null>(null)
  const [selectedSubscription, setSelectedSubscription] = useState<SubscriptionDetail | null>(null)
  const [selectedRecord, setSelectedRecord] = useState<{ kind: ResourceKey; record: RecordItem } | null>(null)
  const [futureSection, setFutureSection] = useState<string | null>(null)
  const [openProvider, setOpenProvider] = useState<string | null>('VirtualPOS')
  const [providerPayload, setProviderPayload] = useState<unknown>(null)
  const [providerLoading, setProviderLoading] = useState(false)
  const [providerError, setProviderError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function loadDashboard() {
      try {
        const [clients, plans, subscriptions, charges, payments, syncRuns] = await Promise.all([getJson<RecordItem[]>('/api/v1/clients?limit=100'), getJson<RecordItem[]>('/api/v1/plans?limit=100'), getJson<RecordItem[]>('/api/v1/subscriptions?limit=100'), getJson<RecordItem[]>('/api/v1/charges?limit=100'), getJson<RecordItem[]>('/api/v1/payments?limit=100'), getJson<SyncRun[]>('/api/v1/sync-runs')])
        if (active) setDashboard({ clients, plans, subscriptions, charges, payments, syncRuns })
      } catch { if (active) setError('No se pudo conectar con la API local.') } finally { if (active) setLoading(false) }
    }
    void loadDashboard()
    return () => { active = false }
  }, [])

  useEffect(() => {
    const endpoint = futureSection ? providerEndpoints[futureSection] : undefined
    if (!endpoint) {
      setProviderPayload(null); setProviderError(null); setProviderLoading(false)
      return
    }
    let active = true
    setProviderLoading(true); setProviderError(null)
    getJson<unknown>(endpoint).then((payload) => {
      if (active) setProviderPayload(payload)
    }).catch(() => {
      if (active) setProviderError('No se pudo consultar este proveedor. Revisa su configuracion local.')
    }).finally(() => {
      if (active) setProviderLoading(false)
    })
    return () => { active = false }
  }, [futureSection])

  function resetViews() { setShowRecords(false); setSelectedClient(null); setSelectedSubscription(null); setSelectedRecord(null) }
  function showDashboard() { setFutureSection(null); resetViews() }
  function showResource(resource: ResourceKey) { setFutureSection(null); resetViews(); setActiveResource(resource); setShowRecords(true) }
  function showFuture(section: string) { resetViews(); setFutureSection(section) }
  function toggleProvider(provider: string) { setOpenProvider((open) => open === provider ? null : provider) }
  function page(content: ReactNode) { return <div className="app-layout"><Sidebar futureSection={futureSection} openProvider={openProvider} onDashboard={showDashboard} onResource={showResource} onFuture={showFuture} onToggleProvider={toggleProvider} />{content}</div> }

  async function openRecord(kind: ResourceKey, record: RecordItem) {
    try {
      if (kind === 'clients') setSelectedClient(await getJson<RecordItem>(`/api/v1/clients/${record.id}`))
      else if (kind === 'subscriptions') setSelectedSubscription(await getJson<SubscriptionDetail>(`/api/v1/subscriptions/${record.id}/detail`))
      else setSelectedRecord({ kind, record: await getJson<RecordItem>(`/api/v1/${kind}/${record.id}`) })
    } catch { setError('No se pudo cargar el detalle del registro.') }
  }

  if (futureSection) {
    const [provider, feature] = futureSection.split(' / ')
    const endpoint = providerEndpoints[futureSection]
    const records = providerRecords(providerPayload)
    const columns = records.length ? [...new Set(records.flatMap((record) => Object.keys(record)))].slice(0, 7) : []
    if (endpoint) return page(<main className="app-shell detail-page provider-page"><BackButton onClick={showDashboard} /><p className="eyebrow">{provider.toUpperCase()}</p><h2>{feature}</h2><section className="panel provider-panel"><div className="panel-heading"><div><p className="eyebrow">LECTURA DEL PROVEEDOR</p><h3>Datos entregados por su endpoint GET</h3></div><span>{providerLoading ? 'Cargando' : `${records.length} registros`}</span></div>{providerError ? <p className="error-message">{providerError}</p> : null}{!providerLoading && !providerError && records.length === 0 ? <p>El proveedor no devolvio registros para esta consulta.</p> : null}{records.length > 0 ? <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{records.map((record, index) => <tr key={String(record.id ?? record.uuid ?? index)}>{columns.map((column) => <td key={column}>{text(record[column])}</td>)}</tr>)}</tbody></table></div> : null}</section></main>)
    return page(<main className="app-shell future-page"><p className="eyebrow">{provider.toUpperCase()}</p><section className="future-panel"><span className="future-mark">+</span><p className="eyebrow">EN CONSTRUCCION</p><h2>{feature ?? provider}</h2><p>Esta seccion esta reservada para la futura integracion de {provider}. No realiza conexiones ni operaciones con proveedores.</p></section></main>)
  }

  if (selectedClient) {
    const cards = Array.isArray(selectedClient.cards) ? selectedClient.cards as CardSummary[] : []
    return page(<main className="app-shell detail-page"><BackButton onClick={() => setSelectedClient(null)} /><p className="eyebrow">CLIENTE</p><h2>{clientName(selectedClient)}</h2><section className="detail-grid"><article className="panel"><p className="eyebrow">DATOS DEL CLIENTE</p><FieldList record={selectedClient} omit={['id', 'source', 'source_record_id', 'cards', 'created_at', 'updated_at']} /></article><aside className="panel note-panel"><p className="eyebrow">RELACIONES</p><h3>Sin inferencias</h3><p>VirtualPOS no entrega un UUID de cliente dentro de las suscripciones. Esta vista no asocia registros por correo o nombre.</p></aside></section><section className="panel"><div className="panel-heading"><div><p className="eyebrow">TARJETAS</p><h3>Tarjetas asociadas</h3></div><span>{cards.length} total</span></div><div className="table-wrap"><table><thead><tr><th>Marca</th><th>Ultimos 4</th><th>Tipo</th><th>Emisor</th><th>Estado</th></tr></thead><tbody>{cards.map((card, index) => <tr key={card.reference_id ?? index}><td>{card.brand ?? 'Sin marca'}</td><td>{card.last4 ? `**** ${card.last4}` : 'No disponible'}</td><td>{card.card_type ?? 'Sin tipo'}</td><td>{card.issuer ?? 'Sin emisor'}</td><td><span className="status-pill">{card.status ?? 'Sin estado'}</span></td></tr>)}{cards.length === 0 ? <tr><td colSpan={5}>Sin tarjetas asociadas.</td></tr> : null}</tbody></table></div></section></main>)
  }

  if (selectedSubscription) {
    const { subscription, plan, charges, charge_total } = selectedSubscription
    return page(<main className="app-shell detail-page"><BackButton onClick={() => setSelectedSubscription(null)} /><p className="eyebrow">SUSCRIPCION</p><h2>{text(subscription.service_id, text(subscription.external_id))}</h2><section className="detail-grid"><article className="panel"><p className="eyebrow">DATOS DE SUSCRIPCION</p><FieldList record={subscription} omit={['id', 'source', 'source_record_id', 'created_at', 'updated_at']} /></article><aside className="panel note-panel"><p className="eyebrow">PLAN ASOCIADO</p><h3>{plan ? text(plan.name, text(plan.external_id)) : 'Sin plan'}</h3><p>{plan ? `${text(plan.amount)} ${text(plan.currency, '')}` : 'No hay plan confirmado.'}</p></aside></section><section className="panel"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Historial reciente</h3></div><span>{charge_total} total</span></div><div className="table-wrap"><table><thead><tr><th>Referencia</th><th>Monto</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{charges.map((charge) => <tr key={charge.id}><td>{text(charge.external_id)}</td><td>{amount(charge)}</td><td>{text(charge.charge_date)}</td><td><span className="status-pill">{text(charge.status)}</span></td></tr>)}{charges.length === 0 ? <tr><td colSpan={4}>Sin cargos asociados.</td></tr> : null}</tbody></table></div></section></main>)
  }

  if (selectedRecord) {
    const { kind, record } = selectedRecord
    const resource = resources.find((item) => item.key === kind)
    return page(<main className="app-shell detail-page"><BackButton onClick={() => setSelectedRecord(null)} /><p className="eyebrow">{resource?.label.toUpperCase()}</p><h2>{text(record.name, text(record.external_id))}</h2><section className="panel"><p className="eyebrow">CAMPOS DISPONIBLES</p><FieldList record={record} omit={['cards']} /></section></main>)
  }

  const latestRun = dashboard.syncRuns[0]
  const activeRecords = dashboard[activeResource]
  const activeLabel = resources.find((item) => item.key === activeResource)?.label ?? ''
  const columns = recordColumns(activeResource)
  const syncLabel = loading ? 'Cargando datos' : latestRun?.status === 'completed' ? 'Sincronizacion al dia' : 'Revisar sincronizacion'

  if (showRecords) {
    return page(<main className="app-shell detail-page"><BackButton onClick={showDashboard} /><p className="eyebrow">EXPLORADOR CRM</p><h2>Registros sincronizados</h2><nav className="resource-tabs" aria-label="Recursos CRM">{resources.map((resource) => <button className={activeResource === resource.key ? 'active' : ''} key={resource.key} onClick={() => setActiveResource(resource.key)}>{resource.label}<span>{dashboard[resource.key].length}</span></button>)}</nav><section className="panel records-panel"><div className="panel-heading"><div><p className="eyebrow">{activeLabel.toUpperCase()}</p><h3>Selecciona un registro para ver su GET de detalle</h3></div><span>{activeRecords.length} cargados</span></div><div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column.label}>{column.label}</th>)}</tr></thead><tbody>{activeRecords.map((record) => <tr key={record.id}>{columns.map((column, index) => <td key={column.label}>{index === 0 ? <button className="record-link" onClick={() => void openRecord(activeResource, record)}>{column.value(record)}</button> : column.value(record)}</td>)}</tr>)}{activeRecords.length === 0 ? <tr><td colSpan={columns.length}>Sin registros disponibles.</td></tr> : null}</tbody></table></div></section></main>)
  }

  return page(<main className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark">VP</span><div><p className="eyebrow">OPERACIONES RECURRENTES</p><h1>CRM Suscripciones</h1></div></div><div className={`sync-state ${latestRun?.status === 'completed' ? 'ready' : 'attention'}`}><span />{syncLabel}</div></header><section className="hero-panel"><div><p className="eyebrow">VIRTUALPOS SANDBOX</p><h2>Visibilidad operativa,<br />sin tocar el proveedor.</h2></div><p className="sync-copy">{latestRun ? `${latestRun.records_processed} cambios en la ultima ejecucion.` : 'Aun no hay ejecuciones registradas.'}</p></section>{error ? <p className="error-message">{error}</p> : null}<section className="metrics" aria-label="Resumen CRM"><Metric label="Clientes" value={dashboard.clients.length} tone="blue" /><Metric label="Planes" value={dashboard.plans.length} tone="violet" /><Metric label="Suscripciones" value={dashboard.subscriptions.length} tone="gold" /><Metric label="Cargos" value={dashboard.charges.length} tone="orange" /><Metric label="Pagos" value={dashboard.payments.length} tone="green" /></section><section className="panel explorer-card"><div><p className="eyebrow">REGISTROS</p><h3>Explora todos los datos CRM</h3><p>Clientes, planes, suscripciones, cargos y pagos con sus campos de detalle.</p></div><button className="primary-button" onClick={() => showResource('clients')}>Ver registros</button></section><section className="workspace"><article className="panel panel-wide"><div className="panel-heading"><div><p className="eyebrow">CLIENTES</p><h3>Recientemente actualizados</h3></div><button className="text-button" onClick={() => showResource('clients')}>Ver todos</button></div><div className="table-wrap"><table><thead><tr><th>Cliente</th><th>Correo</th><th>Estado</th></tr></thead><tbody>{dashboard.clients.slice(0, 5).map((client) => <tr key={client.id}><td><button className="record-link" onClick={() => void openRecord('clients', client)}>{clientName(client)}</button></td><td>{text(client.email)}</td><td><span className="status-pill">{text(client.status)}</span></td></tr>)}{dashboard.clients.length === 0 ? <tr><td colSpan={3}>No hay clientes sincronizados.</td></tr> : null}</tbody></table></div></article><aside className="panel sync-panel"><p className="eyebrow">ULTIMA SINCRONIZACION</p><strong>{latestRun?.status ?? 'Sin ejecuciones'}</strong><p>{latestRun?.finished_at ? new Date(latestRun.finished_at).toLocaleString() : 'Ejecuta la sincronizacion Sandbox para comenzar.'}</p><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">Abrir Swagger local</a></aside></section></main>)
}

export default App
