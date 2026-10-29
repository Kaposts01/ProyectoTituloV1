import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./billingApi";
import { describeBillingError } from "./billingErrors";
import { formatClp, formatDateTime, PLATFORM_LABELS } from "./billingLabels";
import {
  closeReasonLabel, daysText, EMPTY_RENEWAL_FILTERS, isOpenRenewal, renewalPriorityLabel, renewalPriorityTone, renewalStatusLabel,
  renewalStatusTone, type RenewalFilters, type RenewalStatusFilter,
} from "./billingRenewal";
import { lastPageOffset } from "./billingQuery";
import { PERM_REQUEST, type Platform, type RenewalPriority, type RenewalTask, type RenewalTaskList } from "./types";
import { Badge, Cell, FiltersPanel, Notice } from "./ui";

const PAGE_SIZE = 25;
const STATUS_OPTIONS: Array<[RenewalStatusFilter, string]> = [
  ["open", "Abiertas y vencidas"], ["abierta", "Abierta"], ["vencida", "Vencida"], ["cerrada", "Cerrada"], ["no_aplica", "No aplica"], ["all", "Todos los estados"],
];
const isDefaultFilters = (f: RenewalFilters) => f.status === "open" && !f.priority && !f.platform && !f.subscription.trim();

type Props = {
  can: (permission: string) => boolean;
  /** Cambia al crear/modificar solicitudes para volver a cargar las tareas. */
  refreshKey: number;
  onViewRequest: (requestId: string) => void;
  onRequestRenewal: (task: RenewalTask) => void;
};

