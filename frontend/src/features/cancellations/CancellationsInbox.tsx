import { useEffect, useRef, useState } from "react";
import { formatDateTime } from "../billing/billingLabels";
import { Cell, FiltersPanel, Notice } from "../billing/ui";
import { CancellationActions } from "./CancellationActions";
import { StatusBadge } from "./CancellationStatusBadge";
import { CancellationDetailView } from "./CancellationDetailView";
import * as api from "./cancellationsApi";
import { describeCancellationError } from "./cancellationErrors";
import { channelText, reasonText, statusText } from "./cancellationLabels";
import { CHANNELS, EMPTY_CANCELLATION_FILTERS, TAB_STATUSES, type CancellationFilters, type CancellationTab } from "./cancellationsQuery";
import { RequestCancellationDialog } from "./RequestCancellationDialog";
import { ChangeAmountDialog } from "./ChangeAmountDialog";
import { ManualTasksPanel } from "./ManualTasksPanel";
import { PERM_BILLING_REQUEST, PERM_MANUAL_TASKS_VIEW } from "./manualTasks";
import { PERM_CANCELLATION_REQUEST, type CancellationChannel, type CancellationDetail, type CancellationList, type CancellationStatus } from "./types";
import "../billing/billing.css";
import "./cancellations.css";

const PAGE_SIZE = 25;
/** Pestañas de la bandeja: las tres de solicitudes y, con su permiso, «Tareas manuales» (MGT-11/13/14). */
type InboxTab = CancellationTab | "tasks";
const TAB_LABELS: Record<InboxTab, string> = { pending: "Pendientes", running: "En ejecución", history: "Historial", tasks: "Tareas manuales" };
const REQUEST_TABS: CancellationTab[] = ["pending", "running", "history"];
const EMPTY_COPY: Record<CancellationTab, string> = {
  pending: "No hay solicitudes de baja pendientes con estos filtros.",
  running: "No hay bajas en ejecución ni en seguimiento con estos filtros.",
  history: "No hay solicitudes de baja en el historial con estos filtros.",
};

type Props = {
  can: (permission: string) => boolean;
  /** Id del usuario actual: «Retirar» solo para el solicitante. */
  currentUserId?: string;
  /** Rol admin: puede retirar solicitudes ajenas. */
  isAdmin?: boolean;
};

