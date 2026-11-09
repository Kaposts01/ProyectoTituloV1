import { label } from "../../i18n/label";
import { getJson, friendlyError } from "../../api";
import { adaptGeneralClientDetail, type GeneralClientDetailWire } from "./generalClientAdapter";
import { ExportButton } from "../shared/ExportButton";
import { consolidatedExportTarget } from "../shared/exportMapping";
import type { GeneralState } from "./useGeneralDashboard";
import { ActiveFilters, type FilterChip } from "../general/UnifiedControls";
import { Rut } from "../shared/RutCell";
import { rutText } from "../shared/rut";

const CLIENT_FIELDS = [
  { value: "all", label: "Todos los campos" }, { value: "rut", label: "RUT" }, { value: "name", label: "Nombre" },
  { value: "last_name", label: "Apellido" }, { value: "platform", label: "Plataforma" }, { value: "email", label: "Correo" },
  { value: "phone", label: "Teléfono" },
];
const CLIENT_CHANNELS = [
  { value: "virtualpos", label: "VirtualPOS" }, { value: "toku", label: "Toku" }, { value: "payku", label: "Payku" }, { value: "tch", label: "TCH" },
];
const CLIENT_STATUSES = [{ value: "active", label: "Con suscripción activa" }, { value: "inactive", label: "Sin suscripción activa" }];

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
    generalClientChannel,
    setGeneralClientChannel,
    generalClientStatus,
    setGeneralClientStatus,
  } = general;
  const exportTarget = consolidatedExportTarget("clientes", generalClientFilter, generalClientQuery);
  const resetOffset = () => setGeneralClientOffset(0);
  const optionLabel = (options: { value: string; label: string }[], value: string) => options.find((option) => option.value === value)?.label ?? value;
  const chips: FilterChip[] = [];
  if (generalClientQuery.trim()) {
    const where = generalClientFilter === "all" ? "Texto" : optionLabel(CLIENT_FIELDS, generalClientFilter);
    chips.push({ key: "texto", label: `${where}: «${generalClientQuery.trim()}»`, onRemove: () => { setGeneralClientQuery(""); setGeneralClientFilter("all"); resetOffset(); } });
  }
  if (generalClientChannel) chips.push({ key: "canal", label: `Canal: ${optionLabel(CLIENT_CHANNELS, generalClientChannel)}`, onRemove: () => { setGeneralClientChannel(""); resetOffset(); } });
  if (generalClientStatus) chips.push({ key: "estado", label: `Estado: ${optionLabel(CLIENT_STATUSES, generalClientStatus)}`, onRemove: () => { setGeneralClientStatus(""); resetOffset(); } });
  const clearAll = () => { for (const chip of chips) chip.onRemove(); };
  return (
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">CLIENTES CONSOLIDADOS</p><h3>{generalClients?.total.toLocaleString("es-CL") ?? ""} clientes por RUT</h3></div></div>
      <div className="filter-bar">
        <div className="filter-row">
          <div className="filter-fields">
            <label className="filter-field">
              <span>Buscar en</span>
              <select aria-label="Campo de búsqueda de clientes" value={generalClientFilter} onChange={(event) => { setGeneralClientFilter(event.target.value as typeof generalClientFilter); setGeneralClientOffset(0); }}>
                {CLIENT_FIELDS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="filter-field filter-field-wide">
              <span>Texto</span>
              <input type="search" aria-label="Buscar cliente consolidado" placeholder="Buscar clientes" value={generalClientQuery} onChange={(event) => { setGeneralClientQuery(event.target.value); setGeneralClientOffset(0); }} />
            </label>
            <label className="filter-field">
              <span>Canal</span>
              <select aria-label="Canal de los socios" value={generalClientChannel} onChange={(event) => { setGeneralClientChannel(event.target.value as typeof generalClientChannel); setGeneralClientOffset(0); }}>
                <option value="">Todos los canales</option>
                {CLIENT_CHANNELS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="filter-field">
              <span>Estado</span>
              <select aria-label="Estado de los socios" value={generalClientStatus} onChange={(event) => { setGeneralClientStatus(event.target.value as typeof generalClientStatus); setGeneralClientOffset(0); }}>
                <option value="">Todos</option>
                {CLIENT_STATUSES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
          </div>
          <div className="filter-actions">
            <ExportButton entity="clientes" canal={generalClientChannel || undefined} ignoredFilters={generalClientStatus ? [generalClientStatus === "active" ? "estado: con suscripción activa" : "estado: sin suscripción activa"] : []} params={exportTarget.params} window={{ offset: generalClientOffset, limit: 50 }} canPii={can?.("export.pii")} notes={["El archivo lista un registro por canal, no uno por RUT: sus filas pueden diferir de las de la pantalla."]} />
          </div>
        </div>
        <ActiveFilters chips={chips} onClear={clearAll} count={generalClients?.total ?? null} noun="socios" />
      </div>
      <p className="muted-copy">Agrupado por RUT <strong>no verificado</strong>: el mismo RUT en dos canales se muestra como un solo socio, pero el CRM aún no confirma que sea la misma persona (identidad centralizada pendiente).</p>
      {generalClientDetail ? (
        <div className="record-detail"><button onClick={() => setGeneralClientDetail(null)}>← Volver a clientes</button><h3>Ficha general: <Rut value={generalClientDetail.rut} /></h3>{(["clients", "subscriptions", "charges", "transactions"] as const).map((section) => <div key={section}><h4>{section === "clients" ? "IDs de cliente" : section === "subscriptions" ? "Suscripciones" : section === "charges" ? "Cargos" : "Transacciones"}</h4><div className="table-wrap"><table><thead><tr><th>Portal</th><th>ID interno</th><th>ID origen</th><th>Estado</th><th>Monto</th></tr></thead><tbody>{generalClientDetail[section].map((item) => <tr key={`${item.portal}-${item.externalId}`}><td>{label("channel", item.portal)}</td><td>{item.internalId}</td><td>{item.externalId}</td><td>{item.status !== null ? label("status", item.status) : "—"}</td><td>{item.amount ? `$${Number(item.amount).toLocaleString("es-CL")}` : "—"}</td></tr>)}{generalClientDetail[section].length === 0 ? <tr><td colSpan={5}>Sin registros relacionados.</td></tr> : null}</tbody></table></div></div>)}</div>
      ) : <><div className="table-wrap"><table><thead><tr><th>RUT</th><th>Nombre completo</th><th>Plataforma de origen</th><th>Suscripciones activas</th></tr></thead><tbody>{(generalClients?.items ?? []).map((client) => <tr key={client.rut}><td><button className="record-link" onClick={() => getJson<GeneralClientDetailWire>(`/api/v1/staging/dashboard/general/clients/${encodeURIComponent(client.rut)}`).then((detail) => setGeneralClientDetail(adaptGeneralClientDetail(detail))).catch((err: unknown) => setError(friendlyError(err, "No se pudo cargar la ficha general.")))} aria-label={rutText(client.rut)}><Rut value={client.rut} /></button></td><td>{client.name || "—"}</td><td>{client.origins.map((origin) => label("channel", origin)).join(" · ")}</td><td>{client.active_origins.map((origin) => label("channel", origin)).join(" · ") || "—"}</td></tr>)}{(generalClients?.items ?? []).length === 0 ? <tr><td colSpan={4}>Sin clientes con RUT.</td></tr> : null}</tbody></table></div>{generalClients && generalClients.total > generalClients.limit ? <div className="pagination"><button disabled={generalClientOffset === 0} onClick={() => setGeneralClientOffset((offset) => Math.max(0, offset - generalClients.limit))}>← Anterior</button><span>{generalClientOffset + 1}-{Math.min(generalClientOffset + generalClients.items.length, generalClients.total)} de {generalClients.total.toLocaleString("es-CL")}</span><button disabled={generalClientOffset + generalClients.limit >= generalClients.total} onClick={() => setGeneralClientOffset((offset) => offset + generalClients.limit)}>Siguiente →</button></div> : null}</>}
    </section>
  );
}
