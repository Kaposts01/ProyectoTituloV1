import { label, labelOr } from "../../i18n/label";
import { ChannelChart } from "../../components/ChannelChart";
import { ChannelKpiStrip } from "../../components/ChannelKpiStrip";
import { KpiCard } from "../../components/KpiCard";
import { MonthlyGrowthChart, MonthlyChurnChart } from "../../MonthlyStatusChart";
import { Metric } from "../dashboard/Metric";
import { OperationalAlerts } from "../dashboard/OperationalAlerts";
import { activationVsChurnChart, statusStackedChart, tchSourceNote } from "../dashboard/channelCharts";
import { normalizeKpis } from "../shared/kpis";
import { aggregateChurn, defaultYear } from "../shared/utils";
import { ExportButton } from "../shared/ExportButton";
import { tchExportTarget } from "../shared/exportMapping";
import type { TchState } from "./useTch";

/**
 * Contenido de las vistas TCH (resumen, listas y fichas). Es un componente: un fallo de render
 * queda contenido por `ContentErrorBoundary` y no tumba AppCore.
 */
export function TchContent({ tch, showTch, showTchSubscription, onReport, can }: {
  tch: TchState;
  showTch: (view: "summary" | "clientes" | "suscripciones" | "transacciones") => void;
  showTchSubscription: (fileNumber: number) => void;
  onReport: (scope: string) => void;
  can?: (permission: string) => boolean;
}) {
  const {
    tchView,
    tchRefreshing,
    tchSummary,
    tchSubscriptions,
    tchTransactions,
    tchClients,
    tchLoading,
    tchError,
    tchSubscriptionPage,
    setTchSubscriptionPage,
    tchTransactionPage,
    setTchTransactionPage,
    tchSubscriptionStatusFilter,
    setTchSubscriptionStatusFilter,
    tchClientFilter,
    setTchClientFilter,
    tchClientPage,
    setTchClientPage,
    tchTransactionPeriodFilter,
    setTchTransactionPeriodFilter,
    tchMode,
    setTchMode,
    tchYear,
    setTchYear,
    tchSubscriptionDetail,
    tchTransactionDetail,
    tchClientDetail,
    showTchTransaction,
    showTchClient,
  } = tch;
  const tchExportButton = (view: "clientes" | "suscripciones" | "transacciones", filters: { name?: string; status?: string; period?: string }, page: number, pageSize: number) => {
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
            {tchSummary.lastEtl.startedAt ? (
              <>
              <div className={`sync-state ${tchSummary.lastEtl.status === "completed" ? "ready" : "attention"}`}>
                <span />{tchSummary.lastEtl.status ? label("runStatus", tchSummary.lastEtl.status) : "Sin ETL"}
              </div>
              <p className="muted-copy" style={{ fontSize: "0.78rem" }}>
                Último ETL: {tchSummary.lastEtl.startedAt?.slice(0, 10)} · {(tchSummary.lastEtl.recordsUpserted ?? 0).toLocaleString("es-CL")} registros
              </p>
              </>
            ) : null}
          </div>
        </header>
        <section className="metrics provider-metrics" aria-label="KPIs TCH">
          <Metric label="Suscripciones vigentes" value={tchSummary.subscriptions.active} tone="green" amount={tchSummary.subscriptions.activeAmount} mode={tchMode} />
          <Metric label="Suscripciones eliminadas" value={tchSummary.subscriptions.deleted} tone="orange" amount={tchSummary.subscriptions.deletedAmount} mode={tchMode} />
          <Metric label="Total suscripciones" value={tchSummary.subscriptions.total} tone="blue" amount={tchSummary.subscriptions.totalAmount} mode={tchMode} />
          <Metric label="Total transacciones" value={tchSummary.transactions.total} tone="violet" amount={tchSummary.transactions.amount} mode={tchMode} />
        </section>
        <ChannelKpiStrip kpis={normalizeKpis("tch", tchSummary.kpis, tchSummary.churnWindowLabel)} ariaLabel="KPIs financieros TCH" />
        <section className="metrics kpi-metrics" aria-label="KPIs transacciones TCH">
          <KpiCard label="Aceptadas" value={tchSummary.transactions.accepted} format="count" caption="Transacciones cobradas" />
          <KpiCard label="Rechazadas" value={tchSummary.transactions.rejected} format="count" caption="Transacciones fallidas" />
          <KpiCard label="Tasa de rechazo" value={tchSummary.transactions.rejectionRatePct} format="percent" caption="Rechazadas / total" emptyCaption="Sin base para calcular" />
        </section>
        <section className="extended-charts">
          {(() => {
            const tx = statusStackedChart(tchSummary.monthlyTransactions, tchMode);
            const note = tchSourceNote(tchSummary.transactionsSource);
            return tx.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Transacciones mensuales</h3></div></div>
                <ChannelChart series={tx.series} data={tx.rows} kind="stacked" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de transacciones mensuales de TCH por estado" />
                {note ? <p className="muted-copy">{note}</p> : null}
              </article>
            ) : null;
          })()}
          {(() => {
            const ab = activationVsChurnChart(tchSummary.monthlyActivations, tchSummary.monthlyCancellations, tchMode);
            return ab.rows.length ? (
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Altas vs bajas</h3></div></div>
                <ChannelChart series={ab.series} data={ab.rows} kind="grouped" mode={tchMode} year={tchYear} legend ariaLabel="Gráfico de altas y bajas mensuales de suscripciones TCH" />
              </article>
            ) : null;
          })()}
          {tchSummary.monthlyActivations?.length && tchSummary.monthlyCancellations?.length ? (
            <>
              <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Crecimiento real mensual</h3></div></div>
                <MonthlyGrowthChart
                  activations={tchSummary.monthlyActivations}
                  cancellations={aggregateChurn(tchSummary.monthlyCancellations)}
                  year={tchYear}
                  mode={tchMode}
                />
              </article>
            </>
          ) : null}
          {tchSummary.churnRateMonthly.length ? (
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Churn mensual (%)</h3></div></div>
              <MonthlyChurnChart data={tchSummary.churnRateMonthly} year={tchYear} />
            </article>
          ) : null}
        </section>
        <OperationalAlerts alerts={tchSummary.alerts ?? []} />
        <section className="panel channel-resources">
          <div><p className="eyebrow">EXPLORAR TCH</p><h3>Vistas disponibles</h3></div>
          <div>
            <button onClick={() => showTch("suscripciones")}>Suscripciones<span>{tchSummary.subscriptions.total}</span></button>
            <button onClick={() => showTch("transacciones")}>Transacciones<span>{tchSummary.transactions.total}</span></button>
          </div>
        </section>
      </main>
    ) : tchView === "client-detail" && tchClientDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("clientes")}>← Clientes TCH</button>
        <p className="eyebrow">TCH / CLIENTE</p>
        <header className="detail-header"><div><h2>{[tchClientDetail.firstName, tchClientDetail.lastName].filter(Boolean).join(" ") || "Cliente TCH"}</h2><p>{tchClientDetail.rut}</p></div></header>
        <section className="detail-grid"><article className="panel"><h3>Datos personales</h3><dl><dt>RUT</dt><dd>{tchClientDetail.rut}</dd><dt>Fecha de nacimiento</dt><dd>{tchClientDetail.birthDate ?? "—"}</dd><dt>Profesión</dt><dd>{tchClientDetail.profession ?? "—"}</dd><dt>Tipo de socio</dt><dd>{tchClientDetail.memberType ?? "—"}</dd></dl></article><article className="panel"><h3>Contacto</h3><dl><dt>Correo electrónico</dt><dd>{tchClientDetail.email ?? "—"}</dd><dt>Teléfono</dt><dd>{tchClientDetail.phone ?? "—"}</dd><dt>Dirección</dt><dd>{tchClientDetail.address ?? "—"}</dd><dt>Comuna</dt><dd>{tchClientDetail.commune ?? "—"}</dd><dt>Ciudad</dt><dd>{tchClientDetail.city ?? "—"}</dd></dl></article><article className="panel"><h3>Mandatos</h3><p className="metric-value">{(tchClientDetail.subscriptions ?? []).length.toLocaleString("es-CL")}</p><p className="muted-copy">Suscripciones TCH asociadas</p></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES</p><h3>Mandatos asociados</h3></div></div><div className="table-wrap"><table><thead><tr><th>Ficha</th><th>Inicio</th><th>Fin</th><th>Monto</th><th>Estado</th><th>Estado sec.</th><th>Último cobro</th></tr></thead><tbody>{(tchClientDetail.subscriptions ?? []).map((s) => <tr key={s.id}><td><button className="record-link" onClick={() => showTchSubscription(s.fileNumber)}>{s.fileNumber}</button></td><td>{s.activationDate ?? "—"}</td><td>{s.endDate ?? "—"}</td><td>{(s.pesoEquivalent || s.amount) ? `$${Number(s.pesoEquivalent || s.amount).toLocaleString("es-CL")}` : "—"}</td><td><span className={`status-pill${s.status === "VIGENTE" ? "" : " status-attention"}`}>{label("tchStatus", s.status)}</span></td><td><span className={`badge badge-${s.secondaryStatus === "cobrable" ? "green" : s.secondaryStatus === "incobrable" ? "orange" : s.secondaryStatus === "inactiva" ? "gray" : "blue"}`}>{labelOr("secondaryStatus", s.secondaryStatus, "")}</span></td><td>{s.lastPaidDate ? s.lastPaidDate.slice(0, 10) : "—"}</td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "subscription-detail" && tchSubscriptionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("suscripciones")}>← Suscripciones TCH</button>
        <p className="eyebrow">TCH / SUSCRIPCIÓN</p>
        <header className="detail-header"><div><h2>Ficha {tchSubscriptionDetail.fileNumber}</h2><p>Mandato físico e historial de cargos.</p></div><span className={`status-pill${tchSubscriptionDetail.status === "VIGENTE" ? "" : " status-attention"}`}>{label("tchStatus", tchSubscriptionDetail.status)}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Mandato</h3><dl><dt>Inicio</dt><dd>{tchSubscriptionDetail.activationDate ?? "—"}</dd><dt>Fin</dt><dd>{tchSubscriptionDetail.endDate ?? "—"}</dd><dt>Motivo</dt><dd>{tchSubscriptionDetail.cancellationReason ?? "—"}</dd><dt>Monto (CLP)</dt><dd>{(tchSubscriptionDetail.pesoEquivalent || tchSubscriptionDetail.amount) ? `$${Number(tchSubscriptionDetail.pesoEquivalent || tchSubscriptionDetail.amount).toLocaleString("es-CL")}` : "—"}</dd><dt>Banco</dt><dd>{tchSubscriptionDetail.bankName ?? "—"}</dd><dt>RUT cliente</dt><dd>{tchSubscriptionDetail.clientRut ?? "—"}</dd><dt>Último cobro</dt><dd>{tchSubscriptionDetail.lastPaidDate ? tchSubscriptionDetail.lastPaidDate.slice(0, 10) : "—"}</dd><dt>Estado sec.</dt><dd><span className={`badge badge-${tchSubscriptionDetail.secondaryStatus === "cobrable" ? "green" : tchSubscriptionDetail.secondaryStatus === "incobrable" ? "orange" : tchSubscriptionDetail.secondaryStatus === "inactiva" ? "gray" : "blue"}`}>{labelOr("secondaryStatus", tchSubscriptionDetail.secondaryStatus, "")}</span></dd></dl></article><article className="panel"><h3>Captación</h3><dl><dt>Origen</dt><dd>{tchSubscriptionDetail.origin ?? "—"}</dd><dt>Centro de costo</dt><dd>{tchSubscriptionDetail.costCenter ?? "—"}</dd><dt>Captador</dt><dd>{tchSubscriptionDetail.recruiter ?? "—"}</dd><dt>Mandato</dt><dd>{tchSubscriptionDetail.mandateNumber ?? "—"}</dd><dt>Tipo de cuenta</dt><dd>{tchSubscriptionDetail.accountType ?? "—"}</dd></dl></article></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">CARGOS</p><h3>Historial</h3></div></div><div className="table-wrap"><table><thead><tr><th>Período</th><th>Monto</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{(tchSubscriptionDetail.transactions ?? []).map((t) => <tr key={t.id}><td><button className="record-link" onClick={() => showTchTransaction(t.id)}>{t.period ?? "—"}</button></td><td>{t.amount ? `$${Number(t.amount).toLocaleString("es-CL")}` : "—"}</td><td>{t.chargeDate ?? "—"}</td><td><span className={`status-pill${t.status === "ACEPTADA" ? "" : " status-attention"}`}>{label("tchStatus", t.status)}</span></td></tr>)}</tbody></table></div></section>
      </main>
    ) : tchView === "transaction-detail" && tchTransactionDetail ? (
      <main className="app-shell">
        <button className="back-button" onClick={() => showTch("transacciones")}>← Transacciones TCH</button>
        <p className="eyebrow">TCH / TRANSACCIÓN</p>
        <header className="detail-header"><div><h2>Cargo {tchTransactionDetail.period ?? "sin período"}</h2><p>Ficha {tchTransactionDetail.fileNumber}</p></div><span className={`status-pill${tchTransactionDetail.status === "ACEPTADA" ? "" : " status-attention"}`}>{label("tchStatus", tchTransactionDetail.status)}</span></header>
        <section className="detail-grid"><article className="panel"><h3>Detalle del cargo</h3><dl><dt>Monto</dt><dd>{tchTransactionDetail.amount ? `$${Number(tchTransactionDetail.amount).toLocaleString("es-CL")}` : "—"}</dd><dt>Fecha de cargo</dt><dd>{tchTransactionDetail.chargeDate ?? "—"}</dd><dt>Cuota</dt><dd>{tchTransactionDetail.installmentNumber ?? "—"}</dd><dt>Entidad</dt><dd>{tchTransactionDetail.collectingEntity ?? "—"}</dd><dt>Motivo</dt><dd>{tchTransactionDetail.rejectionReason ?? "—"}</dd></dl></article><article className="panel"><h3>Suscripción</h3>{tchTransactionDetail.subscription ? <dl><dt>Ficha</dt><dd><button className="record-link" onClick={() => showTchSubscription(tchTransactionDetail.fileNumber)}>{tchTransactionDetail.fileNumber}</button></dd><dt>RUT cliente</dt><dd>{tchTransactionDetail.subscription.clientRut ?? "—"}</dd><dt>Banco</dt><dd>{tchTransactionDetail.subscription.bankName ?? "—"}</dd><dt>Inicio</dt><dd>{tchTransactionDetail.subscription.activationDate ?? "—"}</dd></dl> : <p className="muted-copy">No hay suscripción local asociada.</p>}</article></section>
      </main>
    ) : tchView === "clientes" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / CLIENTES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}><div><h2>Clientes TCH</h2><p>Socios asociados a mandatos físicos.</p></div><div className="dashboard-controls"><input aria-label="Buscar cliente" placeholder="Buscar por nombre" value={tchClientFilter} onChange={(event) => { setTchClientFilter(event.target.value); setTchClientPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />{tchExportButton("clientes", { name: tchClientFilter }, tchClientPage, 50)}</div></header>
        <section className="panel"><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre</th><th>Fecha nacimiento</th><th>Profesión</th><th>Tipo socio</th></tr></thead><tbody>{(tchClients?.items ?? []).map((c) => <tr key={c.id}><td><button className="record-link" onClick={() => showTchClient(c.rut)}>{c.rut}</button></td><td>{[c.firstName, c.lastName].filter(Boolean).join(" ") || "—"}</td><td>{c.birthDate ?? "—"}</td><td>{c.profession ?? "—"}</td><td>{c.memberType ?? "—"}</td></tr>)}{(tchClients?.items ?? []).length === 0 ? <tr><td colSpan={5}>Sin registros.</td></tr> : null}</tbody></table></div>{tchClients && tchClients.pages > 1 ? <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}><button disabled={tchClientPage <= 1} onClick={() => setTchClientPage((page) => page - 1)}>← Anterior</button><span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchClientPage} / {tchClients.pages} ({tchClients.total.toLocaleString("es-CL")} total)</span><button disabled={tchClientPage >= tchClients.pages} onClick={() => setTchClientPage((page) => page + 1)}>Siguiente →</button></div> : null}</section>
      </main>
    ) : tchView === "suscripciones" ? (
      <main className="app-shell">
        <p className="eyebrow">TCH / SUSCRIPCIONES</p>
        <header className="channel-hero" style={{ alignItems: "flex-end" }}>
          <div><h2>Suscripciones TCH</h2><p>Mandatos activos e históricos de débito físico.</p></div>
          <div className="dashboard-controls">
            <select aria-label="Filtrar por estado" value={tchSubscriptionStatusFilter} onChange={(e) => { setTchSubscriptionStatusFilter(e.target.value); setTchSubscriptionPage(1); }}>
              <option value="">Todos los estados</option>
              <option value="VIGENTE">Vigentes</option>
              <option value="ELIMINADA">Eliminadas</option>
            </select>
            {tchExportButton("suscripciones", { status: tchSubscriptionStatusFilter }, tchSubscriptionPage, 50)}
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
                {(tchSubscriptions?.items ?? []).map((s) => (
                  <tr key={s.id}>
                    <td><button className="record-link" onClick={() => showTchSubscription(s.fileNumber)}>{s.fileNumber}</button></td>
                    <td>{s.clientRut ?? "—"}</td>
                    <td>{s.bankName ?? "—"}</td>
                    <td>{s.mandateType ?? "—"}</td>
                    <td>{s.origin ?? "—"}</td>
                    <td>{s.costCenter ?? "—"}</td>
                    <td>{(s.pesoEquivalent || s.amount) ? `$${Number(s.pesoEquivalent || s.amount).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{s.activationDate ?? "—"}</td>
                    <td><span className={`status-pill${s.status === "VIGENTE" ? "" : " status-attention"}`}>{label("tchStatus", s.status)}</span></td>
                    <td><span className={`badge badge-${s.secondaryStatus === "cobrable" ? "green" : s.secondaryStatus === "incobrable" ? "orange" : s.secondaryStatus === "inactiva" ? "gray" : "blue"}`}>{labelOr("secondaryStatus", s.secondaryStatus, "")}</span></td>
                    <td>{s.lastPaidDate ? s.lastPaidDate.slice(0, 10) : "—"}</td>
                  </tr>
                ))}
                {(tchSubscriptions?.items ?? []).length === 0 ? <tr><td colSpan={11}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchSubscriptions && tchSubscriptions.pages > 1 ? (
            <div className="pagination" style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchSubscriptionPage <= 1} onClick={() => setTchSubscriptionPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchSubscriptionPage} / {tchSubscriptions.pages} ({tchSubscriptions.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchSubscriptionPage >= tchSubscriptions.pages} onClick={() => setTchSubscriptionPage((p) => p + 1)}>Siguiente →</button>
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
            <input type="month" aria-label="Filtrar por período" value={tchTransactionPeriodFilter} onChange={(e) => { setTchTransactionPeriodFilter(e.target.value); setTchTransactionPage(1); }} style={{ padding: "0.35rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />
            {tchExportButton("transacciones", { period: tchTransactionPeriodFilter }, tchTransactionPage, 100)}
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
                {(tchTransactions?.items ?? []).map((t) => (
                  <tr key={t.id}>
                    <td><button className="record-link" onClick={() => showTchTransaction(t.id)}>{t.fileNumber}</button></td>
                    <td>{t.period ?? "—"}</td>
                    <td>{t.collectingEntity ?? "—"}</td>
                    <td>{t.amount ? `$${Number(t.amount).toLocaleString("es-CL")}` : "—"}</td>
                    <td>{t.chargeDate ?? "—"}</td>
                    <td>{t.installmentNumber && t.totalInstallments ? `${t.installmentNumber}/${t.totalInstallments}` : (t.installmentNumber ?? "—")}</td>
                    <td><span className={`status-pill${t.status === "ACEPTADA" ? "" : " status-attention"}`}>{label("tchStatus", t.status)}</span></td>
                  </tr>
                ))}
                {(tchTransactions?.items ?? []).length === 0 ? <tr><td colSpan={7}>Sin registros.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {tchTransactions && tchTransactions.pages > 1 ? (
            <div style={{ display: "flex", gap: "0.5rem", padding: "0.75rem 0 0", justifyContent: "flex-end" }}>
              <button disabled={tchTransactionPage <= 1} onClick={() => setTchTransactionPage((p) => p - 1)}>← Anterior</button>
              <span style={{ padding: "0 0.5rem", lineHeight: "2" }}>{tchTransactionPage} / {tchTransactions.pages} ({tchTransactions.total.toLocaleString("es-CL")} total)</span>
              <button disabled={tchTransactionPage >= tchTransactions.pages} onClick={() => setTchTransactionPage((p) => p + 1)}>Siguiente →</button>
            </div>
          ) : null}
        </section>
      </main>
    ) : <main className="app-shell"><p className="muted-copy">Cargando...</p></main>
  ) : null;
}
