import { useId, useRef, useState, type ReactNode } from "react";
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
export function ActiveFilters({ chips, onClear, count, noun, loading = false }: {
  chips: FilterChip[];
  onClear: () => void;
  count?: number | null;
  noun: string;
  loading?: boolean;
}) {
  return (
    <div className="filter-summary">
      <p className="filter-count" aria-live="polite">
        {count === null || count === undefined ? (loading ? "Actualizando resultados…" : "Sin recuento disponible") : <><span className="mono">{count.toLocaleString("es-CL")}</span> {noun}</>}
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

/** Search is always visible; advanced controls keep their values when the native disclosure is closed. */
export function PortfolioFilters({ searchLabel = "Buscar", placeholder, query, onQuery, fieldLabel, channelControl, actions, advanced, activeCount, chips, onClear, count, noun, busy = false }: {
  searchLabel?: string; placeholder: string; query: string; onQuery: (value: string) => void; fieldLabel: string;
  channelControl: ReactNode; actions?: ReactNode; advanced: ReactNode; activeCount: number;
  chips: FilterChip[]; onClear: () => void; count?: number | null; noun: string; busy?: boolean;
}) {
  const hintId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  return <div className="filter-bar portfolio-filters">
    <div className="portfolio-filter-primary">
      <label className="filter-field portfolio-search">
        <span>{searchLabel}</span>
        <span className="portfolio-search-input">
          <input ref={input} type="search" aria-label={searchLabel} placeholder={placeholder} value={query} aria-describedby={hintId} onChange={(event) => onQuery(event.target.value)} />
          {query ? <button type="button" aria-label="Borrar búsqueda" onClick={() => { onQuery(""); input.current?.focus(); }}>×</button> : null}
        </span>
        <small id={hintId} className={fieldLabel === "Todos los campos" ? "sr-only" : undefined}>Busca en {fieldLabel === "Todos los campos" ? "todos los campos" : fieldLabel}. Los resultados se actualizan al escribir.</small>
      </label>
      {channelControl}
      {actions ? <fieldset className="filter-actions portfolio-export" disabled={busy}><legend className="sr-only">Exportación</legend>{actions}</fieldset> : null}
    </div>
    <details className="portfolio-more-filters" open={advancedOpen}>
      <summary onClick={(event) => { event.preventDefault(); setAdvancedOpen((value) => !value); }}>Más filtros{" "}{activeCount > 0 ? <span className="portfolio-filter-badge">{activeCount} {activeCount === 1 ? "activo" : "activos"}</span> : null}</summary>
      <div className="filter-fields" hidden={!advancedOpen}>{advanced}</div>
    </details>
    <ActiveFilters chips={chips} onClear={onClear} count={count} noun={noun} loading={busy} />
  </div>;
}

/**
 * Barra de filtros común (Cobros y Suscripciones): canal, estado y búsqueda por campo, más filtros propios
 * (`children`), acciones como Exportar (`actions`) y el resumen con chips. Los chips de canal, estado y texto se
 * arman aquí; la vista agrega los suyos en `chips` y su limpieza en `onClear`.
 */
export function UnifiedFilterBar({
  idPrefix, channels, channel, onChannel, statuses, status, onStatus, fields, field, onField, query, onQuery, children,
  actions, chips = [], onClear, count, noun = "resultados", placeholder = "Buscar por ID o estado", busy = false,
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
  placeholder?: string;
  busy?: boolean;
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
    onChannel(""); onStatus(""); onField("all"); onQuery("");
    onClear?.();
  };
  return <PortfolioFilters query={query} onQuery={onQuery} placeholder={placeholder} busy={busy}
    fieldLabel={fieldLabel} count={count} noun={noun} chips={[...base, ...chips]} onClear={clearAll}
    activeCount={Number(Boolean(status)) + Number(field !== "all") + chips.length} actions={actions}
    channelControl={<label className="filter-field"><span>Canal</span>
      <select id={`${idPrefix}-canal`} value={channel} onChange={(event) => onChannel(event.target.value)}>
        <option value="">Todos los canales</option>
        {channel && !options.some((option) => option.value === channel) ? <option value={channel}>{channelText(channel)}</option> : null}
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>}
    advanced={<>
      <label className="filter-field"><span>Estado</span>
        <select id={`${idPrefix}-estado`} value={status} onChange={(event) => onStatus(event.target.value)}>
          <option value="">Todos los estados</option>
          {status && !statuses.some((facet) => facet.status === status) ? <option value={status}>{statusLabel(status)}</option> : null}
          {statuses.map((facet) => <option key={facet.status} value={facet.status}>{`${statusLabel(facet.status)} (${facet.count.toLocaleString("es-CL")})`}</option>)}
        </select>
      </label>
      <label className="filter-field"><span>Buscar en</span>
        <select id={`${idPrefix}-campo`} value={field} onChange={(event) => onField(event.target.value)}>
          {fields.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      {children}
    </>} />;
}

export function UnifiedPagination({ offset, limit, total, shown, onOffset, loading = false }: {
  offset: number; limit: number; total: number; shown: number; onOffset: (offset: number) => void; loading?: boolean;
}) {
  if (total <= limit && offset === 0) return null;
  return (
    <nav className="pagination portfolio-pagination" aria-label="Paginación">
      {offset > 0 ? <button type="button" disabled={loading} onClick={() => onOffset(0)}>Primera página</button> : null}
      <button type="button" disabled={loading || offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>← Anterior</button>
      <span className="mono">{shown === 0 ? "0" : `${offset + 1}-${Math.min(offset + shown, total)}`} de {total.toLocaleString("es-CL")}</span>
      <button type="button" disabled={loading || offset + limit >= total} onClick={() => onOffset(offset + limit)}>Siguiente →</button>
    </nav>
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