/** Sección «Renovaciones»: tareas de renovación de calendario. El chequeo solo crea la tarea; un humano decide si solicita la renovación. */
export function RenewalTasksView({ can, refreshKey, onViewRequest, onRequestRenewal }: Props) {
  const [draft, setDraft] = useState<RenewalFilters>(EMPTY_RENEWAL_FILTERS);
  const [applied, setApplied] = useState<RenewalFilters>(EMPTY_RENEWAL_FILTERS);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<RenewalTaskList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (filters: RenewalFilters, nextOffset: number) => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.fetchRenewalTasks(filters, nextOffset, PAGE_SIZE);
      if (mine !== seq.current) return;
      // Se actuó sobre el último ítem de la última página: la página quedó vacía pero hay datos. Se reposiciona.
      const back = lastPageOffset(result.total, PAGE_SIZE);
      if (result.items.length === 0 && result.total > 0 && nextOffset > 0 && back < nextOffset) {
        setOffset(back);
        return;
      }
      setData(result);
    } catch (err) {
      if (mine !== seq.current) return;
      setError(describeBillingError(err, "No se pudieron cargar las tareas de renovación.").message);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(applied, offset); }, [load, applied, offset, refreshKey]);

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    setOffset(0);
    setApplied(draft);
  }
  function clearFilters() {
    setDraft(EMPTY_RENEWAL_FILTERS);
    setApplied(EMPTY_RENEWAL_FILTERS);
    setOffset(0);
  }
  const setField = <K extends keyof RenewalFilters>(key: K, value: RenewalFilters[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const activeFilterCount =
    (applied.status !== "open" ? 1 : 0) + (applied.priority ? 1 : 0) + (applied.platform ? 1 : 0) + (applied.subscription.trim() ? 1 : 0);
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const canRequest = can(PERM_REQUEST);

  return (
    <section aria-label="Renovaciones de calendario">
      <form className="bx-filters" onSubmit={applyFilters} aria-label="Filtros de renovaciones">
        <FiltersPanel activeCount={activeFilterCount}>
          <label>Estado
            <select value={draft.status} onChange={(e) => setField("status", e.target.value as RenewalStatusFilter)}>
              {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label>Prioridad
            <select value={draft.priority} onChange={(e) => setField("priority", e.target.value as RenewalPriority | "")}>
              <option value="">Todas</option>
              <option value="alta">Alta</option>
              <option value="normal">Normal</option>
            </select>
          </label>
          <label>Plataforma
            <select value={draft.platform} onChange={(e) => setField("platform", e.target.value as Platform | "")}>
              <option value="">Todas</option>
              {Object.entries(PLATFORM_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label>Suscripción
            <input className="mono" value={draft.subscription} maxLength={255} onChange={(e) => setField("subscription", e.target.value)} />
          </label>
          <button type="submit" className="bx-btn bx-btn-primary" disabled={loading}>Buscar</button>
          <button type="button" className="bx-btn bx-btn-ghost" onClick={clearFilters} disabled={loading}>Limpiar</button>
        </FiltersPanel>
      </form>

      {error ? (
        <Notice tone="error">
          {error}{" "}
          <button className="bx-btn bx-btn-ghost" onClick={() => void load(applied, offset)}>Reintentar</button>
        </Notice>
      ) : null}

      <p className="bx-sr" role="status" aria-live="polite">
        {loading ? "Cargando renovaciones…" : data ? `${total} tareas de renovación.` : ""}
      </p>
      {loading && !data ? <p className="muted-copy">Cargando renovaciones…</p> : null}

      {data && items.length === 0 && total === 0 && !error ? (
        <div className="bx-notice">
          <p style={{ margin: "0 0 8px" }}>{isDefaultFilters(applied) ? "No hay renovaciones pendientes." : "No hay renovaciones con estos filtros."}</p>
          {!isDefaultFilters(applied) ? <button className="bx-btn bx-btn-ghost" onClick={clearFilters}>Limpiar filtros</button> : null}
        </div>
      ) : null}

      {items.length > 0 ? (
        <div className="table-wrap" aria-busy={loading}>
          <table className="bx-table bx-stack bx-stack-renewals" role="table">
            <caption className="bx-sr">Tareas de renovación de calendario</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th role="columnheader" scope="col">Suscripción</th><th role="columnheader" scope="col">Plataforma</th><th role="columnheader" scope="col">Prioridad</th><th role="columnheader" scope="col">Estado</th>
                <th role="columnheader" scope="col">Fecha límite</th><th role="columnheader" scope="col" className="num">Último monto programado</th><th role="columnheader" scope="col">Acción</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {items.map((t) => {
                const open = isOpenRenewal(t.status);
                const days = open ? daysText(t.days_remaining) : null;
                const viewRequest = t.request_id ? (
                  <button className="bx-btn bx-btn-ghost" onClick={() => onViewRequest(t.request_id as string)}
                    aria-label={`Ver solicitud de la suscripción ${t.subscription_external_id}`}>Ver solicitud</button>
                ) : null;
                return (
                  <tr role="row" key={t.id}>
                    <Cell label="Suscripción" className="mono bx-c-sub">{t.subscription_external_id}</Cell>
                    <Cell label="Plataforma" className="bx-c-platform">{PLATFORM_LABELS[t.platform] ?? t.platform}</Cell>
                    <Cell label="Prioridad" className="bx-c-priority"><Badge tone={renewalPriorityTone(t.priority)}>{renewalPriorityLabel(t.priority)}</Badge></Cell>
                    <Cell label="Estado" className="bx-c-status">
                      <Badge tone={renewalStatusTone(t.status)}>{renewalStatusLabel(t.status)}</Badge>
                      {open && t.data_stale ? (
                        <div className="bx-sub">
                          <Badge tone="warning">Datos desactualizados</Badge>
                          <span className="bx-sr"> La última sincronización de la plataforma es antigua o falló; confirme los datos antes de solicitar la renovación.</span>
                        </div>
                      ) : null}
                    </Cell>
                    <Cell label="Fecha límite" className="bx-c-deadline bx-lbl">
                      <span className="mono">{formatDateTime(t.due_date)}</span>
                      {days ? <div className="mono bx-sub">{days}</div> : null}
                    </Cell>
                    <Cell label="Último monto programado" className="mono num bx-c-amount bx-lbl">{formatClp(t.scheduled_amount)}</Cell>
                    <Cell label="Acción" className="bx-c-action">
                      {open ? (
                        viewRequest ?? (canRequest ? (
                          <button className="bx-btn bx-btn-primary" onClick={() => onRequestRenewal(t)}
                            aria-label={`Solicitar renovación de la suscripción ${t.subscription_external_id}`}>Solicitar renovación</button>
                        ) : <span className="bx-sub">—</span>)
                      ) : (
                        <div>
                          <span>{closeReasonLabel(t.close_reason)}</span>
                          {viewRequest ? <div className="bx-sub">{viewRequest}</div> : null}
                        </div>
                      )}
                    </Cell>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {data && total > 0 ? (
        <div className="bx-pagination">
          <button className="bx-btn bx-btn-ghost" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</button>
          <span className="mono">{offset + 1}-{Math.min(offset + PAGE_SIZE, total)} de {total}</span>
          <button className="bx-btn bx-btn-ghost" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</button>
        </div>
      ) : null}
    </section>
  );
}
