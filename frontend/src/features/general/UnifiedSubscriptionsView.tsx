import { useState } from "react";
import { useDebouncedValue } from "../../hooks";
import { labelOr } from "../../i18n/label";
import { ExportButton } from "../shared/ExportButton";
import { ChannelTotals, UnifiedFilterBar, UnifiedPagination } from "./UnifiedControls";
import { StatusText, channelText, day, detailPath, money } from "./unifiedDisplay";
import { VIEW_PERMISSIONS, canAny, type StatusFacets, type SubscriptionRow, type UnifiedPage } from "./unifiedTypes";
import { cleanParams, useUnifiedGet } from "./useUnifiedList";
import { Rut } from "../shared/RutCell";
import { rutText } from "../shared/rut";

const PAGE = 50;
const FIELDS = [
  { value: "all", label: "Todos los campos" }, { value: "id", label: "ID" }, { value: "rut", label: "RUT" },
  { value: "client", label: "Socio" }, { value: "status", label: "Estado" },
];
/** `?offset=` de un enlace guardado (la página inicial); el resto de los filtros vive en la pantalla. */
function initialOffset(): number {
  const value = Number(new URLSearchParams(window.location.search).get("offset") ?? "0");
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

const secondaryBadge = (value: string | null) =>
  value === "cobrable" ? "green" : value === "incobrable" ? "orange" : value === "inactiva" ? "gray" : "blue";

/**
 * Suscripciones (UX-08, /central/suscripciones): las de los 4 canales en una tabla paginada en el servidor, con
 * filtros de canal y estado. Cada fila abre su ficha por canal; el RUT lleva a Socios filtrado por ese RUT.
 */
export function UnifiedSubscriptionsView({ can, onOpenPath }: { can: (permission: string) => boolean; onOpenPath?: (path: string) => void }) {
  const allowed = canAny(can, VIEW_PERMISSIONS.subscriptions);
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [field, setField] = useState("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(initialOffset);
  const debouncedQuery = useDebouncedValue(query);
  const reset = (setter: (value: string) => void) => (value: string) => { setter(value); setOffset(0); };

  const filterParams = cleanParams({ query: debouncedQuery, filter_field: debouncedQuery.trim() ? field : "", status });
  const list = useUnifiedGet<UnifiedPage<SubscriptionRow>>(
    "/api/v1/general/subscriptions", { ...filterParams, ...cleanParams({ canal: channel, offset, limit: PAGE }) }, allowed);
  const facets = useUnifiedGet<StatusFacets>("/api/v1/general/subscriptions/statuses", cleanParams({ canal: channel }), allowed);
  const channels = list.data?.canales ?? facets.data?.canales ?? [];
  const open = (path: string | null) => (path && onOpenPath ? () => onOpenPath(path) : undefined);

  return (
    <main className="app-shell unified-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Cartera</p>
          <h1>Suscripciones</h1>
        </div>
      </div>
      {!allowed ? (
        <p className="muted-copy">Tu rol no puede ver suscripciones de ningún canal. Pide acceso a un administrador.</p>
      ) : (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Suscripciones de todos los canales</p>
              <h3><span className="mono">{list.data ? list.data.total.toLocaleString("es-CL") : "…"}</span> suscripciones</h3>
            </div>
          </div>
          <UnifiedFilterBar
            idPrefix="suscripciones"
            channels={channels}
            channel={channel}
            onChannel={reset(setChannel)}
            statuses={facets.data?.statuses ?? []}
            status={status}
            onStatus={reset(setStatus)}
            fields={FIELDS}
            field={field}
            onField={reset(setField)}
            query={query}
            onQuery={reset(setQuery)}
            count={list.data?.total ?? null}
            noun="suscripciones"
            actions={
              <ExportButton
                entity="suscripciones"
                canal={channel || undefined}
                params={filterParams}
                window={{ offset, limit: PAGE }}
                canPii={can("export.pii")}
              />
            }
          />
          {list.data ? <ChannelTotals byChannel={list.data.by_channel} /> : null}
          {list.error ? <p className="error-message" role="alert">{list.error}</p> : null}
          {list.forbidden ? <p className="muted-copy">Tu rol no puede ver este canal.</p> : null}
          <div className="table-wrap" aria-busy={list.loading}>
            <table>
              <thead><tr><th>Canal</th><th>ID</th><th>Socio</th><th>RUT</th><th>Estado</th><th>Estado secundario</th><th>Último cobro</th><th>Inicio</th><th>Término</th><th>Monto</th></tr></thead>
              <tbody>
                {(list.data?.items ?? []).map((row) => {
                  const go = open(detailPath("subscription", row.channel, row.subscription_id));
                  const member = row.rut ? open(`/central/clientes?rut=${encodeURIComponent(row.rut)}`) : undefined;
                  return (
                    <tr key={`${row.channel}-${row.subscription_id}`}>
                      <td>{channelText(row.channel)}</td>
                      <td className="mono">{go ? <button type="button" className="text-button" onClick={go}>{row.subscription_id}</button> : row.subscription_id}</td>
                      <td>{row.name || "—"}</td>
                      <td>{row.rut ? (member ? <button type="button" className="text-button" aria-label={`Ver socio ${rutText(row.rut)}`} onClick={member}><Rut value={row.rut} /></button> : <Rut value={row.rut} />) : "—"}</td>
                      <td><StatusText value={row.status} /></td>
                      <td><span className={`badge badge-${secondaryBadge(row.secondary_status)}`}>{labelOr("secondaryStatus", row.secondary_status, "—")}</span></td>
                      <td className="mono">{day(row.last_charge)}</td>
                      <td className="mono">{day(row.start_date)}</td>
                      <td className="mono">{day(row.end_date)}</td>
                      <td className="mono">{money(row.amount, row.currency)}</td>
                    </tr>
                  );
                })}
                {!list.loading && list.data && list.data.items.length === 0 ? <tr><td colSpan={10}>Sin suscripciones.</td></tr> : null}
              </tbody>
            </table>
          </div>
          {list.data ? <UnifiedPagination offset={offset} limit={PAGE} total={list.data.total} shown={list.data.items.length} onOffset={setOffset} /> : null}
        </section>
      )}
    </main>
  );
}
