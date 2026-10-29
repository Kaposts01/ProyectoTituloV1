import { ChannelChart } from "../../components/ChannelChart";
import { ChannelKpiStrip } from "../../components/ChannelKpiStrip";
import { KpiCard } from "../../components/KpiCard";
import { CrecimientoMensualChart, ChurnMensualChart } from "../../MonthlyStatusChart";
import { Metric } from "../dashboard/Metric";
import { OperationalAlerts } from "../dashboard/OperationalAlerts";
import { activationVsChurnChart, statusStackedChart, tchSourceNote } from "../dashboard/channelCharts";
import { normalizeKpis } from "../shared/kpis";
import { aggregateChurn, defaultYear } from "../shared/utils";
import { ExportButton } from "../shared/ExportButton";
import { tchExportTarget } from "../shared/exportMapping";
import type { TchState } from "./useTch";

/**
 * Contenido de las vistas TCH (resumen, listas y fichas). Se invoca como función desde AppCore
 * (no como elemento) a propósito: así un fallo de render sigue propagándose a AppCore igual que
 * antes de la extracción (ver el hallazgo de la ficha de suscripción en docs/engineering/appcore-extraction.md).
 */
export function renderTchContent({ tch, showTch, showTchSuscripcion, onReport, can }: {
  tch: TchState;
  showTch: (view: "summary" | "clientes" | "suscripciones" | "transacciones") => void;
  showTchSuscripcion: (numeroFicha: number) => void;
  onReport: (scope: string) => void;
  can?: (permission: string) => boolean;
}) {
  const {
    tchView,
    tchRefreshing,
    tchSummary,
    tchSuscripciones,
    tchTransacciones,
    tchClientes,
    tchLoading,
    tchError,
    tchSusPage,
    setTchSusPage,
    tchTransPage,
    setTchTransPage,
    tchSusFiltroEstado,
    setTchSusFiltroEstado,
    tchClienteFiltro,
    setTchClienteFiltro,
    tchClientesPage,
    setTchClientesPage,
    tchTransFiltroPeriodo,
    setTchTransFiltroPeriodo,
    tchMode,
    setTchMode,
    tchYear,
    setTchYear,
    tchSuscripcionDetail,
    tchTransaccionDetail,
    tchClienteDetail,
    showTchTransaccion,
    showTchCliente,
  } = tch;
  const tchExportButton = (view: "clientes" | "suscripciones" | "transacciones", filters: { nombre?: string; estado?: string; periodo?: string }, page: number, pageSize: number) => {
    const target = tchExportTarget(view, filters);
    if (target.viewPermission && can && !can(target.viewPermission)) return null;
    return (
      <ExportButton
        entity={target.entity}
        canal={target.canal}
        params={target.params}
        window={{ offset: (page - 1) * pageSize, limit: pageSize }}
        canPii={can?.("export.pii")}
      />
    );
  };
  return tchView ? (
    tchLoading ? (
      <main className="app-shell"><p className="muted-copy">Cargando datos TCH...</p></main>
    ) : tchError ? (
      <main className="app-shell"><p className="error-message">{tchError}</p></main>
    ) : tchView === "summary" && tchSummary ? (
      <main className="app-shell channel-dashboard-page">
        <p className="eyebrow">TCH / CANAL</p>
        <header className="channel-hero">
          <div>
            <h2>Resumen operativo {tchRefreshing && <span className="refreshing-badge">⟳ Actualizando</span>}</h2>
            <p>Datos cargados desde reportes Excel mensuales vía ETL.</p>
          </div>
          <div className="channel-hero-controls">
            <div className="dashboard-controls">
              <div className="mode-switch">
                <button className={tchMode === "count" ? "active" : ""} onClick={() => setTchMode("count")}>Cantidad</button>
                <button className={tchMode === "amount" ? "active" : ""} onClick={() => setTchMode("amount")}>Monto</button>
              </div>
              {tchSummary.years.length ? (
                <select aria-label="Año TCH" value={tchYear ?? defaultYear(tchSummary.years) ?? tchSummary.years[0]} onChange={(event) => setTchYear(Number(event.target.value))}>
                  {tchSummary.years.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
                </select>
              ) : null}
              <button className="sync-btn sync-btn-secondary" onClick={() => onReport("tch")}>Generar reporte</button>
            </div>
            {tchSummary.ultimo_etl.started_at ? (
              <>
              <div className={`sync-state ${tchSummary.ultimo_etl.status === "completed" ? "ready" : "attention"}`}>
                <span />{tchSummary.ultimo_etl.status ?? "Sin ETL"}
              </div>
              <p className="muted-copy" style={{ fontSize: "0.78rem" }}>
                Último ETL: {tchSummary.ultimo_etl.started_at?.slice(0, 10)} · {(tchSummary.ultimo_etl.records_upserted ?? 0).toLocaleString("es-CL")} registros
              </p>
              </>
            ) : null}
          </div>
        </header>
        <section className="metrics provider-metrics" aria-label="KPIs TCH">
          <Metric label="Suscripciones vigentes" value={tchSummary.suscripciones.vigentes} tone="green" amount={tchSummary.suscripciones.monto_vigentes} mode={tchMode} />
          <Metric label="Suscripciones eliminadas" value={tchSummary.suscripciones.eliminadas} tone="orange" amount={tchSummary.suscripciones.monto_eliminadas} mode={tchMode} />
          <Metric label="Total suscripciones" value={tchSummary.suscripciones.total} tone="blue" amount={tchSummary.suscripciones.monto_total} mode={tchMode} />
          <Metric label="Total transacciones" value={tchSummary.transacciones.total} tone="violet" amount={tchSummary.transacciones.monto} mode={tchMode} />
        </section>
        <ChannelKpiStrip kpis={normalizeKpis("tch", tchSummary.kpis, tchSummary.churn_window_label)} ariaLabel="KPIs financieros TCH" />
        <section className="metrics kpi-metrics" aria-label="KPIs transacciones TCH">
          <KpiCard label="Aceptadas" value={tchSummary.transacciones.aceptadas} format="count" caption="Transacciones cobradas" />
          <KpiCard label="Rechazadas" value={tchSummary.transacciones.rechazadas} format="count" caption="Transacciones fallidas" />
          <KpiCard label="Tasa de rechazo" value={tchSummary.transacciones.tasa_rechazo_pct} format="percent" caption="Rechazadas / total" emptyCaption="Sin base para calcular" />
        </section>
        <section className="extended-charts">
          {(() => {
            const tx = statusStackedChart(tchSummary.transacciones_mensuales, tchMode);
            const note = tchSourceNote(tchSummary.transacciones_fuente);
            return tx.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Transacciones mensuales</h3></div></div>
                <ChannelChart series={tx.series} data={tx.rows} kind="stacked" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de transacciones mensuales de TCH por estado" />
                {note ? <p className="muted-copy">{note}</p> : null}
              </article>
            ) : null;
          })()}
          {(() => {
            const ab = activationVsChurnChart(tchSummary.activaciones_mensuales, tchSummary.bajas_mensuales, tchMode);
            return ab.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas vs bajas</h3></div></div>
                <ChannelChart series={ab.series} data={ab.rows} kind="grouped" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de altas y bajas mensuales de suscripciones TCH" />
              </article>
            ) : null;
          })()}
          {tchSummary.activaciones_mensuales?.length && tchSummary.bajas_mensuales?.length ? (
            <>
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
                <CrecimientoMensualChart
                  activaciones={tchSummary.activaciones_mensuales}
                  caidas={aggregateChurn(tchSummary.bajas_mensuales)}
                  year={tchYear}
                  mode={tchMode}
                />
              </article>
            </>
          ) : null}
          {tchSummary.churn_rate_monthly.length ? (
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
              <ChurnMensualChart data={tchSummary.churn_rate_monthly} year={tchYear} />
            </article>
          ) : null}
        </section>
        <OperationalAlerts alerts={tchSummary.alerts ?? []} />
        <section className="panel channel-resources">
          <div><p className="eyebrow">EXPLORAR TCH</p><h3>Vistas disponibles</h3></div>
          <div>
            <button onClick={() => showTch("suscripciones")}>Suscripciones<span>{tchSummary.suscripciones.total}</span></button>
            <button onClick={() => showTch("transacciones")}>Transacciones<span>{tchSummary.transacciones.total}</span></button>
          </div>
        </section>
      </main>
    ) : tchView === "cliente-detalle" && tchClienteDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("clientes")}>← Clientes TCH</button>
        <p className="eyebrow">TCH / CLIENTE</p>
        <header className="detail-header"><div><h2>{[tchClienteDetail.nombre, tchClienteDetail.apellido].filter(Boolean).join(" ") || "Cliente TCH"}</h2><p>{tchClienteDetail.rut}</p></div></header>
        <section className="detail-grid"><article className="panel"><h3>Datos personales</h3><dl><dt>RUT</dt><dd>{tchClienteDetail.rut}</dd><dt>Fecha de nacimiento</dt><dd>{tchClienteDetail.fecha_nacimiento ?? "—"}</dd><dt>Profesión</dt><dd>{tchClienteDetail.profesion ?? "—"}</dd><dt>Tipo de socio</dt><dd>{tchClienteDetail.tipo_socio ?? "—"}</dd></dl></article><article className="panel"><h3>Contacto</h3><dl><dt>Email</dt><dd>{tchClienteDetail.email ?? "—"}</dd><dt>Teléfono</dt><dd>{tchClienteDetail.telefono ?? "—"}</dd><dt>Dirección</dt><dd>{tchClienteDetail.direccion ?? "—"}</dd><dt>Comuna</dt><dd>{tchClienteDetail.comuna ?? "—"}</dd><dt>Ciudad</dt><dd>{tchClienteDetail.ciudad ?? "—"}</dd></dl></article><article className="panel"><h3>Mandatos</h3><p className="metric-value">{(tchClienteDetail.suscripciones ?? []).length.toLocaleString("es-CL")}</p><p className="muted-copy">Suscripciones TCH asociadas</p></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Mandatos asociados</h3></div></div><div className="table-wrap"><table><thead><tr><th>Ficha</th><th>Inicio</th><th>Fin</th><th>Monto</th><th>Estado</th><th>Estado sec.</th><th>Último cobro</th></tr></thead><tbody>{(tchClienteDetail.suscripciones ?? []).map((s) => <tr key={s.id}><td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td><td>{s.fecha_activacion ?? "—"}</td><td>{s.fecha_fin ?? "—"}</td><td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td><td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td><td><span className={`badge badge-${s.secondary_status === "cobrable" ? "green" : s.secondary_status === "incobrable" ? "orange" : s.secondary_status === "inactiva" ? "gray" : "blue"}`}>{s.secondary_status}</span></td><td>{s.last_paid_date ? s.last_paid_date.slice(0, 10) : "—"}</td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "suscripcion-detalle" && tchSuscripcionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("suscripciones")}>← Suscripciones TCH</button>
        <p className="eyebrow">TCH / SUSCRIPCIÓN</p>
        <header className="detail-header"><div><h2>Ficha {tchSuscripcionDetail.numero_ficha}</h2><p>Mandato físico e historial de cargos.</p></div><span className={`status-pill${tchSuscripcionDetail.estado === "VIGENTE" ? "" : " status-attention"}`}>{tchSuscripcionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Mandato</h3><dl><dt>Inicio</dt><dd>{tchSuscripcionDetail.fecha_activacion ?? "—"}</dd><dt>Fin</dt><dd>{tchSuscripcionDetail.fecha_fin ?? "—"}</dd><dt>Motivo</dt><dd>{tchSuscripcionDetail.razon_baja ?? "—"}</dd><dt>Monto (CLP)</dt><dd>{(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto) ? `$${Number(tchSuscripcionDetail.equivalente_pesos || tchSuscripcionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Banco</dt><dd>{tchSuscripcionDetail.banco_nombre ?? "—"}</dd><dt>RUT cliente</dt><dd>{tchSuscripcionDetail.cliente_rut ?? "—"}</dd><dt>Último cobro</dt><dd>{tchSuscripcionDetail.last_paid_date ? tchSuscripcionDetail.last_paid_date.slice(0, 10) : "—"}</dd><dt>Estado sec.</dt><dd><span className={`badge badge-${tchSuscripcionDetail.secondary_status === "cobrable" ? "green" : tchSuscripcionDetail.secondary_status === "incobrable" ? "orange" : tchSuscripcionDetail.secondary_status === "inactiva" ? "gray" : "blue"}`}>{tchSuscripcionDetail.secondary_status}</span></dd></dl></article><article className="panel"><h3>Captación</h3><dl><dt>Origen</dt><dd>{tchSuscripcionDetail.origen ?? "—"}</dd><dt>Centro de costo</dt><dd>{tchSuscripcionDetail.centro_costo ?? "—"}</dd><dt>Captador</dt><dd>{tchSuscripcionDetail.captador ?? "—"}</dd><dt>Mandato</dt><dd>{tchSuscripcionDetail.numero_mandato ?? "—"}</dd><dt>Tipo de cuenta</dt><dd>{tchSuscripcionDetail.tipo_cuenta ?? "—"}</dd></dl></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Historial</h3></div></div><div className="table-wrap"><table><thead><tr><th>Período</th><th>Monto</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{tchSuscripcionDetail.transacciones.map((t) => <tr key={t.id}><td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.periodo ?? "—"}</button></td><td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td><td>{t.fecha_cargo ?? "—"}</td><td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "transaccion-detalle" && tchTransaccionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("transacciones")}>← Transacciones TCH</button>
        <p className="eyebrow">TCH / TRANSACCIÓN</p>
        <header className="detail-header"><div><h2>Cargo {tchTransaccionDetail.periodo ?? "sin período"}</h2><p>Ficha {tchTransaccionDetail.numero_ficha}</p></div><span className={`status-pill${tchTransaccionDetail.estado === "ACEPTADA" ? "" : " status-attention"}`}>{tchTransaccionDetail.estado}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Detalle del cargo</h3><dl><dt>Monto</dt><dd>{tchTransaccionDetail.monto ? `$${Number(tchTransaccionDetail.monto).toLocaleString("es-CL")}` : "—"}</dd><dt>Fecha de cargo</dt><dd>{tchTransaccionDetail.fecha_cargo ?? "—"}</dd><dt>Cuota</dt><dd>{tchTransaccionDetail.numero_cuota ?? "—"}</dd><dt>Entidad</dt><dd>{tchTransaccionDetail.entidad_recaudadora ?? "—"}</dd><dt>Motivo</dt><dd>{tchTransaccionDetail.razon_rechazo ?? "—"}</dd></dl></article><article className="panel"><h3>Suscripción</h3>{tchTransaccionDetail.suscripcion ? <dl><dt>Ficha</dt><dd><button className="record-link" onClick={() => showTchSuscripcion(tchTransaccionDetail.numero_ficha)}>{tchTransaccionDetail.numero_ficha}</button></dd><dt>RUT cliente</dt><dd>{tchTransaccionDetail.suscripcion.cliente_rut ?? "—"}</dd><dt>Banco</dt><dd>{tchTransaccionDetail.suscripcion.banco_nombre ?? "—"}</dd><dt>Inicio</dt><dd>{tchTransaccionDetail.suscripcion.fecha_activacion ?? "—"}</dd></dl> : <p className="muted-copy">No hay suscripción local asociada.</p>}</article></section>
      </main>
    ) : tchView === "clientes" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / CLIENTES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}><div><h2>Clientes TCH</h2><p>Socios asociados a mandatos físicos.</p></div><div className="dashboard-controls"><input aria-label="Buscar cliente" placeholder="Buscar por nombre" value={tchClienteFiltro} onChange={(event) => { setTchClienteFiltro(event.target.value); setTchClientesPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />{tchExportButton("clientes", { nombre: tchClienteFiltro }, tchClientesPage, 50)}</div></header>
        <section className="panel"><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre</th><th>Fecha nacimiento</th><th>Profesión</th><th>Tipo socio</th></tr></thead><tbody>{(tchClientes?.items ?? []).map((c) => <tr key={c.id}><td><button className="record-link" onClick={() => showTchCliente(c.rut)}>{c.rut}</button></td><td>{[c.nombre, c.apellido].filter(Boolean).join(" ") || "—"}</td><td>{c.fecha_nacimiento ?? "—"}</td><td>{c.profesion ?? "—"}</td><td>{c.tipo_socio ?? "—"}</td></tr>)}{(tchClientes?.items ?? []).length === 0 ? <tr><td colSpan={5}>Sin registros.</td></tr> : null}</tbody></table></div>{tchClientes && tchClientes.pages > 1 ? <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}><button disabled={tchClientesPage <= 1} onClick={() => setTchClientesPage((page) => page - 1)}>← Anterior</button><span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchClientesPage} / {tchClientes.pages} ({tchClientes.total.toLocaleString("es-CL")} total)</span><button disabled={tchClientesPage >= tchClientes.pages} onClick={() => setTchClientesPage((page) => page + 1)}>Siguiente →</button></div> : null}</section>
      </main>
    ) : tchView === "suscripciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / SUSCRIPCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Suscripciones TCH</h2><p>Mandatos activos e históricos de débito físico.</p></div>
          <div className="dashboard-controls">
            <select aria-label="Filtrar por estado" value={tchSusFiltroEstado} onChange={(e) => { setTchSusFiltroEstado(e.target.value); setTchSusPage(1); }}>
              <option value="">Todos los estados</option>
              <option value="VIGENTE">Vigentes</option>
              <option value="ELIMINADA">Eliminadas</option>
            </select>
            {tchExportButton("suscripciones", { estado: tchSusFiltroEstado }, tchSusPage, 50)}
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>RUT cliente</th><th>Banco</th>
                <th>Tipo mandato</th><th>Origen</th><th>Centro costo</th>
                <th>Monto</th><th>F. Activación</th><th>Estado</th>
                <th>Estado sec.</th><th>Último cobro</th>
              </tr></thead>
              <tbody>
                {(tchSuscripciones?.items ?? []).map((s) => (
                  <tr key={s.id}>
                    <td><button className="record-link" onClick={() => showTchSuscripcion(s.numero_ficha)}>{s.numero_ficha}</button></td>
                    <td>{s.cliente_rut ?? "—"}</td>
                    <td>{s.banco_nombre ?? "—"}</td>
                    <td>{s.tipo_mandato ?? "—"}</td>
                    <td>{s.origen ?? "—"}</td>
                    <td>{s.centro_costo ?? "—"}</td>
                    <td>{(s.equivalente_pesos || s.monto) ? `$${Number(s.equivalente_pesos || s.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{s.fecha_activacion ?? "—"}</td>
                    <td><span className={`status-pill${s.estado === "VIGENTE" ? "" : " status-attention"}`}>{s.estado}</span></td>
                    <td><span className={`badge badge-${s.secondary_status === "cobrable" ? "green" : s.secondary_status === "incobrable" ? "orange" : s.secondary_status === "inactiva" ? "gray" : "blue"}`}>{s.secondary_status}</span></td>
                    <td>{s.last_paid_date ? s.last_paid_date.slice(0, 10) : "—"}</td>
                  </tr>
                ))}
                {(tchSuscripciones?.items ?? []).length === 0 ? <tr><td colSpan={11}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchSuscripciones && tchSuscripciones.pages > 1 ? (
            <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchSusPage <= 1} onClick={() => setTchSusPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchSusPage} / {tchSuscripciones.pages} ({tchSuscripciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchSusPage >= tchSuscripciones.pages} onClick={() => setTchSusPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : tchView === "transacciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / TRANSACCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Transacciones TCH</h2><p>Historial de cargos aceptados y rechazados.</p></div>
          <div className="dashboard-controls">
            <input type="month" aria-label="Filtrar por período" value={tchTransFiltroPeriodo} onChange={(e) => { setTchTransFiltroPeriodo(e.target.value); setTchTransPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />
            {tchExportButton("transacciones", { periodo: tchTransFiltroPeriodo }, tchTransPage, 100)}
          </div>
        </header>
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Ficha</th><th>Período</th><th>Entidad</th>
                <th>Monto</th><th>Fecha cargo</th><th>Cuota</th><th>Estado</th>
              </tr></thead>
              <tbody>
                {(tchTransacciones?.items ?? []).map((t) => (
                  <tr key={t.id}>
                    <td><button className="record-link" onClick={() => showTchTransaccion(t.id)}>{t.numero_ficha}</button></td>
                    <td>{t.periodo ?? "—"}</td>
                    <td>{t.entidad_recaudadora ?? "—"}</td>
                    <td>{t.monto ? `$${Number(t.monto).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{t.fecha_cargo ?? "—"}</td>
                    <td>{t.numero_cuota && t.total_cuotas ? `${t.numero_cuota}/${t.total_cuotas}` : (t.numero_cuota ?? "—")}</td>
                    <td><span className={`status-pill${t.estado === "ACEPTADA" ? "" : " status-attention"}`}>{t.estado}</span></td>
                  </tr>
                ))}
                {(tchTransacciones?.items ?? []).length === 0 ? <tr><td colSpan={7}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchTransacciones && tchTransacciones.pages > 1 ? (
            <div style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchTransPage <= 1} onClick={() => setTchTransPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchTransPage} / {tchTransacciones.pages} ({tchTransacciones.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchTransPage >= tchTransacciones.pages} onClick={() => setTchTransPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : <main className="app-shell"><p className="muted-copy">Cargando...</p></main>
  ) : null;
}
