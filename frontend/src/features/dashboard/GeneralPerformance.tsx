import { useState, type ReactNode } from 'react';
import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { annualSeries, channels, historyWindow, monthNames, type PerformanceSnapshot } from './performanceModel';
import './GeneralPerformance.css';

const money = (v: number | null | undefined) => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`;
const millions = (v: number | null | undefined) => v == null ? '—' : Math.abs(v) < 1e6 ? money(v) : `${v < 0 ? '-' : ''}$${(Math.abs(v) / 1e6).toLocaleString('es-CL', { maximumFractionDigits: 1 })} MM`;
const number = (v: number | null | undefined) => v == null ? '—' : v.toLocaleString('es-CL');
const pct = (v: number | null | undefined) => v == null ? '—' : `${v.toLocaleString('es-CL', { maximumFractionDigits: 2 })} %`;
const palette = ['#39c7e6', '#190e69', '#0e849c', '#9b8be8'];
function Card({ title, value, caption, tone = '', children }: { title: string; value: string; caption: string; tone?: string; children?: ReactNode }) {
  return <article className={`performance-card ${tone}`}><p>{title}</p><strong>{value}</strong>{children}<small>{caption}</small></article>;
}
function Plot({ title, subtitle, children, table, wide = false }: { title: string; subtitle: string; children: ReactNode; table: ReactNode; wide?: boolean }) {
  return <article className={`performance-plot ${wide ? 'wide' : ''}`}><h3>{title}</h3><p>{subtitle}</p><div className="performance-chart">{children}</div><details><summary>Ver datos</summary><div className="table-wrap">{table}</div></details></article>;
}
export function GeneralPerformance({ data }: { data: PerformanceSnapshot }) {
  const [selected, setSelected] = useState(data.default_period);
  const [range, setRange] = useState<'12m' | 'year' | 'all'>('12m');
  const [goals, setGoals] = useState<Record<string, string>>({});
  const period = data.monthly.some(m => m.period === selected) ? selected : data.default_period;
  const year = period.slice(0, 4);
  const row = data.monthly.find(m => m.period === period)!;
  const previousIndex = data.monthly.findIndex(m => m.period === period) - 1;
  const previous = data.monthly[previousIndex];
  const goalValue = Number(goals[year] ?? '');
  const goal = Number.isFinite(goalValue) && goalValue > 0 ? goalValue : null;
  const annual = annualSeries(data.monthly, period, goal);
  const selectedAnnual = annual[row.month - 1];
  const accumulated = selectedAnnual.actual;
  const monthlyTarget = goal != null ? goal / 12 : null;
  const gap = goal != null && accumulated != null ? accumulated - goal : null;
  const history = historyWindow(data.monthly, period, range).map(m => ({ ...m, label: `${monthNames[m.month - 1]} '${String(m.year).slice(-2)}`, ...m.channels, monthlyTarget: monthlyTarget != null && m.year === Number(year) ? monthlyTarget : null }));
  const delta = row.revenue != null && previous?.revenue != null ? row.revenue - previous.revenue : null;
  const excluded = Object.values(data.excluded).reduce((sum, count) => sum + count, 0);
  const chartTooltip = (v: unknown) => money(Number(v));
  return <section className="performance-dashboard" aria-label="Indicadores mensuales generales">
    <div className="performance-banner"><p>ANÁLISIS MENSUAL · DATOS CENTRALIZADOS</p><h2>Indicadores de recaudación y suscripciones</h2><span>Corte de datos: {data.as_of} · Montos en CLP · {row.partial_month ? 'Mes en curso, parcial' : 'Mes calendario cerrado'}</span></div>
    <div className="performance-controls"><div><h3>{new Date(`${period}-02T12:00:00`).toLocaleDateString('es-CL', { month: 'long', year: 'numeric' })}</h3><p>Resultados observados y comparación con el mes anterior</p></div>
      <label>Mes<select aria-label="Mes de indicadores generales" value={period} onChange={e => setSelected(e.target.value)}>{[...data.monthly].reverse().map(m => <option key={m.period} value={m.period}>{monthNames[m.month - 1]} {m.year}</option>)}</select></label>
      <label>Meta anual de análisis {year} (CLP)<input aria-label="Meta anual de análisis en CLP" type="number" min="1" step="1" placeholder="Sin meta definida" value={goals[year] ?? ''} onChange={e => setGoals(g => ({ ...g, [year]: e.target.value }))} /><small>Escenario local; no modifica la meta institucional.</small></label>
    </div>
    <div className="performance-cards">
      <Card title="Suscripciones activas" value={number(row.active)} caption={`Base reconstruida al cierre · ${previous?.active != null && row.active != null ? `${number(row.active - previous.active)} vs mes anterior` : 'Sin comparación previa'}`} tone="featured" />
      <Card title="Recaudación observada" value={millions(row.revenue)} caption={monthlyTarget != null && row.revenue != null ? `${pct(row.revenue / monthlyTarget * 100)} de ${millions(monthlyTarget)} · meta lineal del mes` : monthlyTarget != null ? 'Sin observaciones para comparar con la meta' : 'Pagos aceptados · sin meta definida'} tone="featured">
        {monthlyTarget != null && row.revenue != null && <progress aria-label="Avance de recaudación mensual" value={row.revenue} max={Math.max(monthlyTarget, row.revenue, 1)} />}
      </Card>
      <Card title={`Acumulado ${year} a ${monthNames[row.month - 1]}`} value={millions(accumulated)} caption={selectedAnnual.incomplete ? 'Suma parcial: hay meses sin observaciones' : goal != null ? `${pct((accumulated ?? 0) / goal * 100)} de ${millions(goal)} al año` : 'Suma observada del año · sin meta definida'} />
      <Card title="Diferencia vs meta anual" value={millions(gap)} caption={goal != null ? `Ritmo lineal a la fecha: ${millions(selectedAnnual.target)}` : 'Ingresa una meta para comparar'} tone={gap != null && gap < 0 ? 'negative' : ''} />
      <Card title="Activaciones" value={number(row.activations)} caption="Suscripciones con fecha de inicio en el mes" />
      <Card title="Bajas" value={number(row.cancellations)} caption="Suscripciones con fecha de término en el mes" tone="negative" />
      <Card title="Crecimiento neto" value={row.net_growth != null && row.net_growth > 0 ? `+${number(row.net_growth)}` : number(row.net_growth)} caption="Activaciones − bajas del mes" />
      <Card title="Churn mensual" value={pct(row.churn)} caption={`Bajas de la base inicial ÷ ${number(row.opening)} suscripciones. Sin base: no disponible.`} />
      <Card title="Variación de recaudación" value={millions(delta)} caption="Diferencia respecto del mes calendario anterior" />
      <Card title="Monto rechazado" value={millions(row.rejected_amount)} caption="Intentos rechazados; puede incluir reintentos" tone="negative" />
      <Card title="Efectividad por monto" value={pct(row.collection_rate)} caption="Aceptado ÷ (aceptado + rechazado), según evidencia local" />
    </div>
    <details className="performance-coverage"><summary>Cobertura parcial · definición de indicadores</summary><p>{data.coverage}</p><p>La base cuenta suscripciones por origen, no socios únicos. Churn y movimientos usan únicamente intervalos reconstruibles. {number(excluded)} registros excluidos por fecha, moneda o intervalo no verificable. Las metas se distribuyen en doce meses; la proyección es un escenario, no una predicción.</p><ul>{Object.entries(data.excluded).map(([reason, count]) => <li key={reason}>{({ invalid_amount: 'Monto inválido', undated_or_future_payments: 'Pago futuro o sin fecha', other_or_missing_currency: 'Moneda distinta de CLP o ausente', subscriptions_without_valid_interval: 'Suscripción sin intervalo verificable', invalid_or_future_controls: 'Control vacío, inválido o futuro' } as Record<string, string>)[reason] ?? reason}: {number(count)}</li>)}</ul></details>
    <div className="performance-evolution"><h3>Evolución</h3><div className="mode-switch" aria-label="Rango de evolución">{([['12m', 'Últimos 12 meses'], ['year', `Año ${year}`], ['all', 'Todo']] as const).map(([value, label]) => <button key={value} className={range === value ? 'active' : ''} aria-pressed={range === value} onClick={() => setRange(value)}>{label}</button>)}</div></div>
    <div className="performance-plots">
      <Plot wide title="Recaudación observada por canal" subtitle="Pagos aceptados · la línea punteada indica la meta mensual de análisis" table={<table><thead><tr><th>Mes</th>{channels.map(ch => <th key={ch}>{ch}</th>)}<th>Total CLP</th></tr></thead><tbody>{history.map(m => <tr key={m.period}><td>{m.label}</td>{channels.map(ch => <td key={ch}>{money(m.channels[ch])}</td>)}<td>{money(m.revenue)}</td></tr>)}</tbody></table>}>
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={history} margin={{ left: 12, right: 16, top: 12 }}><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="label" /><YAxis width={76} tickFormatter={v => `$${Number(v) / 1e6} MM`} /><Tooltip formatter={chartTooltip} /><Legend />{channels.map((ch, i) => <Bar key={ch} dataKey={ch} stackId="income" fill={palette[i]} maxBarSize={44} />)}{goal != null && <Line dataKey="monthlyTarget" name="Meta del mes" stroke="var(--text-1)" strokeDasharray="5 5" dot={false} />}</ComposedChart></ResponsiveContainer>
      </Plot>
      <Plot wide title={`Ingreso acumulado ${year}${goal != null ? ` frente a ${millions(goal)}` : ''}`} subtitle="Acumulado observado · ritmo meta = anual ÷ 12 · proyección = promedio de meses cerrados, solo con evidencia desde enero" table={<table><thead><tr><th>Mes</th><th>Acumulado CLP</th><th>Proyección CLP</th><th>Ritmo meta CLP</th></tr></thead><tbody>{annual.map(m => <tr key={m.month}><td>{m.label}</td><td>{money(m.actual)}</td><td>{money(m.projected)}</td><td>{money(m.target)}</td></tr>)}</tbody></table>}>
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={annual} margin={{ left: 12, right: 16, top: 12 }}><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="label" /><YAxis width={76} tickFormatter={v => `$${Number(v) / 1e6} MM`} /><Tooltip formatter={chartTooltip} /><Legend /><Area dataKey="actual" name="Real acumulado" stroke="#39c7e6" fill="#39c7e6" fillOpacity={0.16} strokeWidth={3} connectNulls={false} /><Line dataKey="projected" name="Proyección estimada" stroke="#8c8c8c" strokeDasharray="3 4" dot={false} connectNulls={false} />{goal != null && <Line dataKey="target" name="Ritmo meta" stroke="#6a59cf" strokeDasharray="6 4" dot={false} />}</ComposedChart></ResponsiveContainer>
      </Plot>
      <Plot title="Suscripciones activas" subtitle="Base reconstruida al cierre de cada mes; mes actual al corte" table={<table><thead><tr><th>Mes</th><th>Suscripciones activas</th></tr></thead><tbody>{history.map(m => <tr key={m.period}><td>{m.label}</td><td>{number(m.active)}</td></tr>)}</tbody></table>}>
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={history}><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="label" /><YAxis width={58} /><Tooltip /><Area dataKey="active" name="Suscripciones activas" stroke="#39c7e6" fill="#39c7e6" fillOpacity={0.16} strokeWidth={3} connectNulls={false} /></ComposedChart></ResponsiveContainer>
      </Plot>
      <Plot title="Activaciones y bajas" subtitle="Suscripciones por mes · línea = crecimiento neto" table={<table><thead><tr><th>Mes</th><th>Activaciones</th><th>Bajas</th><th>Neto</th></tr></thead><tbody>{history.map(m => <tr key={m.period}><td>{m.label}</td><td>{number(m.activations)}</td><td>{number(m.cancellations)}</td><td>{number(m.net_growth)}</td></tr>)}</tbody></table>}>
        <ResponsiveContainer width="100%" height="100%"><ComposedChart data={history}><CartesianGrid stroke="var(--border-subtle)" vertical={false} /><XAxis dataKey="label" /><YAxis width={58} /><Tooltip /><Legend /><Bar dataKey="activations" name="Activaciones" fill="#39c7e6" /><Bar dataKey="cancellations" name="Bajas" fill="#c21872" /><Line dataKey="net_growth" name="Crecimiento neto" stroke="var(--text-1)" strokeWidth={2} dot={false} /></ComposedChart></ResponsiveContainer>
      </Plot>
    </div>
  </section>;
}
