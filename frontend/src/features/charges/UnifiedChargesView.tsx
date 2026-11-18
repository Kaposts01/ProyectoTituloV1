import { pageLabels } from "../../pageLabels";
import { useState } from "react";
import { useDebouncedValue } from "../../hooks";
import { tryLabel } from "../../i18n/label";
import { ExportButton } from "../shared/ExportButton";
import { ChannelTotals, UnifiedFilterBar, UnifiedPagination, type FilterChip } from "../general/UnifiedControls";
import { StatusText, channelText, day, detailPath, money } from "../general/unifiedDisplay";
import {
  CHARGE_OUTCOMES, VIEW_PERMISSIONS, canAny,
  type ChargeRow, type PaymentRow, type RejectionSummary, type StatusFacets, type UnifiedPage,
} from "../general/unifiedTypes";
import { cleanParams, useUnifiedGet } from "../general/useUnifiedList";
import { PortfolioTable, type PortfolioColumn } from "../general/PortfolioTable";
import { Rut } from "../shared/RutCell";

const PAGE = 50;
type Tab = "charges" | "payments";

const FIELDS: Record<Tab, { value: string; label: string }[]> = {
  charges: [{ value: "all", label: "Todos los campos" }, { value: "id", label: "ID de cobro" }, { value: "subscription_id", label: "ID de suscripción" }, { value: "status", label: "Estado" }],
  payments: [{ value: "all", label: "Todos los campos" }, { value: "id", label: "ID de pago" }, { value: "charge_id", label: "ID de cobro" }, { value: "status", label: "Estado" }],
};

const pct = (rate: number | null) => (rate === null ? "—" : `${rate.toFixed(1).replace(".", ",")} %`);