/** Último offset válido para `total` elementos (inicio de la última página). */
function lastPageOffset(total: number): number {
  return Math.max(0, Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
}

export function CancellationsInbox({ can, currentUserId, isAdmin = false }: Props) {
  const [tab, setTab] = useState<InboxTab>("pending");
  const TAB_KEYS: InboxTab[] = can(PERM_MANUAL_TASKS_VIEW) ? [...REQUEST_TABS, "tasks"] : REQUEST_TABS;
  const listTab: CancellationTab = tab === "tasks" ? "pending" : tab;
  const [changingAmount, setChangingAmount] = useState(false);
  const [draft, setDraft] = useState<CancellationFilters>(EMPTY_CANCELLATION_FILTERS);
  const [applied, setApplied] = useState<CancellationFilters>(EMPTY_CANCELLATION_FILTERS);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<{ key: string; data: CancellationList | null; error: string | null }>({ key: "", data: null, error: null });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const tabRefs = useRef<Partial<Record<InboxTab, HTMLButtonElement | null>>>({});

  // La carga se deriva de la clave de la consulta: mientras el resultado guardado no sea el de la consulta vigente, se está cargando.
  const requestKey = `${tab}|${applied.status}|${applied.channel}|${offset}|${reloadKey}`;
  useEffect(() => {
    if (tab === "tasks") return undefined; // la pestaña de tareas manuales carga su propia lista
    let alive = true;
    api.fetchCancellations(listTab, applied, offset, PAGE_SIZE).then((data) => {
      if (!alive) return;
      // Se actuó sobre el último ítem de la última página: la página pedida quedó vacía pero hay datos. Se reposiciona.
      const back = lastPageOffset(data.total);
      if (data.items.length === 0 && data.total > 0 && offset > 0 && back < offset) {
        setOffset(back);
        return;
      }
      setResult({ key: requestKey, data, error: null });
    }).catch((err: unknown) => {
      if (!alive) return;
      const message = describeCancellationError(err, "No se pudo cargar la bandeja de bajas.").message;
      setResult((prev) => ({ key: requestKey, data: prev.data, error: message }));
    });
    return () => { alive = false; };
  }, [tab, listTab, applied, offset, requestKey]);

  const loading = result.key !== requestKey;
  const data = result.data;
  const error = result.key === requestKey ? result.error : null;
  const reload = () => setReloadKey((k) => k + 1);

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
    setOffset(0);
    setApplied(draft);
  }

  function clearFilters() {
    setDraft(EMPTY_CANCELLATION_FILTERS);
    setApplied(EMPTY_CANCELLATION_FILTERS);
    setOffset(0);
  }

  function onTabKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const at = TAB_KEYS.indexOf(tab);
    let next: InboxTab | null = null;
    if (event.key === "ArrowRight") next = TAB_KEYS[(at + 1) % TAB_KEYS.length];
    else if (event.key === "ArrowLeft") next = TAB_KEYS[(at - 1 + TAB_KEYS.length) % TAB_KEYS.length];
    else if (event.key === "Home") next = TAB_KEYS[0];
    else if (event.key === "End") next = TAB_KEYS[TAB_KEYS.length - 1];
    if (!next) return;
    event.preventDefault();
    changeTab(next);
    tabRefs.current[next]?.focus();
  }

  function onCreated(created: CancellationDetail) {
    setCreating(false);
    setNotice(created.status === "approved" ? "Solicitud de baja creada y autoaprobada. Ya puede aplicarse." : "Solicitud de baja creada y pendiente de aprobación.");
    // Pendientes sin filtro de estado ni página; el efecto carga la lista una vez (reloadKey cubre el caso en que nada cambia).
    setTab("pending");
    setOffset(0);
    setDraft((d) => ({ ...d, status: "" }));
    setApplied((a) => ({ ...a, status: "" }));
    setSelectedId(created.id);
    setFocusToken((t) => t + 1);
    reload();
  }

  function openExisting(id: string) {
    setCreating(false);
    selectRequest(id);
  }

  function selectRequest(id: string) {
    setSelectedId(id);
    setFocusToken((t) => t + 1);
  }

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const activeFilterCount = Object.values(applied).filter((v) => v !== "").length;

  return (
    <main className="app-shell bx-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Operación</p>
          <h1>Bajas</h1>
        </div>
        <div className="cx-topbar-actions">
          {can(PERM_BILLING_REQUEST) ? <button className="bx-btn bx-btn-ghost" onClick={() => { setNotice(null); setChangingAmount(true); }}>Cambiar monto</button> : null}
          {can(PERM_CANCELLATION_REQUEST) ? <button className="bx-btn bx-btn-primary" onClick={() => { setNotice(null); setCreating(true); }}>Solicitar baja</button> : null}
        </div>
      </div>

      <div className="bx-tabs" role="tablist" aria-label="Vistas de bajas" onKeyDown={onTabKeyDown}>
        {TAB_KEYS.map((key) => (
          <button
            key={key} role="tab" id={`cx-tab-${key}`} aria-selected={tab === key} aria-controls="cx-tabpanel" tabIndex={tab === key ? 0 : -1}
            ref={(el) => { tabRefs.current[key] = el; }} onClick={() => changeTab(key)}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
      {tab === "tasks" ? (
        <div role="tabpanel" id="cx-tabpanel" aria-labelledby="cx-tab-tasks"><ManualTasksPanel can={can} /></div>
      ) : (
      <div role="tabpanel" id="cx-tabpanel" aria-labelledby={`cx-tab-${tab}`}>
        <form className="bx-filters" onSubmit={applyFilters} aria-label="Filtros de bajas">
          <FiltersPanel activeCount={activeFilterCount}>
            <label>Estado
              <select value={draft.status} onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value as CancellationStatus | "" }))}>
                <option value="">Todos</option>
                {TAB_STATUSES[listTab].map((s) => <option key={s} value={s}>{statusText(s)}</option>)}
              </select>
            </label>
            <label>Canal
              <select value={draft.channel} onChange={(e) => setDraft((d) => ({ ...d, channel: e.target.value as CancellationChannel | "" }))}>
                <option value="">Todos</option>
                {CHANNELS.map((c) => <option key={c} value={c}>{channelText(c)}</option>)}
              </select>
            </label>
            <button type="submit" className="bx-btn bx-btn-primary" disabled={loading}>Buscar</button>
            <button type="button" className="bx-btn bx-btn-ghost" onClick={clearFilters} disabled={loading}>Limpiar</button>
          </FiltersPanel>
        </form>

        {error ? (
          <Notice tone="error">
            {error}{" "}
            <button className="bx-btn bx-btn-ghost" onClick={reload}>Reintentar</button>
          </Notice>
        ) : null}

        <p className="bx-sr" role="status" aria-live="polite">
          {loading ? "Cargando solicitudes de baja…" : data ? `${total} solicitudes en ${TAB_LABELS[listTab].toLowerCase()}.` : ""}
        </p>

        {loading && !data ? <p className="muted-copy">Cargando solicitudes de baja…</p> : null}
        {data && items.length === 0 && total === 0 && !error ? (
          <div className="bx-notice">
            <p style={{ margin: "0 0 8px" }}>{EMPTY_COPY[listTab]}</p>
            {can(PERM_CANCELLATION_REQUEST) && tab === "pending"
              ? <button className="bx-btn bx-btn-ghost" onClick={() => { setNotice(null); setCreating(true); }}>Solicitar baja</button>
              : <button className="bx-btn bx-btn-ghost" onClick={clearFilters}>Limpiar filtros</button>}
          </div>
        ) : null}
        {items.length > 0 ? (
          <div className="table-wrap" aria-busy={loading}>
            <table className="bx-table bx-stack bx-stack-cancellations" role="table">
              <caption className="bx-sr">Solicitudes de baja de suscripción</caption>
              <thead role="rowgroup">
                <tr role="row">
                  <th role="columnheader" scope="col">Suscripción</th><th role="columnheader" scope="col">Canal</th><th role="columnheader" scope="col">Motivo</th>
                  <th role="columnheader" scope="col">Solicitante</th><th role="columnheader" scope="col">Estado</th><th role="columnheader" scope="col">Creada</th>
                </tr>
              </thead>
              <tbody role="rowgroup">
                {items.map((r) => (
                  <tr role="row" key={r.id} data-selected={selectedId === r.id}>
                    <Cell label="Suscripción" className="bx-c-sub">
                      <button className="bx-row-btn mono" aria-current={selectedId === r.id ? "true" : undefined} onClick={() => selectRequest(r.id)}
                        aria-label={`Ver solicitud de baja de la suscripción ${r.subscription_external_id}`}>
                        {r.subscription_external_id}
                      </button>
                      {selectedId === r.id ? <span className="bx-selected-mark">Detalle abajo</span> : null}
                    </Cell>
                    <Cell label="Canal" className="bx-c-channel bx-lbl">{channelText(r.channel)}</Cell>
                    <Cell label="Motivo" className="bx-c-reason bx-lbl">{reasonText(r.reason_code)}</Cell>
                    <Cell label="Solicitante" className="mono bx-c-who bx-lbl">{r.requested_by ?? "—"}</Cell>
                    <Cell label="Estado" className="bx-c-status"><StatusBadge status={r.status} /></Cell>
                    <Cell label="Creada" className="mono bx-c-created bx-lbl">{formatDateTime(r.created_at)}</Cell>
                  </tr>
                ))}
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
      </div>
      )}

      {selectedId && tab !== "tasks" ? (
        <CancellationDetailView
          key={selectedId} id={selectedId} focusToken={focusToken} reloadToken={reloadKey}
          renderActions={(detail, reloadDetail) => (
            <CancellationActions detail={detail} can={can} currentUserId={currentUserId} isAdmin={isAdmin} reload={reloadDetail} onChanged={reload} />
          )}
        />
      ) : null}
      {changingAmount ? <ChangeAmountDialog onClose={() => setChangingAmount(false)} onDone={(message) => { setChangingAmount(false); setNotice(message); }} /> : null}
      {creating ? <RequestCancellationDialog onClose={() => setCreating(false)} onCreated={onCreated} onOpenExisting={openExisting} /> : null}
    </main>
  );
}
