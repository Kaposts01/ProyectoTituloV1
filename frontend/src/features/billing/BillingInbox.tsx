import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./billingApi";
import { describeBillingError } from "./billingErrors";
import {
  ALL_STATUSES, CHILE_TZ_NOTE, expiryText, formatDateTime, PLATFORM_LABELS, REQUEST_TYPES, requestSummary, statusLabel, TYPE_LABELS,
  HISTORY_STATUSES, PENDING_STATUSES,
} from "./billingLabels";
import { EMPTY_FILTERS, lastPageOffset, validateFilters, type InboxFilters, type InboxTab } from "./billingQuery";
import { CreateRequestDialog, type RenewalPrefill } from "./CreateRequestDialog";
import { RenewalTasksView } from "./RenewalTasksView";
import { RequestDetail } from "./RequestDetail";
import { PERM_REQUEST, type BillingList, type BillingRequestDetail, type Platform, type RenewalTask, type Requester, type RequestStatus, type RequestType } from "./types";
import { Notice, StatusBadge } from "./ui";
import "./billing.css";

const PAGE_SIZE = 25;
type View = InboxTab | "renewals";
const TAB_LABELS: Record<View, string> = { pending: "Pendientes", history: "Historial", renewals: "Renovaciones" };

type Props = {
  can: (permission: string) => boolean;
  /** Id del usuario actual, solo para el atajo «Mis solicitudes». */
  currentUserId?: string;
  /** Rol admin: puede retirar solicitudes ajenas (AP-33). */
  isAdmin?: boolean;
};


