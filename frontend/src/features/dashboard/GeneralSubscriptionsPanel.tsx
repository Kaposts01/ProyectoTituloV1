import type { GeneralState } from "./useGeneralDashboard";

/** Tabla de suscripciones consolidadas con búsqueda, filtro por campo y paginación. */
export function GeneralSubscriptionsPanel({ general }: { general: GeneralState }) {
  const {
    generalSubscriptions,
    generalSubscriptionQuery,
    setGeneralSubscriptionQuery,
    generalSubscriptionFilter,
    setGeneralSubscriptionFilter,
    generalSubscriptionOffset,
    setGeneralSubscriptionOffset,
  } = general;
  return (
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">SUSCRIPCIONES CONSOLIDADAS</p><h3>{generalSubscriptions?.total.toLocaleString("es-CL") ?? ""} suscripciones</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de suscripciones" value={generalSubscriptionFilter} onChange={(event) => { setGeneralSubscriptionFilter(event.target.value as typeof generalSubscriptionFilter); setGeneralSubscriptionOffset(0); }}><option value="all">Todos los campos</option><option value="id">ID</option><option value="rut">RUT</option><option value="client">Cliente</option><option value="platform">Plataforma</option><option value="status">Estado</option></select><input aria-label="Buscar suscripción consolidada" placeholder="Buscar suscripciones" value={generalSubscriptionQuery} onChange={(event) => { setGeneralSubscriptionQuery(event.target.value); setGeneralSubscriptionOffset(0); }} /></div></div>
      <div className="table-wrap"><table><thead><tr><th>ID</th><th>Cliente</th><th>RUT</th><th>Plataforma</th><th>Estado</th><th>Estado secundario</th><th>Último cobro</th><th>Inicio</th><th>Término</th><th>Monto</th></tr></thead><tbody>{(generalSubscriptions?.items ?? []).map((subscription) => <tr key={`${subscription.platform}-${subscription.id}`}><td>{subscription.id}</td><td>{subscription.client || "—"}</td><td>{subscription.rut || "—"}</td><td>{subscription.platform}</td><td>{subscription.status || "—"}</td><td><span className={`badge badge-${subscription.secondary_status === "cobrable" ? "green" : subscription.secondary_status === "incobrable" ? "orange" : subscription.secondary_status === "inactiva" ? "gray" : "blue"}`}>{subscription.secondary_status}</span></td><td>{subscription.last_paid_date ? subscription.last_paid_date.slice(0, 10) : "—"}</td><td>{subscription.started_at ?? "—"}</td><td>{subscription.ended_at ?? "—"}</td><td>{subscription.amount ? `${subscription.currency ?? ""} $${Number(subscription.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{(generalSubscriptions?.items ?? []).length === 0 ? <tr><td colSpan={10}>Sin suscripciones.</td></tr> : null}</tbody></table></div>{generalSubscriptions && generalSubscriptions.total > generalSubscriptions.limit ? <div className="pagination"><button disabled={generalSubscriptionOffset === 0} onClick={() => setGeneralSubscriptionOffset((offset) => Math.max(0, offset - generalSubscriptions.limit))}>← Anterior</button><span>{generalSubscriptionOffset + 1}-{Math.min(generalSubscriptionOffset + generalSubscriptions.items.length, generalSubscriptions.total)} de {generalSubscriptions.total.toLocaleString("es-CL")}</span><button disabled={generalSubscriptionOffset + generalSubscriptions.limit >= generalSubscriptions.total} onClick={() => setGeneralSubscriptionOffset((offset) => offset + generalSubscriptions.limit)}>Siguiente →</button></div> : null}
    </section>
  );
}
