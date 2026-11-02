import { useState } from "react";
import { friendlyError, getJson } from "../../api";
import { labelOr, tryLabel } from "../../i18n/label";
import { text } from "../shared/utils";
import { clpOrDash } from "./format";
import {
  CHANNEL_RECOVERY, EMPTY_CHANNEL_FILTERS, EMPTY_REASON_TEXT, channelListPath,
  type ChannelFilters, type ChannelView, type ReadOnlyChannel, type RecoveryColumn,
} from "./channelRecoveryViews";

type Row = Record<string, unknown>;
type Page = { items: Row[]; total: number; offset: number; limit: number; empty_reason?: string | null };

const PAGE_SIZE = 50;
const REASONS: { value: string; label: string }[] = [
  { value: "blocked_card", label: "Tarjeta bloqueada" },
  { value: "expired_card", label: "Tarjeta vencida" },
  { value: "streak", label: "Racha de cuotas impagas" },
];

function money(row: Row, key: string): string {
  const value = row[key];
  if (row.currency === "UF" && value !== null && value !== undefined && value !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? `${n.toLocaleString("es-CL", { maximumFractionDigits: 4 })} UF` : "—";
  }
  return clpOrDash(value);
}

function cell(row: Row, column: RecoveryColumn): { content: string; mono: boolean } {
  const value = row[column.key];
  switch (column.kind) {
    case "money": return { content: money(row, column.key), mono: true };
    case "status": return { content: labelOr("status", value, "—"), mono: false };
    case "tchStatus": return { content: tryLabel("tchStatus", value) ?? labelOr("status", value, "—"), mono: false };
    case "recoverableReason": return { content: labelOr("recoverableReason", value, "—"), mono: false };
    case "id": case "date": case "number":
      return { content: typeof value === "number" ? value.toLocaleString("es-CL") : text(value, "—"), mono: true };
    default: return { content: text(value, "—"), mono: false };
  }
}

/** Pestaña de solo lectura del recuperador general (Toku o TCH). */
export function ChannelRecoveryPanel({ channel }: { channel: ReadOnlyChannel }) {
  const config = CHANNEL_RECOVERY[channel];
  const [view, setView] = useState<ChannelView>(config.views[0]);
  const [filters, setFilters] = useState<ChannelFilters>(EMPTY_CHANNEL_FILTERS);
  const [applied, setApplied] = useState<{ view: ChannelView; filters: ChannelFilters } | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setFilter = (key: keyof ChannelFilters, value: string) => setFilters((current) => ({ ...current, [key]: value }));

  async function load(offset = 0, state = { view, filters }) {
    setLoading(true);
    setError(null);
    try {
      setPage(await getJson<Page>(channelListPath(state.view, state.filters, offset, PAGE_SIZE)));
      setApplied(state);
    } catch (err) {
      setError(friendlyError(err, "No se pudieron cargar los registros de recuperación."));
    } finally {
      setLoading(false);
    }
  }

  const shown = applied?.view ?? view;
  const emptyText = page?.empty_reason ? EMPTY_REASON_TEXT[page.empty_reason] ?? "Sin registros." : "Sin registros para los filtros seleccionados.";

  return (
    <section aria-label={`Recuperador ${config.label}`}>
      <p className="muted-copy">{config.notice}</p>
      <div className="recovery-tabs" role="tablist" aria-label={`Vistas de ${config.label}`}>
        {config.views.map((item) => (
          <button key={item.id} role="tab" aria-selected={view.id === item.id} className={view.id === item.id ? "active" : ""}
            onClick={() => { setView(item); setPage(null); setApplied(null); setError(null); }}>
            {item.label}
          </button>
        ))}
      </div>
      <div className="recovery-controls">
        {view.dateLabels ? <>
          <label>{view.dateLabels.from}<input type="date" value={filters.dateFrom} onChange={(event) => setFilter("dateFrom", event.target.value)} /></label>
          <label>{view.dateLabels.to}<input type="date" value={filters.dateTo} onChange={(event) => setFilter("dateTo", event.target.value)} /></label>
        </> : null}
        {view.reasonFilter ? (
          <label>Motivo
            <select value={filters.reason} onChange={(event) => setFilter("reason", event.target.value)}>
              <option value="">Todos los motivos</option>
              {REASONS.map((reason) => <option key={reason.value} value={reason.value}>{reason.label}</option>)}
            </select>
          </label>
        ) : null}
        <button className="primary-button" onClick={() => void load(0)} disabled={loading}>{loading ? "Cargando..." : "Buscar"}</button>
      </div>
      {error ? <p className="error-message">{error}</p> : null}
      {page && applied ? <>
        <section className="panel recovery-table"><div className="table-wrap"><table>
          <thead><tr>{shown.columns.map((column) => <th key={column.key}>{column.header}</th>)}</tr></thead>
          <tbody>
            {page.items.map((row, index) => (
              <tr key={`${String(row.charge_id ?? row.subscription_id ?? "")}-${index}`}>
                {shown.columns.map((column) => {
                  const { content, mono } = cell(row, column);
                  return <td key={column.key} className={mono ? "mono" : undefined} data-raw-text={column.kind === "reason" ? true : undefined}>{content}</td>;
                })}
              </tr>
            ))}
            {page.items.length === 0 ? <tr><td colSpan={shown.columns.length}>{emptyText}</td></tr> : null}
          </tbody>
        </table></div></section>
        <div className="recovery-pagination">
          <button className="secondary-button" disabled={page.offset === 0 || loading} onClick={() => void load(Math.max(0, page.offset - PAGE_SIZE), applied)}>Anterior</button>
          <span className="mono">{page.total ? `${page.offset + 1}-${Math.min(page.offset + page.limit, page.total)} de ${page.total.toLocaleString("es-CL")}` : "0 registros"}</span>
          <button className="secondary-button" disabled={page.offset + page.limit >= page.total || loading} onClick={() => void load(page.offset + page.limit, applied)}>Siguiente</button>
        </div>
      </> : !loading ? <p className="muted-copy">Elige los filtros (opcionales) y pulsa «Buscar» para ver los registros de {shown.label.toLowerCase()}.</p> : null}
    </section>
  );
}
