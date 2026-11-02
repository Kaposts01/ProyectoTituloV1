import type { ReactNode } from "react";
import type { StatusFacet } from "./unifiedTypes";
import { channelText } from "./unifiedDisplay";
import { tryLabel } from "../../i18n/label";

/** Opciones del filtro de canal a partir de los canales permitidos (`canales` de la API). */
export function channelOptions(channels: string[]): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const vp = channels.filter((value) => value.startsWith("virtualpos"));
  if (vp.length > 1) out.push({ value: "virtualpos", label: "VirtualPOS (ambas cuentas)" });
  for (const value of channels) out.push({ value, label: channelText(value) });
  return out;
}

/** Barra de filtros común: canal, estado, búsqueda por campo y espacio para filtros propios y el botón Exportar. */
export function UnifiedFilterBar({
  idPrefix, channels, channel, onChannel, statuses, status, onStatus, fields, field, onField, query, onQuery, children,
}: {
  idPrefix: string;
  channels: string[];
  channel: string;
  onChannel: (value: string) => void;
  statuses: StatusFacet[];
  status: string;
  onStatus: (value: string) => void;
  fields: { value: string; label: string }[];
  field: string;
  onField: (value: string) => void;
  query: string;
  onQuery: (value: string) => void;
  children?: ReactNode;
}) {
  const statusLabel = (value: string) => tryLabel("status", value) ?? tryLabel("tchStatus", value) ?? value;
  return (
    <div className="table-filters unified-filters">
      <label className="unified-filter">
        <span>Canal</span>
        <select id={`${idPrefix}-canal`} value={channel} onChange={(event) => onChannel(event.target.value)}>
          <option value="">Todos los canales</option>
          {channelOptions(channels).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label className="unified-filter">
        <span>Estado</span>
        <select id={`${idPrefix}-estado`} value={status} onChange={(event) => onStatus(event.target.value)}>
          <option value="">Todos los estados</option>
          {status && !statuses.some((facet) => facet.status === status) ? <option value={status}>{statusLabel(status)}</option> : null}
          {statuses.map((facet) => (
            <option key={facet.status} value={facet.status}>{`${statusLabel(facet.status)} (${facet.count.toLocaleString("es-CL")})`}</option>
          ))}
        </select>
      </label>
      <label className="unified-filter">
        <span>Buscar en</span>
        <select id={`${idPrefix}-campo`} value={field} onChange={(event) => onField(event.target.value)}>
          {fields.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label className="unified-filter unified-filter-search">
        <span>Texto</span>
        <input id={`${idPrefix}-buscar`} type="search" placeholder="Buscar" value={query} onChange={(event) => onQuery(event.target.value)} />
      </label>
      {children}
    </div>
  );
}

export function UnifiedPagination({ offset, limit, total, shown, onOffset }: {
  offset: number; limit: number; total: number; shown: number; onOffset: (offset: number) => void;
}) {
  if (total <= limit && offset === 0) return null;
  return (
    <div className="pagination">
      <button type="button" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>← Anterior</button>
      <span className="mono">{total === 0 ? "0" : `${offset + 1}-${offset + shown}`} de {total.toLocaleString("es-CL")}</span>
      <button type="button" disabled={offset + limit >= total} onClick={() => onOffset(offset + limit)}>Siguiente →</button>
    </div>
  );
}

/** Totales por canal con los filtros activos («VirtualPOS 120 · Toku 30»). */
export function ChannelTotals({ byChannel }: { byChannel: Record<string, number> }) {
  const entries = Object.entries(byChannel);
  if (entries.length === 0) return null;
  return (
    <p className="muted-copy unified-totals">
      {entries.map(([channel, count], index) => (
        <span key={channel}>{index > 0 ? " · " : ""}{channelText(channel)} <span className="mono">{count.toLocaleString("es-CL")}</span></span>
      ))}
    </p>
  );
}
