import { useState } from "react";
import { useDebouncedValue } from "../../hooks";
import { tryLabel } from "../../i18n/label";
import { ExportButton } from "../shared/ExportButton";
import { ChannelTotals, UnifiedFilterBar, UnifiedPagination } from "../general/UnifiedControls";
import { StatusText, channelText, day, detailPath, money } from "../general/unifiedDisplay";
import {
  CHARGE_OUTCOMES, VIEW_PERMISSIONS, canAny,
  type ChargeRow, type PaymentRow, type RejectionSummary, type StatusFacets, type UnifiedPage,
} from "../general/unifiedTypes";
import { cleanParams, useUnifiedGet } from "../general/useUnifiedList";

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
  const { data, loading, forbidden } = useUnifiedGet<RejectionSummary>("/api/v1/general/charges/summary", params);
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
        Rechazados / (pagados + rechazados), con fecha de cobro hasta hoy (hora de Chile) y sin cancelados, expirados ni anulados.
        VirtualPOS y TCH cuentan cargos; Toku y Payku cuentan intentos de cobro, porque el canal no marca el cargo como rechazado.
      </p>
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
  const open = (path: string | null) => (path && onOpenPath ? () => onOpenPath(path) : undefined);

  return (
    <main className="app-shell unified-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Cartera</p>
          <h1>Cobros</h1>
        </div>
      </div>
      {!canCharges && !canPayments ? (
        <p className="muted-copy">Tu rol no puede ver cobros ni pagos de ningún canal. Pide acceso a un administrador.</p>
      ) : <>
        {canCharges ? <RejectionSummaryPanel channel={channel} dateFrom={dateFrom} dateTo={dateTo} /> : null}
        <div className="recovery-tabs" role="tablist" aria-label="Tipo de registro">
          {canCharges ? <button type="button" role="tab" aria-selected={tab === "charges"} className={tab === "charges" ? "active" : ""} onClick={() => switchTab("charges")}>Cobros</button> : null}
          {canPayments ? <button type="button" role="tab" aria-selected={tab === "payments"} className={tab === "payments" ? "active" : ""} onClick={() => switchTab("payments")}>Pagos</button> : null}
        </div>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{tab === "charges" ? "Cobros de todos los canales" : "Pagos de todos los canales"}</p>
              <h3><span className="mono">{list.data ? list.data.total.toLocaleString("es-CL") : "…"}</span> {tab === "charges" ? "cobros" : "pagos"}</h3>
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
            query={query}
            onQuery={reset(setQuery)}
          >
            <label className="unified-filter">
              <span>Resultado</span>
              <select value={outcome} onChange={(event) => reset(setOutcome)(event.target.value)}>
                <option value="">Todos los resultados</option>
                {CHARGE_OUTCOMES.map((value) => <option key={value} value={value}>{tryLabel("chargeOutcome", value) ?? value}</option>)}
              </select>
            </label>
            <label className="unified-filter">
              <span>Desde</span>
              <input type="date" value={dateFrom} onChange={(event) => reset(setDateFrom)(event.target.value)} />
            </label>
            <label className="unified-filter">
              <span>Hasta</span>
              <input type="date" value={dateTo} onChange={(event) => reset(setDateTo)(event.target.value)} />
            </label>
            <ExportButton
              entity={tab === "charges" ? "cobros" : "pagos"}
              canal={channel || undefined}
              params={filterParams}
              window={{ offset, limit: PAGE }}
              canPii={can("export.pii")}
            />
          </UnifiedFilterBar>
          {tab === "charges" ? <p className="muted-copy">Payku no tiene cobros propios: sus intentos de cobro están en la pestaña Pagos.</p> : null}
          {list.data ? <ChannelTotals byChannel={list.data.by_channel} /> : null}
          {list.error ? <p className="error-message" role="alert">{list.error}</p> : null}
          {list.forbidden ? <p className="muted-copy">Tu rol no puede ver este canal.</p> : null}
          <div className="table-wrap" aria-busy={list.loading}>
            {tab === "charges" ? (
              <table>
                <thead><tr><th>Canal</th><th>ID de cobro</th><th>Suscripción</th><th>Socio</th><th>RUT</th><th>Estado</th><th>Fecha de cobro</th><th>Período</th><th>Monto</th><th>Motivo de rechazo</th></tr></thead>
                <tbody>
                  {((list.data?.items ?? []) as ChargeRow[]).map((row) => {
                    const go = open(detailPath("charge", row.channel, row.charge_id));
                    return (
                      <tr key={`${row.channel}-${row.charge_id}`}>
                        <td>{channelText(row.channel)}</td>
                        <td className="mono">{go ? <button type="button" className="text-button" onClick={go}>{row.charge_id}</button> : row.charge_id}</td>
                        <td className="mono">{row.subscription_id ?? "—"}</td>
                        <td>{row.name || "—"}</td>
                        <td className="mono">{row.rut || "—"}</td>
                        <td><StatusText value={row.status} /></td>
                        <td className="mono">{day(row.charge_date)}</td>
                        <td className="mono">{row.period ?? "—"}</td>
                        <td className="mono">{money(row.amount, row.currency)}</td>
                        <td>{row.rejection_reason ? <span data-raw-text>{row.rejection_reason}</span> : "—"}</td>
                      </tr>
                    );
                  })}
                  {!list.loading && list.data && list.data.items.length === 0 ? <tr><td colSpan={10}>Sin cobros con estos filtros.</td></tr> : null}
                </tbody>
              </table>
            ) : (
              <table>
                <thead><tr><th>Canal</th><th>ID de pago</th><th>ID de cobro</th><th>Socio</th><th>RUT</th><th>Estado</th><th>Fecha de pago</th><th>Monto</th></tr></thead>
                <tbody>
                  {((list.data?.items ?? []) as PaymentRow[]).map((row) => {
                    const go = open(detailPath("payment", row.channel, row.payment_id));
                    return (
                      <tr key={`${row.channel}-${row.payment_id}`}>
                        <td>{channelText(row.channel)}</td>
                        <td className="mono">{go ? <button type="button" className="text-button" onClick={go}>{row.payment_id}</button> : row.payment_id}</td>
                        <td className="mono">{row.charge_id ?? "—"}</td>
                        <td>{row.name || "—"}</td>
                        <td className="mono">{row.rut || "—"}</td>
                        <td><StatusText value={row.status} /></td>
                        <td className="mono">{day(row.payment_date)}</td>
                        <td className="mono">{money(row.amount, row.currency)}</td>
                      </tr>
                    );
                  })}
                  {!list.loading && list.data && list.data.items.length === 0 ? <tr><td colSpan={8}>Sin pagos con estos filtros.</td></tr> : null}
                </tbody>
              </table>
            )}
          </div>
          {list.data ? <UnifiedPagination offset={offset} limit={PAGE} total={list.data.total} shown={list.data.items.length} onOffset={setOffset} /> : null}
        </section>
      </>}
    </main>
  );
}