/** Tasa de rechazo por canal con la definición única (`charge_stats`): pagados y rechazados con fecha hasta hoy. */
function RejectionSummaryPanel({ channel, dateFrom, dateTo }: { channel: string; dateFrom: string; dateTo: string }) {
  const params = cleanParams({ canal: channel, date_from: dateFrom, date_to: dateTo });
  const { data: loaded, loading, forbidden, error, reload } = useUnifiedGet<RejectionSummary>("/api/v1/general/charges/summary", params);
  const data = loading ? null : loaded;
  if (forbidden) return null;
  return (
    <section className="panel unified-summary" aria-label="Rechazo por canal" aria-busy={loading}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Rechazo</p>
          <h3>Tasa de rechazo <span className="mono">{pct(data?.total.rate ?? null)}</span></h3>
        </div>
      </div>
      <p className="muted-copy">
        Este resumen utiliza el canal y las fechas seleccionadas. Rechazados / (pagados + rechazados), con fecha de cobro hasta hoy (hora de Chile) y sin cancelados, expirados ni anulados.
        VirtualPOS y TCH cuentan cargos; Toku y Payku cuentan intentos de cobro, porque el canal no marca el cargo como rechazado.
      </p>
      {loading ? <p role="status">Actualizando resumen de rechazo…</p> : null}
      {error ? <div role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={reload}>Reintentar resumen</button></div> : null}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Canal</th><th>Base</th><th>Pagados</th><th>Rechazados</th><th>Tasa</th></tr></thead>
          <tbody>
            {(data?.channels ?? []).map((item) => (
              <tr key={item.channel}>
                <td>{item.label}</td>
                <td>{item.basis === "cargos" ? "Cargos" : "Intentos de cobro"}</td>
                <td className="mono">{item.paid.toLocaleString("es-CL")}</td>
                <td className="mono">{item.rejected.toLocaleString("es-CL")}</td>
                <td className="mono">{pct(item.rate)}</td>
              </tr>
            ))}
            {!loading && data && data.channels.length === 0 ? <tr><td colSpan={5}>Sin datos.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Cobros (UX-09): cobros y pagos de todos los canales en una sola tabla, paginada en el servidor. Los canales se
 * filtran según los permisos de vista de siempre; el botón Exportar descarga lo mismo con los filtros activos.
 */
export function UnifiedChargesView({ can, onOpenPath }: { can: (permission: string) => boolean; onOpenPath?: (path: string) => void }) {
  const canCharges = canAny(can, VIEW_PERMISSIONS.charges);
  const canPayments = canAny(can, VIEW_PERMISSIONS.payments);
  const [tab, setTab] = useState<Tab>(canCharges ? "charges" : "payments");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const [field, setField] = useState("all");
  const [query, setQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);
  const debouncedQuery = useDebouncedValue(query);
  const reset = <T,>(setter: (value: T) => void) => (value: T) => { setter(value); setOffset(0); };

  const base = tab === "charges" ? "/api/v1/general/charges" : "/api/v1/general/payments";
  const filterParams = cleanParams({
    query: debouncedQuery, filter_field: debouncedQuery.trim() ? field : "", status, outcome, date_from: dateFrom, date_to: dateTo,
  });
  const list = useUnifiedGet<UnifiedPage<ChargeRow | PaymentRow>>(base, { ...filterParams, ...cleanParams({ canal: channel, offset, limit: PAGE }) }, canCharges || canPayments);
  const facets = useUnifiedGet<StatusFacets>(`${base}/statuses`, cleanParams({ canal: channel, date_from: dateFrom, date_to: dateTo }), canCharges || canPayments);
  const channels = list.data?.canales ?? facets.data?.canales ?? [];

  const switchTab = (next: Tab) => {
    setTab(next); setChannel(""); setStatus(""); setField("all"); setOffset(0);
  };
  // QA-16: un rango invertido devolvía «0 cobros» sin explicación; ahora se avisa (las fechas AAAA-MM-DD se comparan como texto).
  const invertedRange = dateFrom !== "" && dateTo !== "" && dateFrom > dateTo;
  const open = (path: string | null) => (path && onOpenPath ? () => onOpenPath(path) : undefined);
  const extraChips: FilterChip[] = [];
  if (outcome) extraChips.push({ key: "resultado", label: `Resultado: ${tryLabel("chargeOutcome", outcome) ?? outcome}`, onRemove: () => reset(setOutcome)("") });
  if (dateFrom) extraChips.push({ key: "desde", label: `Desde: ${day(dateFrom)}`, onRemove: () => reset(setDateFrom)("") });
  if (dateTo) extraChips.push({ key: "hasta", label: `Hasta: ${day(dateTo)}`, onRemove: () => reset(setDateTo)("") });

  const busy = list.loading || query !== debouncedQuery;
  const filtered = Boolean(channel || status || outcome || dateFrom || dateTo || query.trim());
  const clearAll = () => { setChannel(""); setStatus(""); setOutcome(""); setDateFrom(""); setDateTo(""); setQuery(""); setField("all"); setOffset(0); };
  const chargeColumns: PortfolioColumn<ChargeRow>[] = [
    { id: "channel", label: "Canal", cell: (row) => channelText(row.channel) },
    { id: "id", label: "ID de cobro", required: true, className: "mono", cell: (row) => {
      const go = open(detailPath("charge", row.channel, row.charge_id));
      return go ? <button type="button" className="text-button" onClick={go}>{row.charge_id}</button> : row.charge_id;
    } },
    { id: "subscription", label: "Suscripción", initiallyHidden: true, className: "mono", cell: (row) => row.subscription_id ?? "—" },
    { id: "member", label: "Socio", cell: (row) => row.name || "—" },
    { id: "rut", label: "RUT", cell: (row) => <Rut value={row.rut} /> },
    { id: "status", label: "Estado", cell: (row) => <StatusText value={row.status} /> },
    { id: "date", label: "Fecha de cobro", className: "mono", cell: (row) => day(row.charge_date) },
    { id: "period", label: "Período", initiallyHidden: true, className: "mono", cell: (row) => row.period ?? "—" },
    { id: "amount", label: "Monto", className: "mono num", cell: (row) => money(row.amount, row.currency) },
    { id: "reason", label: "Motivo de rechazo", cell: (row) => row.rejection_reason ? <span data-raw-text>{row.rejection_reason}</span> : "—" },
  ];
  const paymentColumns: PortfolioColumn<PaymentRow>[] = [
    { id: "channel", label: "Canal", cell: (row) => channelText(row.channel) },
    { id: "id", label: "ID de pago", required: true, className: "mono", cell: (row) => {
      const go = open(detailPath("payment", row.channel, row.payment_id));
      return go ? <button type="button" className="text-button" onClick={go}>{row.payment_id}</button> : row.payment_id;
    } },
    { id: "charge", label: "ID de cobro", initiallyHidden: true, className: "mono", cell: (row) => row.charge_id ?? "—" },
    { id: "member", label: "Socio", cell: (row) => row.name || "—" },
    { id: "rut", label: "RUT", cell: (row) => <Rut value={row.rut} /> },
    { id: "status", label: "Estado", cell: (row) => <StatusText value={row.status} /> },
    { id: "date", label: "Fecha de pago", className: "mono", cell: (row) => day(row.payment_date) },
    { id: "amount", label: "Monto", className: "mono num", cell: (row) => money(row.amount, row.currency) },
  ];

  return (
    <main className="app-shell unified-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Cartera</p>
          <h1>{pageLabels.charges}</h1>
        </div>
      </div>
      {!canCharges && !canPayments ? (
        <p className="muted-copy">Tu rol no puede ver cobros ni pagos de ningún canal. Pide acceso a un administrador.</p>
      ) : <>
        <div className="recovery-tabs" role="tablist" aria-label="Tipo de registro">
          {canCharges ? <button type="button" role="tab" aria-selected={tab === "charges"} className={tab === "charges" ? "active" : ""} onClick={() => switchTab("charges")}>Cobros</button> : null}
          {canPayments ? <button type="button" role="tab" aria-selected={tab === "payments"} className={tab === "payments" ? "active" : ""} onClick={() => switchTab("payments")}>Pagos</button> : null}
        </div>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{tab === "charges" ? "Cobros de todos los canales" : "Pagos de todos los canales"}</p>
              <h3>Listado de {tab === "charges" ? "cobros" : "pagos"}</h3>
            </div>
          </div>
          <UnifiedFilterBar
            idPrefix={`cobros-${tab}`}
            channels={channels}
            channel={channel}
            onChannel={reset(setChannel)}
            statuses={facets.data?.statuses ?? []}
            status={status}
            onStatus={reset(setStatus)}
            fields={FIELDS[tab]}
            field={field}
            onField={reset(setField)}
            placeholder={tab === "charges" ? "ID de cobro, suscripción o estado" : "ID de pago, cobro o estado"}
            busy={busy || invertedRange}
            query={query}
            onQuery={reset(setQuery)}
            chips={extraChips}
            onClear={() => { setOutcome(""); setDateFrom(""); setDateTo(""); setOffset(0); }}
            count={busy ? null : list.data?.total ?? null}
            noun={tab === "charges" ? "cobros" : "pagos"}
            actions={
              <ExportButton
                entity={tab === "charges" ? "cobros" : "pagos"}
                canal={channel || undefined}
                params={filterParams}
                window={{ offset, limit: PAGE }}
                canPii={can("export.pii")}
              />
            }
          >
            <label className="filter-field">
              <span>Resultado</span>
              <select value={outcome} onChange={(event) => reset(setOutcome)(event.target.value)}>
                <option value="">Todos los resultados</option>
                {CHARGE_OUTCOMES.map((value) => <option key={value} value={value}>{tryLabel("chargeOutcome", value) ?? value}</option>)}
              </select>
            </label>
            <label className="filter-field">
              <span>Desde</span>
              <input type="date" value={dateFrom} max={dateTo || undefined} aria-invalid={invertedRange || undefined} onChange={(event) => reset(setDateFrom)(event.target.value)} />
            </label>
            <label className="filter-field">
              <span>Hasta</span>
              <input type="date" value={dateTo} min={dateFrom || undefined} aria-invalid={invertedRange || undefined} onChange={(event) => reset(setDateTo)(event.target.value)} />
            </label>
          </UnifiedFilterBar>
          {invertedRange ? (
            <p className="export-warning" role="alert">
              La fecha «Desde» ({day(dateFrom)}) es posterior a «Hasta» ({day(dateTo)}): no hay {tab === "charges" ? "cobros" : "pagos"} en un rango invertido. Corrige una de las dos fechas.
            </p>
          ) : null}
          {tab === "charges" ? <p className="muted-copy">Payku aparece con sus ciclos de cobro cuando existen; cada intento de cobro está en la pestaña Pagos.</p> : null}
          {list.data && !busy ? <ChannelTotals byChannel={list.data.by_channel} /> : null}
          {tab === "charges" ? <PortfolioTable key="charges" view="charges" caption="cobros" columns={chargeColumns}
            rows={((list.data?.items ?? []) as ChargeRow[]).filter((row) => row.charge_id !== undefined)} rowKey={(row, i) => `${row.channel}-${row.charge_id}-${i}`}
            loading={busy} error={list.error} forbidden={list.forbidden} onRetry={list.reload} filtered={filtered} onClear={clearAll} />
            : <PortfolioTable key="payments" view="payments" caption="pagos" columns={paymentColumns}
              rows={((list.data?.items ?? []) as PaymentRow[]).filter((row) => row.payment_id !== undefined)} rowKey={(row, i) => `${row.channel}-${row.payment_id}-${i}`}
              loading={busy} error={list.error} forbidden={list.forbidden} onRetry={list.reload} filtered={filtered} onClear={clearAll} />}
          {list.data ? <UnifiedPagination offset={offset} limit={PAGE} total={list.data.total} shown={list.data.items.length} onOffset={setOffset} loading={busy} /> : null}
        </section>
        {canCharges ? <RejectionSummaryPanel channel={channel} dateFrom={dateFrom} dateTo={dateTo} /> : null}
      </>}
    </main>
  );
}
