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

export const facetStatusLabel = (value: string) => tryLabel("status", value) ?? tryLabel("tchStatus", value) ?? value;

/**
 * Etiquetas del filtro «Estado» (QA-09). Cada canal escribe el mismo estado a su manera (`PAID`, `paid`, `pagado`) y
 * todos se traducen a «Pagado»; si una etiqueta se repite se le agrega el canal («Pagado · Toku») y, si aún se repite
 * (dos textos del mismo canal), el texto crudo del proveedor. Las etiquetas únicas quedan como estaban.
 */
export function statusFacetLabels(facets: StatusFacet[]): Map<string, string> {
  const tally = (labels: Map<string, string>) => {
    const counts = new Map<string, number>();
    for (const value of labels.values()) counts.set(value, (counts.get(value) ?? 0) + 1);
    return counts;
  };
  const labels = new Map(facets.map((facet) => [facet.status, facetStatusLabel(facet.status)]));
  const first = tally(labels);
  for (const facet of facets) {
    const base = labels.get(facet.status)!;
    if ((first.get(base) ?? 0) < 2) continue;
    const where = (facet.channels ?? []).map((channel) => channelText(channel)).join(", ");
    labels.set(facet.status, where ? `${base} · ${where}` : `${base} · ${facet.status.trim()}`);
  }
  const second = tally(labels);
  for (const facet of facets) {
    const current = labels.get(facet.status)!;
    if ((second.get(current) ?? 0) > 1) labels.set(facet.status, `${current} (${facet.status.trim()})`);
  }
  return labels;
}

/** Filtro activo como chip: «Canal: Toku ×». `onRemove` lo quita. */
export type FilterChip = { key: string; label: string; onRemove: () => void };

/**
 * Resumen de filtros (d143): contador de resultados, chips de los filtros activos con «×» para quitar cada uno y
 * «Limpiar filtros». Lo usan Cobros, Suscripciones y Socios.
 */
export function ActiveFilters({ chips, onClear, count, noun }: {
  chips: FilterChip[];
  onClear: () => void;
  count?: number | null;
  noun: string;
}) {
  return (
    <div className="filter-summary">
      <p className="filter-count" aria-live="polite">
        {count === null || count === undefined ? "…" : <><span className="mono">{count.toLocaleString("es-CL")}</span> {noun}</>}
      </p>
      {chips.length > 0 ? (
        <>
          <ul className="filter-chips" aria-label="Filtros activos">
            {chips.map((chip) => (
              <li key={chip.key} className="filter-chip">
                <span>{chip.label}</span>
                <button type="button" aria-label={`Quitar filtro ${chip.label}`} onClick={chip.onRemove}>×</button>
              </li>
            ))}
          </ul>
          <button type="button" className="filter-clear" onClick={onClear}>Limpiar filtros</button>
        </>
      ) : null}
    </div>
  );
}

/**
 * Barra de filtros común (Cobros y Suscripciones): canal, estado y búsqueda por campo, más filtros propios
 * (`children`), acciones como Exportar (`actions`) y el resumen con chips. Los chips de canal, estado y texto se
 * arman aquí; la vista agrega los suyos en `chips` y su limpieza en `onClear`.
 */
export function UnifiedFilterBar({
  idPrefix, channels, channel, onChannel, statuses, status, onStatus, fields, field, onField, query, onQuery, children,
  actions, chips = [], onClear, count, noun = "resultados",
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
  actions?: ReactNode;
  chips?: FilterChip[];
  onClear?: () => void;
  count?: number | null;
  noun?: string;
}) {
  const facetLabels = statusFacetLabels(statuses);
  const statusLabel = (value: string) => facetLabels.get(value) ?? facetStatusLabel(value);
  const options = channelOptions(channels);
  const channelLabel = options.find((option) => option.value === channel)?.label ?? channelText(channel);
  const fieldLabel = fields.find((option) => option.value === field)?.label ?? field;
  const base: FilterChip[] = [];
  if (channel) base.push({ key: "canal", label: `Canal: ${channelLabel}`, onRemove: () => onChannel("") });
  if (status) base.push({ key: "estado", label: `Estado: ${statusLabel(status)}`, onRemove: () => onStatus("") });
  if (query.trim()) {
    base.push({
      key: "texto",
      label: field === "all" ? `Texto: «${query.trim()}»` : `${fieldLabel}: «${query.trim()}»`,
      onRemove: () => { onQuery(""); onField("all"); },
    });
  }
  const clearAll = () => {
    for (const chip of base) chip.onRemove();
    onClear?.();
  };
  return (
    <div className="filter-bar">
      <div className="filter-row">
        <div className="filter-fields">
          <label className="filter-field">
            <span>Canal</span>
            <select id={`${idPrefix}-canal`} value={channel} onChange={(event) => onChannel(event.target.value)}>
              <option value="">Todos los canales</option>
              {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="filter-field">
            <span>Estado</span>
            <select id={`${idPrefix}-estado`} value={status} onChange={(event) => onStatus(event.target.value)}>
              <option value="">Todos los estados</option>
              {status && !statuses.some((facet) => facet.status === status) ? <option value={status}>{statusLabel(status)}</option> : null}
              {statuses.map((facet) => (
                <option key={facet.status} value={facet.status}>{`${statusLabel(facet.status)} (${facet.count.toLocaleString("es-CL")})`}</option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Buscar en</span>
            <select id={`${idPrefix}-campo`} value={field} onChange={(event) => onField(event.target.value)}>
              {fields.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="filter-field filter-field-wide">
            <span>Texto</span>
            <input id={`${idPrefix}-buscar`} type="search" placeholder="Buscar" value={query} onChange={(event) => onQuery(event.target.value)} />
          </label>
          {children}
        </div>
        {actions ? <div className="filter-actions">{actions}</div> : null}
      </div>
      <ActiveFilters chips={[...base, ...chips]} onClear={clearAll} count={count} noun={noun} />
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
