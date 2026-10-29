import { getJson, friendlyError } from "../../api";
import type { GeneralClientDetail } from "../shared/types";
import { ExportButton } from "../shared/ExportButton";
import { consolidatedExportTarget } from "../shared/exportMapping";
import type { GeneralState } from "./useGeneralDashboard";

/** Tabla de clientes consolidados por RUT, con búsqueda, paginación y ficha general. */
export function GeneralClientsPanel({ general, setError, can }: { general: GeneralState; setError: (message: string | null) => void; can?: (permission: string) => boolean }) {
  const {
    generalClients,
    generalClientQuery,
    setGeneralClientQuery,
    generalClientFilter,
    setGeneralClientFilter,
    generalClientOffset,
    setGeneralClientOffset,
    generalClientDetail,
    setGeneralClientDetail,
  } = general;
  const exportTarget = consolidatedExportTarget("clientes", generalClientFilter, generalClientQuery);
  return (
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">CLIENTES CONSOLIDADOS</p><h3>{generalClients?.total.toLocaleString("es-CL") ?? ""} clientes por RUT</h3></div><div className="table-filters"><select aria-label="Campo de búsqueda de clientes" value={generalClientFilter} onChange={(event) => { setGeneralClientFilter(event.target.value as typeof generalClientFilter); setGeneralClientOffset(0); }}><option value="all">Todos los campos</option><option value="rut">RUT</option><option value="name">Nombre</option><option value="last_name">Apellido</option><option value="platform">Plataforma</option><option value="email">Correo</option><option value="phone">Teléfono</option></select><input aria-label="Buscar cliente consolidado" placeholder="Buscar clientes" value={generalClientQuery} onChange={(event) => { setGeneralClientQuery(event.target.value); setGeneralClientOffset(0); }} /><ExportButton entity="clientes" params={exportTarget.params} window={{ offset: generalClientOffset, limit: 100 }} canPii={can?.("export.pii")} notes={["El archivo lista un registro por canal, no uno por RUT: sus filas pueden diferir de las de la pantalla."]} /></div></div>
      {generalClientDetail ? (
        <div className="record-detail"><button onClick={() => setGeneralClientDetail(null)}>← Volver a clientes</button><h3>Ficha general: {generalClientDetail.rut}</h3>{(["clients", "subscriptions", "charges", "transactions"] as const).map((section) => <div key={section}><h4>{section === "clients" ? "IDs de cliente" : section === "subscriptions" ? "Suscripciones" : section === "charges" ? "Cargos" : "Transacciones"}</h4><div className="table-wrap"><table><thead><tr><th>Portal</th><th>ID interno</th><th>ID origen</th><th>Estado</th><th>Monto</th></tr></thead><tbody>{generalClientDetail[section].map((item) => <tr key={`${item.portal}-${item.external_id}`}><td>{item.portal}</td><td>{("id_cliente" in item ? item.id_cliente : "id_subscription" in item ? item.id_subscription : "id_cargo" in item ? item.id_cargo : item.id_transaccion)}</td><td>{item.external_id}</td><td>{"status" in item ? item.status : "—"}</td><td>{"amount" in item && item.amount ? `$${Number(item.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{generalClientDetail[section].length === 0 ? <tr><td colSpan={5}>Sin registros relacionados.</td></tr> : null}</tbody></table></div></div>)}</div>
      ) : <><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre completo</th><th>Plataforma de origen</th><th>Suscripciones activas</th></tr></thead><tbody>{(generalClients?.items ?? []).map((client) => <tr key={client.rut}><td><button className="record-link" onClick={() => getJson<GeneralClientDetail>(`/api/v1/staging/dashboard/general/clients/${encodeURIComponent(client.rut)}`).then(setGeneralClientDetail).catch((err: unknown) => setError(friendlyError(err, "No se pudo cargar la ficha general.")))}>{client.rut}</button></td><td>{client.name || "—"}</td><td>{client.origins.join(" · ")}</td><td>{client.active_origins.join(" · ") || "—"}</td></tr>)}{(generalClients?.items ?? []).length === 0 ? <tr><td colSpan={4}>Sin clientes con RUT.</td></tr> : null}</tbody></table></div>{generalClients && generalClients.total > generalClients.limit ? <div className="pagination"><button disabled={generalClientOffset === 0} onClick={() => setGeneralClientOffset((offset) => Math.max(0, offset - generalClients.limit))}>← Anterior</button><span>{generalClientOffset + 1}-{Math.min(generalClientOffset + generalClients.items.length, generalClients.total)} de {generalClients.total.toLocaleString("es-CL")}</span><button disabled={generalClientOffset + generalClients.limit >= generalClients.total} onClick={() => setGeneralClientOffset((offset) => offset + generalClients.limit)}>Siguiente →</button></div> : null}</>}
    </section>
  );
}
