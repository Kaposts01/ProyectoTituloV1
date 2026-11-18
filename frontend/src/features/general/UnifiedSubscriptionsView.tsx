import { pageLabels } from "../../pageLabels";
import { useState } from "react";
import { useDebouncedValue } from "../../hooks";
import { labelOr } from "../../i18n/label";
import { ExportButton } from "../shared/ExportButton";
import { ChannelTotals, UnifiedFilterBar, UnifiedPagination } from "./UnifiedControls";
import { StatusText, canOpenRecordPath, channelText, day, detailPath, money } from "./unifiedDisplay";
import { GENERAL_VIEW_PERMISSIONS, VIEW_PERMISSIONS, canAny, type StatusFacets, type SubscriptionRow, type UnifiedPage } from "./unifiedTypes";
import { cleanParams, useUnifiedGet } from "./useUnifiedList";
import { readPortfolioLocation } from "../summary/dashboardContext";
import { DashboardContextNotice } from "../summary/DashboardContextNotice";
import { PortfolioTable, type PortfolioColumn } from "./PortfolioTable";
import { Rut } from "../shared/RutCell";
import { rutText } from "../shared/rut";

const PAGE = 50;
const FIELDS = [
  { value: "all", label: "Todos los campos" }, { value: "id", label: "ID" }, { value: "rut", label: "RUT" },
  { value: "client", label: "Socio" }, { value: "status", label: "Estado" },
];

const secondaryBadge = (value: string | null) =>
  value === "cobrable" ? "green" : value === "incobrable" ? "orange" : value === "inactiva" ? "gray" : "blue";

/**
 * Suscripciones (UX-08, /central/suscripciones): las de los 4 canales en una tabla paginada en el servidor, con
 * filtros de canal y estado. Cada fila abre su ficha por canal; el RUT lleva a Socios filtrado por ese RUT.
 */
export function UnifiedSubscriptionsView({ can, onOpenPath }: { can: (permission: string) => boolean; onOpenPath?: (path: string) => void }) {
  const allowed = can(GENERAL_VIEW_PERMISSIONS.subscriptions) || canAny(can, VIEW_PERMISSIONS.subscriptions);
  const [initial] = useState(() => readPortfolioLocation(window.location.search));
  const [channel, setChannel] = useState(initial.channel);
  const [status, setStatus] = useState("");
  const [field, setField] = useState("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(initial.offset);
  const debouncedQuery = useDebouncedValue(query);
  const reset = (setter: (value: string) => void) => (value: string) => { setter(value); setOffset(0); };

  const filterParams = cleanParams({ query: debouncedQuery, filter_field: debouncedQuery.trim() ? field : "", status });
  const list = useUnifiedGet<UnifiedPage<SubscriptionRow>>(
    "/api/v1/general/subscriptions", { ...filterParams, ...cleanParams({ canal: channel, offset, limit: PAGE }) }, allowed);
  const facets = useUnifiedGet<StatusFacets>("/api/v1/general/subscriptions/statuses", cleanParams({ canal: channel }), allowed);
  const channels = list.data?.canales ?? facets.data?.canales ?? [];
  const open = (path: string | null) => (path && onOpenPath && (path.startsWith("/central/clientes?") ? can("dashboard.view") : canOpenRecordPath(path, can)) ? () => onOpenPath(path) : undefined);

  const busy = list.loading || query !== debouncedQuery;
  const filtered = Boolean(channel || status || query.trim());
  const clearAll = () => { setChannel(""); setStatus(""); setField("all"); setQuery(""); setOffset(0); };
  const columns: PortfolioColumn<SubscriptionRow>[] = [
    { id: "channel", label: "Canal", cell: (row) => channelText(row.channel) },
    { id: "id", label: "ID", required: true, className: "mono", cell: (row) => {
      const go = open(detailPath("subscription", row.channel, row.subscription_id));
      return go ? <button type="button" className="text-button" onClick={go}>{row.subscription_id}</button> : row.subscription_id;
    } },
    { id: "member", label: "Socio", required: true, cell: (row) => row.name || "—" },
    { id: "rut", label: "RUT", cell: (row) => {
      const member = row.rut ? open(`/central/clientes?rut=${encodeURIComponent(row.rut)}`) : undefined;
      return row.rut ? (member ? <button type="button" className="text-button" aria-label={`Ver socio ${rutText(row.rut)}`} onClick={member}><Rut value={row.rut} /></button> : <Rut value={row.rut} />) : "—";
    } },
    { id: "status", label: "Estado", cell: (row) => <StatusText value={row.status} /> },
    { id: "secondary", label: "Estado secundario", initiallyHidden: true, cell: (row) => <span className={`badge badge-${secondaryBadge(row.secondary_status)}`}>{labelOr("secondaryStatus", row.secondary_status, "—")}</span> },
    { id: "last", label: "Último cobro", className: "mono", cell: (row) => day(row.last_charge) },
    { id: "start", label: "Inicio", className: "mono", initiallyHidden: true, cell: (row) => day(row.start_date) },
    { id: "end", label: "Término", className: "mono", initiallyHidden: true, cell: (row) => day(row.end_date) },
    { id: "amount", label: "Monto", className: "mono num", cell: (row) => money(row.amount, row.currency) },
  ];

  return (
    <main className="app-shell unified-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Cartera</p>
          <h1>{pageLabels.subscriptions}</h1>
        </div>
      </div>
      <DashboardContextNotice onOpenPath={onOpenPath} canReturn={can("dashboard.view")} />
      {!allowed ? (
        <p className="muted-copy">Tu rol no puede ver suscripciones de ningún canal. Pide acceso a un administrador.</p>
      ) : (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Suscripciones de todos los canales</p>
              <h3>Listado de suscripciones</h3>
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
            placeholder="Nombre del socio, RUT o ID de suscripción"
            busy={busy}
            query={query}
            onQuery={reset(setQuery)}
            count={busy ? null : list.data?.total ?? null}
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
          {list.data && !busy ? <ChannelTotals byChannel={list.data.by_channel} /> : null}
          <PortfolioTable view="subscriptions" caption="suscripciones" columns={columns} rows={list.data?.items ?? []}
            rowKey={(row) => `${row.channel}-${row.subscription_id}`} loading={busy} error={list.error} forbidden={list.forbidden}
            onRetry={list.reload} filtered={filtered} onClear={clearAll} />
          {list.data ? <UnifiedPagination offset={offset} limit={PAGE} total={list.data.total} shown={list.data.items.length} onOffset={setOffset} loading={busy} /> : null}
        </section>
      )}
    </main>
  );
}