export function BillingInbox({ can, currentUserId, isAdmin = false }: Props) {
  const [tab, setTab] = useState<View>("pending");
  const listTab: InboxTab = tab === "renewals" ? "pending" : tab;
  const [draft, setDraft] = useState<InboxFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<InboxFilters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<BillingList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [prefill, setPrefill] = useState<RenewalPrefill | undefined>(undefined);
  const [renewalKey, setRenewalKey] = useState(0);
  const [alertCount, setAlertCount] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const seq = useRef(0);
  const [reloadKey, setReloadKey] = useState(0);
  const tabRefs = useRef<Partial<Record<View, HTMLButtonElement | null>>>({});
  const [requesters, setRequesters] = useState<Requester[]>([]);
  const [requestersState, setRequestersState] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(async (nextTab: InboxTab, filters: InboxFilters, nextOffset: number) => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.fetchRequests(nextTab, filters, nextOffset, PAGE_SIZE);
      if (mine !== seq.current) return;
      // Se actuó sobre el último ítem de la última página: la página pedida quedó vacía pero hay datos. Se reposiciona.
      const back = lastPageOffset(result.total, PAGE_SIZE);
      if (result.items.length === 0 && result.total > 0 && nextOffset > 0 && back < nextOffset) {
        setOffset(back);
        return;
      }
      setData(result);
    } catch (err) {
      if (mine !== seq.current) return;
      setError(describeBillingError(err, "No se pudo cargar la bandeja de solicitudes.").message);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(listTab, applied, offset); }, [load, listTab, applied, offset, reloadKey]);

  const loadRequesters = useCallback(async () => {
    setRequestersState("loading");
    try {
      const result = await api.fetchRequesters();
      setRequesters(result.items);
      setRequestersState("ready");
    } catch {
      setRequestersState("error");
    }
  }, []);

  useEffect(() => { void loadRequesters(); }, [loadRequesters]);

  // Contador de la pestaña «Renovaciones»: si falla, se omite sin molestar (la sección muestra su propio error).
  useEffect(() => {
    let alive = true;
    api.fetchRenewalAlertCount().then((r) => { if (alive) setAlertCount(r.total); }).catch(() => { if (alive) setAlertCount(0); });
    return () => { alive = false; };
  }, [renewalKey]);

  function changeTab(next: View, force = false) {
    if (next === tab && !force) return;
    setTab(next);
    setOffset(0);
    setSelectedId(null);
    setDraft((d) => ({ ...d, status: "" }));
    setApplied((a) => ({ ...a, status: "" }));
  }

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    const problem = validateFilters(draft);
    setFilterError(problem);
    if (problem) return;
    setOffset(0);
    setApplied(draft);
  }

  function clearFilters() {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setFilterError(null);
    setOffset(0);
  }

  const setField = <K extends keyof InboxFilters>(key: K, value: InboxFilters[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const statusOptions: RequestStatus[] = listTab === "pending" ? PENDING_STATUSES : HISTORY_STATUSES;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  function onCreated(created: BillingRequestDetail) {
    setCreating(false);
    setPrefill(undefined);
    setNotice(created.status === "aprobada" ? "Solicitud creada y autoaprobada. Ya puede aplicarse." : "Solicitud creada y pendiente de aprobación.");
    // Pendientes: reinicia pestaña, filtro de estado y página; el efecto carga la lista UNA vez (reloadKey cubre el caso
    // en que nada cambia). Desde «Renovaciones» se permanece ahí (la tarea pasa a «Ver solicitud») y solo se limpia el filtro.
    if (tab === "renewals") {
      setOffset(0);
      setDraft((d) => ({ ...d, status: "" }));
      setApplied((a) => ({ ...a, status: "" }));
    } else {
      changeTab("pending", true);
    }
    setSelectedId(created.id);
    setReloadKey((k) => k + 1);
    setRenewalKey((k) => k + 1);
  }

  function onTabKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const keys = Object.keys(TAB_LABELS) as View[];
    const at = keys.indexOf(tab);
    let next: View | null = null;
    if (event.key === "ArrowRight") next = keys[(at + 1) % keys.length];
    else if (event.key === "ArrowLeft") next = keys[(at - 1 + keys.length) % keys.length];
    else if (event.key === "Home") next = keys[0];
    else if (event.key === "End") next = keys[keys.length - 1];
    if (!next) return;
    event.preventDefault();
    changeTab(next);
    tabRefs.current[next]?.focus();
  }

  function requestRenewal(task: RenewalTask) {
    setNotice(null);
    setPrefill({ platform: task.platform, subscription: task.subscription_external_id, scheduledAmount: task.scheduled_amount });
    setCreating(true);
  }
  function closeDialog() {
    setCreating(false);
    setPrefill(undefined);
  }

  return (
    <main className="app-shell bx-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">General</p>
          <h1>Cambios de cobro</h1>
        </div>
        {can(PERM_REQUEST) ? <button className="bx-btn bx-btn-primary" onClick={() => { setNotice(null); setPrefill(undefined); setCreating(true); }}>Nueva solicitud</button> : null}
      </div>

      <div className="bx-tabs" role="tablist" aria-label="Vistas de solicitudes" onKeyDown={onTabKeyDown}>
        {(Object.keys(TAB_LABELS) as View[]).map((key) => (
          <button
            key={key} role="tab" id={`bx-tab-${key}`} aria-selected={tab === key} aria-controls="bx-tabpanel" tabIndex={tab === key ? 0 : -1}
            ref={(el) => { tabRefs.current[key] = el; }} onClick={() => changeTab(key)}
          >
            {TAB_LABELS[key]}
            {key === "renewals" && alertCount > 0 ? (
              <>
                <span className="bx-count mono" aria-hidden="true">{alertCount}</span>
                <span className="bx-sr"> ({alertCount} de prioridad alta o vencidas)</span>
              </>
            ) : null}
          </button>
        ))}
      </div>

      <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
      <div role="tabpanel" id="bx-tabpanel" aria-labelledby={`bx-tab-${tab}`}>
      {tab === "renewals" ? (
        <RenewalTasksView can={can} refreshKey={renewalKey} onViewRequest={setSelectedId} onRequestRenewal={requestRenewal} />
      ) : (
        <>
      <form className="bx-filters" onSubmit={applyFilters} aria-label="Filtros de solicitudes">
        <label>Estado
          <select value={draft.status} onChange={(e) => setField("status", e.target.value as RequestStatus | "")}>
            <option value="">Todos</option>
            {statusOptions.filter((s) => ALL_STATUSES.includes(s)).map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </select>
        </label>
        <label>Tipo
          <select value={draft.requestType} onChange={(e) => setField("requestType", e.target.value as RequestType | "")}>
            <option value="">Todos</option>
            {REQUEST_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
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
        <label>Solicitante
          <select value={draft.requestedBy} disabled={requestersState === "loading"} onChange={(e) => setField("requestedBy", e.target.value)}>
            <option value="">{requestersState === "loading" ? "Cargando…" : "Todos"}</option>
            {requesters.map((r) => <option key={r.id} value={r.id}>{r.username}</option>)}
            {draft.requestedBy && !requesters.some((r) => r.id === draft.requestedBy)
              ? <option value={draft.requestedBy}>{draft.requestedBy === currentUserId ? "Mis solicitudes" : "Usuario seleccionado"}</option> : null}
          </select>
        </label>
        {currentUserId ? <button type="button" className="bx-btn bx-btn-ghost" onClick={() => setField("requestedBy", currentUserId)}>Mis solicitudes</button> : null}
        <label>Desde
          <input className="mono" type="date" value={draft.dateFrom} aria-describedby="bx-date-hint" onChange={(e) => setField("dateFrom", e.target.value)} />
        </label>
        <label>Hasta
          <input className="mono" type="date" value={draft.dateTo} aria-describedby="bx-date-hint" onChange={(e) => setField("dateTo", e.target.value)} />
        </label>
        <span id="bx-date-hint" className="bx-hint">Fechas en UTC</span>
        <button type="submit" className="bx-btn bx-btn-primary" disabled={loading}>Buscar</button>
        <button type="button" className="bx-btn bx-btn-ghost" onClick={clearFilters} disabled={loading}>Limpiar</button>
      </form>
      {filterError ? <Notice tone="error">{filterError}</Notice> : null}
      {requestersState === "error" ? (
        <Notice tone="warning" live>
          No se pudo cargar la lista de solicitantes; puede seguir usando la bandeja sin ese filtro.{" "}
          <button type="button" className="bx-btn bx-btn-ghost" onClick={() => void loadRequesters()}>Reintentar</button>
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="error">
          {error}{" "}
          <button className="bx-btn bx-btn-ghost" onClick={() => void load(listTab, applied, offset)}>Reintentar</button>
        </Notice>
      ) : null}

      <p className="bx-sr" role="status" aria-live="polite">
        {loading ? "Cargando solicitudes…" : data ? `${total} solicitudes en ${TAB_LABELS[listTab].toLowerCase()}.` : ""}
      </p>

      {loading && !data ? <p className="muted-copy">Cargando solicitudes…</p> : null}
      {data && items.length === 0 && total === 0 && !error ? (
        <div className="bx-notice">
          <p style={{ margin: "0 0 8px" }}>{listTab === "pending" ? "No hay solicitudes pendientes con estos filtros." : "No hay solicitudes en el historial con estos filtros."}</p>
          {can(PERM_REQUEST) && listTab === "pending" ? <button className="bx-btn bx-btn-ghost" onClick={() => setCreating(true)}>Crear una solicitud</button> : <button className="bx-btn bx-btn-ghost" onClick={clearFilters}>Limpiar filtros</button>}
        </div>
      ) : null}
      {items.length > 0 ? (
        <div className="table-wrap" aria-busy={loading}>
          <table className="bx-table">
            <caption className="bx-sr">Solicitudes de cambio de cobro</caption>
            <thead>
              <tr>
                <th scope="col">Suscripción</th><th scope="col">Tipo</th><th scope="col" className="num">Cambio</th><th scope="col">Estado</th>
                <th scope="col">Solicitante</th><th scope="col">Creada</th><th scope="col">Vencimiento</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const expiry = expiryText(r);
                return (
                  <tr key={r.id} data-selected={selectedId === r.id}>
                    <td>
                      <button className="bx-row-btn mono" aria-current={selectedId === r.id ? "true" : undefined} onClick={() => setSelectedId(r.id)}
                        aria-label={`Ver solicitud de la suscripción ${r.subscription_external_id}`}>
                        {r.subscription_external_id}
                      </button>
                      <div className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{PLATFORM_LABELS[r.platform] ?? r.platform}</div>
                    </td>
                    <td>{TYPE_LABELS[r.request_type] ?? r.request_type}</td>
                    <td className="mono num">{requestSummary(r)}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td>{r.requested_by ?? "—"}</td>
                    <td className="mono">{formatDateTime(r.created_at)}</td>
                    <td className="mono">{expiry ?? "—"}</td>
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
      {items.length > 0 ? <p className="bx-hint">{CHILE_TZ_NOTE}</p> : null}

        </>
      )}
      </div>

      {selectedId ? <RequestDetail key={selectedId} id={selectedId} can={can} currentUserId={currentUserId} isAdmin={isAdmin} onChanged={() => { void load(listTab, applied, offset); setRenewalKey((k) => k + 1); }} /> : null}
      {creating ? <CreateRequestDialog prefill={prefill} onClose={closeDialog} onCreated={onCreated} /> : null}
    </main>
  );
}
