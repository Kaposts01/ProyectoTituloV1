import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./billingApi";
import { describeBillingError } from "./billingErrors";
import {
  ALL_STATUSES, expiryText, formatDateTime, PLATFORM_LABELS, REQUEST_TYPES, requestSummary, statusLabel, TYPE_LABELS,
  HISTORY_STATUSES, PENDING_STATUSES,
} from "./billingLabels";
import { EMPTY_FILTERS, validateFilters, type InboxFilters, type InboxTab } from "./billingQuery";
import { CreateRequestDialog } from "./CreateRequestDialog";
import { RequestDetail } from "./RequestDetail";
import { PERM_REQUEST, type BillingList, type BillingRequestDetail, type Platform, type Requester, type RequestStatus, type RequestType } from "./types";
import { Notice, StatusBadge } from "./ui";
import "./billing.css";

const PAGE_SIZE = 25;
const TAB_LABELS: Record<InboxTab, string> = { pending: "Pendientes", history: "Historial" };

type Props = {
  can: (permission: string) => boolean;
  /** Id del usuario actual, solo para el atajo «Mis solicitudes». */
  currentUserId?: string;
};

export function BillingInbox({ can, currentUserId }: Props) {
  const [tab, setTab] = useState<InboxTab>("pending");
  const [draft, setDraft] = useState<InboxFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<InboxFilters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<BillingList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const seq = useRef(0);
  const [requesters, setRequesters] = useState<Requester[]>([]);
  const [requestersState, setRequestersState] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(async (nextTab: InboxTab, filters: InboxFilters, nextOffset: number) => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.fetchRequests(nextTab, filters, nextOffset, PAGE_SIZE);
      if (mine !== seq.current) return;
      setData(result);
    } catch (err) {
      if (mine !== seq.current) return;
      setError(describeBillingError(err, "No se pudo cargar la bandeja de solicitudes.").message);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(tab, applied, offset); }, [load, tab, applied, offset]);

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

  function changeTab(next: InboxTab) {
    if (next === tab) return;
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
  const statusOptions: RequestStatus[] = tab === "pending" ? PENDING_STATUSES : HISTORY_STATUSES;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  function onCreated(created: BillingRequestDetail) {
    setCreating(false);
    setNotice(created.status === "aprobada" ? "Solicitud creada y autoaprobada. Ya puede aplicarse." : "Solicitud creada y pendiente de aprobación.");
    setTab("pending");
    setOffset(0);
    setSelectedId(created.id);
    void load("pending", applied, 0);
  }

  return (
    <main className="app-shell bx-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">General</p>
          <h1>Cambios de cobro</h1>
        </div>
        {can(PERM_REQUEST) ? <button className="bx-btn bx-btn-primary" onClick={() => { setNotice(null); setCreating(true); }}>Nueva solicitud</button> : null}
      </div>

      <div className="bx-tabs" role="tablist" aria-label="Vistas de solicitudes">
        {(Object.keys(TAB_LABELS) as InboxTab[]).map((key) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => changeTab(key)}>{TAB_LABELS[key]}</button>
        ))}
      </div>

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
          <input className="mono" type="date" value={draft.dateFrom} onChange={(e) => setField("dateFrom", e.target.value)} />
        </label>
        <label>Hasta
          <input className="mono" type="date" value={draft.dateTo} onChange={(e) => setField("dateTo", e.target.value)} />
        </label>
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
      <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
      {error ? (
        <Notice tone="error">
          {error}{" "}
          <button className="bx-btn bx-btn-ghost" onClick={() => void load(tab, applied, offset)}>Reintentar</button>
        </Notice>
      ) : null}

      <p className="bx-sr" role="status" aria-live="polite">
        {loading ? "Cargando solicitudes…" : data ? `${total} solicitudes en ${TAB_LABELS[tab].toLowerCase()}.` : ""}
      </p>

      {loading && !data ? <p className="muted-copy">Cargando solicitudes…</p> : null}
      {data && items.length === 0 && !error ? (
        <div className="bx-notice">
          <p style={{ margin: "0 0 8px" }}>{tab === "pending" ? "No hay solicitudes pendientes con estos filtros." : "No hay solicitudes en el historial con estos filtros."}</p>
          {can(PERM_REQUEST) && tab === "pending" ? <button className="bx-btn bx-btn-ghost" onClick={() => setCreating(true)}>Crear una solicitud</button> : <button className="bx-btn bx-btn-ghost" onClick={clearFilters}>Limpiar filtros</button>}
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

      {selectedId ? <RequestDetail key={selectedId} id={selectedId} can={can} onChanged={() => void load(tab, applied, offset)} /> : null}
      {creating ? <CreateRequestDialog onClose={() => setCreating(false)} onCreated={onCreated} /> : null}
    </main>
  );
}
