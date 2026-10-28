import type { ChangeEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getJson, postJson, postForm, friendlyError } from "../../api";
import { invalidateCache } from "../../apiCache";
import { CHANNEL_UNAVAILABLE_TITLE, useEnabledChannels } from "../shared/environment";
import type { EtlRun, SchedulerJob, SseEvent } from "../shared/types";

const _PHASE_LABELS: Record<string, string> = {
  sync_virtualpos1: "VirtualPOS VP1",
  sync_virtualpos2: "VirtualPOS VP2",
  sync_toku: "Toku",
  sync_payku: "Payku",
  consolidating: "Consolidación centralizada",
};

type ChannelKey = "all" | "virtualpos" | "toku" | "payku" | "tch";
type VpSubKey = "both" | "vp1" | "vp2";
const CHANNEL_OPTS: Array<{ key: ChannelKey; label: string; channels: string[] | null }> = [
  { key: "all",        label: "Todos",      channels: null },
  { key: "virtualpos", label: "VirtualPOS", channels: ["virtualpos1", "virtualpos2"] },
  { key: "toku",       label: "Toku",       channels: ["toku"] },
  { key: "payku",      label: "Payku",      channels: ["payku"] },
  { key: "tch",        label: "TCH",        channels: ["tch"] },
];
const VP_SUB_OPTS: Array<{ key: VpSubKey; label: string; channels: string[] }> = [
  { key: "both", label: "VP1 + VP2", channels: ["virtualpos1", "virtualpos2"] },
  { key: "vp1",  label: "Solo VP1",  channels: ["virtualpos1"] },
  { key: "vp2",  label: "Solo VP2",  channels: ["virtualpos2"] },
];
const _API_CHANNELS = ["virtualpos1", "virtualpos2", "toku", "payku"];

/** Presets de cuentas VirtualPOS; con una sola cuenta habilitada, "VP1 + VP2" se sustituye por "VP1"/"VP2". */
export function vpSubOptions(enabled: string[]): Array<{ key: VpSubKey; label: string; channels: string[] }> {
  const vp1 = enabled.includes("virtualpos1");
  const vp2 = enabled.includes("virtualpos2");
  if (vp1 && vp2) return VP_SUB_OPTS;
  if (vp1) return [{ key: "vp1", label: "VP1", channels: ["virtualpos1"] }];
  if (vp2) return [{ key: "vp2", label: "VP2", channels: ["virtualpos2"] }];
  return [];
}

/** Payload de sync: null (todos) si todo esta habilitado; si no, solo canales habilitados. */
export function syncPayloadChannels(selected: string[] | null, enabled: string[]): string[] | null {
  if (selected === null) {
    return _API_CHANNELS.every((c) => enabled.includes(c)) ? null : _API_CHANNELS.filter((c) => enabled.includes(c));
  }
  return selected.filter((c) => enabled.includes(c));
}

export function getPhasesForChannels(channels: string[] | null | undefined, enabled: string[] = [..._API_CHANNELS, "tch"]): string[] {
  const phases: string[] = [];
  const wanted = (c: string) => enabled.includes(c) && (!channels || channels.includes(c));
  if (wanted("virtualpos1")) phases.push("sync_virtualpos1");
  if (wanted("virtualpos2")) phases.push("sync_virtualpos2");
  if (wanted("toku")) phases.push("sync_toku");
  if (wanted("payku")) phases.push("sync_payku");
  phases.push("consolidating");
  return phases;
}

const _RUNS_PAGE = 10;

function cronLabel(cron: string): string {
  const map: Record<string, string> = {
    "0 2 * * *": "Diario a las 02:00 (Santiago)",
    "0 * * * *": "Cada hora",
    "*/30 * * * *": "Cada 30 min",
    "0 3 * * *": "Diario a las 03:00 (Santiago)",
    "10 * * * *": "Cada hora (minuto 10)",
    "5,20,35,50 * * * *": "Cada 15 min (minutos 5, 20, 35 y 50)",
  };
  return map[cron] ?? cron;
}

function runTypeLabel(channels: string[] | null, enabled: string[]): string {
  if (!channels || channels.length === 0) return "—";
  const map: Record<string, string> = { virtualpos1: "VP1", virtualpos2: "VP2", toku: "Toku", payku: "Payku", tch: "TCH" };
  const apiChannels = _API_CHANNELS.filter((c) => enabled.includes(c));
  const hasAllApi = apiChannels.length > 0 && apiChannels.every((c) => channels.includes(c));
  if (hasAllApi && channels.includes("tch")) return "Sync completa";
  if (hasAllApi) return "Sync completa";
  if (channels.length === 1 && channels[0] === "tch") return "TCH (importación)";
  return channels.map((c) => map[c] ?? c).join(" + ");
}

export function SchedulerPanel({ canSync, canViewRuns, canImportTch }: { canSync: boolean; canViewRuns: boolean; canImportTch: boolean }) {
  const { enabled } = useEnabledChannels();
  const [jobs, setJobs] = useState<SchedulerJob[]>([]);
  const [runs, setRuns] = useState<{ total: number; items: EtlRun[] }>({ total: 0, items: [] });
  const [runsOffset, setRunsOffset] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [sseEvents, setSseEvents] = useState<SseEvent[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [selectedChannelKey, setSelectedChannelKey] = useState<ChannelKey>("all");
  const [vpSubKey, setVpSubKey] = useState<VpSubKey>("both");
  const [polledPhase, setPolledPhase] = useState<string | null>(null);
  const [triggeredChannels, setTriggeredChannels] = useState<string[] | null | undefined>(undefined);

  const activeRunIdRef = useRef<string | null>(null);
  const reportInputRef = useRef<HTMLInputElement>(null);
  activeRunIdRef.current = activeRunId;

  function refreshData() {
    if (!canViewRuns) return;
    getJson<SchedulerJob[]>("/api/v1/scheduler/jobs").then((data) => {
      setJobs(data);
      const running = data.find((j) => j.active_run_id);
      if (running?.active_run_id && !activeRunIdRef.current) {
        setActiveRunId(running.active_run_id);
        setTriggeredChannels(undefined);
      }
    }).catch(() => {});
    getJson<{ total: number; items: EtlRun[] }>(`/api/v1/scheduler/runs?limit=${_RUNS_PAGE}&offset=0`)
      .then((data) => { setRuns(data); setRunsOffset(0); })
      .catch(() => {});
  }

  useEffect(() => { refreshData(); }, [canViewRuns]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!activeRunId) return;
    setSseEvents([]);
    setPolledPhase(null);
    let sseReceived = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    function startPolling() {
      if (pollTimer) return;
      pollTimer = setInterval(() => {
        getJson<{ items: EtlRun[] }>(`/api/v1/scheduler/runs?limit=5&offset=0`)
          .then((data) => {
            const run = data.items.find((r) => r.id === activeRunId);
            if (!run) return;
            setPolledPhase(run.phase ?? run.status);
            if (run.status !== "running") {
              if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
              if (run.status === "completed") invalidateCache();
              setTimeout(refreshData, 800);
            }
          }).catch(() => {});
      }, 4000);
    }
    const fallbackTimeout = setTimeout(() => { if (!sseReceived) startPolling(); }, 6000);
    const es = new EventSource(`/api/v1/scheduler/runs/${activeRunId}/stream`);
    es.onmessage = (e) => {
      if (!sseReceived) {
        sseReceived = true;
        clearTimeout(fallbackTimeout);
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        setPolledPhase(null);
      }
      const ev: SseEvent = JSON.parse(e.data as string);
      setSseEvents((prev) => [...prev, ev]);
      if (ev.type === "not_found") { es.close(); startPolling(); return; }
      if (ev.type === "completed" || ev.type === "error") {
        es.close();
        if (ev.type === "completed") invalidateCache();
        setTimeout(refreshData, 800);
      }
    };
    es.onerror = () => {};
    return () => {
      es.close();
      clearTimeout(fallbackTimeout);
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [activeRunId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function triggerSync() {
    const opt = CHANNEL_OPTS.find((o) => o.key === selectedChannelKey)!;
    const vpOpts = vpSubOptions(enabled);
    const vpChosen = vpOpts.find((o) => o.key === vpSubKey) ?? vpOpts[0];
    const selected = selectedChannelKey === "virtualpos" ? (vpChosen?.channels ?? []) : opt.channels;
    const channels = syncPayloadChannels(selected, enabled);
    if (channels !== null && channels.length === 0) {
      setTriggerError("No hay canales habilitados para sincronizar en este ambiente.");
      return;
    }
    setTriggeredChannels(channels);
    setTriggering(true);
    setTriggerError(null);
    try {
      const r = await postJson<{ run_id: string }>("/api/v1/scheduler/jobs/sync_all_channels/run", { channels });
      setActiveRunId(r.run_id);
      setTimeout(refreshData, 600);
    } catch (err) {
      setTriggerError(friendlyError(err, "No se pudo iniciar la sincronización."));
    } finally { setTriggering(false); }
  }

  async function importTchReport(event: ChangeEvent<HTMLInputElement>) {
    const report = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!report || triggering) return;
    setTriggeredChannels(["tch"]);
    setTriggering(true);
    setTriggerError(null);
    try {
      const form = new FormData();
      form.append("report", report);
      const response = await postForm<{ run_id: string }>("/api/v1/tch/import-report", form);
      setActiveRunId(response.run_id);
      setTimeout(refreshData, 600);
    } catch (err) {
      setTriggerError(friendlyError(err, "No se pudo importar el reporte TCH."));
    } finally { setTriggering(false); }
  }

  async function loadMore() {
    setLoadingMore(true);
    const nextOffset = runsOffset + _RUNS_PAGE;
    try {
      const data = await getJson<{ total: number; items: EtlRun[] }>(`/api/v1/scheduler/runs?limit=${_RUNS_PAGE}&offset=${nextOffset}`);
      setRuns((prev) => ({ total: data.total, items: [...prev.items, ...data.items] }));
      setRunsOffset(nextOffset);
    } finally { setLoadingMore(false); }
  }

  function phaseStatus(phase: string): "pending" | "running" | "done" | "error" {
    if (sseEvents.some((e) => e.type === "error" && e.phase === phase)) return "error";
    if (sseEvents.some((e) => e.type === "phase_done" && e.phase === phase)) return "done";
    if (sseEvents.some((e) => e.type === "phase_start" && e.phase === phase)) return "running";
    return "pending";
  }
  function phaseProgress(phase: string): number | null {
    const evts = sseEvents.filter((e) => e.type === "progress" && e.phase === phase);
    return evts.length ? (evts[evts.length - 1].pct ?? null) : null;
  }

  const allPhases = useMemo(() => getPhasesForChannels(null, enabled), [enabled]);
  const activePhases = useMemo(() => {
    if (triggeredChannels !== undefined) return getPhasesForChannels(triggeredChannels, enabled);
    const seen = new Set(sseEvents.filter((e) => e.phase && e.type !== "error").map((e) => e.phase!));
    const inferred = allPhases.filter((p) => seen.has(p));
    return inferred.length > 0 ? inferred : allPhases;
  }, [triggeredChannels, sseEvents, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const globalPct = useMemo(() => {
    if (!activeRunId || activePhases.length === 0) return null;
    let total = 0; let started = 0;
    for (const phase of activePhases) {
      const st = phaseStatus(phase);
      if (st === "done") { total += 100; started++; }
      else if (st === "running") { total += phaseProgress(phase) ?? 0; started++; }
    }
    if (started === 0) return null;
    return Math.round(total / activePhases.length);
  }, [sseEvents, activePhases]); // eslint-disable-line react-hooks/exhaustive-deps

  const isCompleted = sseEvents.some((e) => e.type === "completed");
  const completedEv = sseEvents.find((e) => e.type === "completed");

  function fmtDate(iso: string | null | undefined): string {
    if (!iso) return "—";
    const d = new Date(iso);
    const dd = d.getDate().toString().padStart(2, "0");
    const mm = (d.getMonth() + 1).toString().padStart(2, "0");
    const hh = d.getHours().toString().padStart(2, "0");
    const min = d.getMinutes().toString().padStart(2, "0");
    return `${dd}/${mm} ${hh}:${min}`;
  }
  function fmtDuration(start: string | null, end: string | null): string {
    if (!start || !end) return "—";
    const s = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
  function statusBadge(st: string) {
    // `partial`: corrida con errores parciales (p. ej. billing_renewal_check). Advertencia, no error ni éxito.
    const cls = st === "completed" ? "badge-green" : st === "failed" ? "badge-red" : st === "running" ? "badge-blue" : st === "partial" ? "badge-orange" : "badge-gray";
    const label = st === "completed" ? "OK" : st === "failed" ? "Error" : st === "running" ? "En curso" : st === "partial" ? "Parcial" : st;
    return <span className={`badge ${cls}`}>{label}</span>;
  }

  const channelAvailable = (key: ChannelKey): boolean => {
    if (key === "all") return true;
    if (key === "virtualpos") return enabled.includes("virtualpos1") || enabled.includes("virtualpos2");
    return enabled.includes(key);
  };
  const vpOptions = vpSubOptions(enabled);
  const effectiveVpSubKey = vpOptions.some((o) => o.key === vpSubKey) ? vpSubKey : vpOptions[0]?.key;
  useEffect(() => {
    if (!channelAvailable(selectedChannelKey)) setSelectedChannelKey("all");
  }, [enabled, selectedChannelKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const isRunning = jobs.some((j) => j.status === "running");
  const hasMore = runs.items.length < runs.total;

  return (
    <section className="panel scheduler-panel">
      <p className="eyebrow">ADMINISTRACIÓN / SINCRONIZACIÓN</p>
      <h1>Orquestador</h1>
      {canSync ? (
        <div className="channel-selector-wrap">
          <span className="channel-selector-label">Canal:</span>
          <div className="channel-selector">
            {CHANNEL_OPTS.filter((opt) => opt.key !== "tch" || canImportTch).map((opt) => (
              <button key={opt.key} className={`channel-btn${selectedChannelKey === opt.key ? " active" : ""}`} disabled={isRunning || triggering || !channelAvailable(opt.key)} title={channelAvailable(opt.key) ? undefined : CHANNEL_UNAVAILABLE_TITLE} onClick={() => setSelectedChannelKey(opt.key)}>{opt.label}</button>
            ))}
          </div>
          {selectedChannelKey === "virtualpos" && (
            <div className="channel-selector vp-sub-selector">
              {vpOptions.map((sub) => (
                <button key={sub.key} className={`channel-btn channel-btn-sm${effectiveVpSubKey === sub.key ? " active" : ""}`} disabled={isRunning || triggering} onClick={() => setVpSubKey(sub.key)}>{sub.label}</button>
              ))}
            </div>
          )}
        </div>
      ) : null}
      <h3 className="scheduler-section-title">Jobs programados</h3>
      {triggerError ? <p className="scheduler-error">{triggerError}</p> : null}
      {jobs.length === 0 ? (
        <p className="muted-copy">Sin jobs registrados.</p>
      ) : jobs.map((job) => (
        <div key={job.id} className="scheduler-job-card">
          <div className="sjc-top">
            <span className="sjc-name">{job.name}</span>
            <div className="sjc-top-right">
              {statusBadge(job.status)}
              {job.status === "running" && globalPct !== null ? <span className="sjc-live-pct">{globalPct}%</span> : null}
            </div>
          </div>
          <div className="sjc-meta">
            <span className="sjc-schedule">{cronLabel(job.cron)}</span>
            <span className="sjc-next">Próx: {fmtDate(job.next_run)}</span>
            {job.last_run ? <span className="sjc-last">Último: {fmtDate(job.last_run.started_at)}</span> : null}
          </div>
          {job.status === "running" && globalPct !== null ? (
            <div className="sjc-progress-wrap"><div className="sjc-progress-fill" style={{ width: `${globalPct}%` }} /></div>
          ) : null}
          <div className="sjc-actions">
            {selectedChannelKey === "tch" && canImportTch && !isRunning ? (
              <>
                <input ref={reportInputRef} type="file" accept=".xlsx" hidden onChange={importTchReport} />
                <button className="save-button sjc-btn" disabled={triggering} onClick={() => reportInputRef.current?.click()}>{triggering ? "Importando…" : "Importar reporte"}</button>
              </>
            ) : canSync && !isRunning ? (
              <button className="save-button sjc-btn" disabled={triggering} onClick={triggerSync}>
                {triggering ? "Iniciando…" : selectedChannelKey === "all" ? "Sincronizar todos" : `Sincronizar ${CHANNEL_OPTS.find((o) => o.key === selectedChannelKey)?.label}`}
              </button>
            ) : null}
            {job.status === "running" && job.active_run_id ? (
              <button className="save-button sjc-btn sjc-btn-live" onClick={() => { setActiveRunId(job.active_run_id!); setTriggeredChannels(undefined); }}>Ver progreso en vivo</button>
            ) : null}
          </div>
        </div>
      ))}
      {activeRunId ? (
        <div className="sse-panel">
          <div className="sse-header">
            <div className="sse-header-left">
              <h3 className="sse-title">
                {isCompleted ? `✓ Completado — ${(completedEv?.total_records ?? 0).toLocaleString()} registros en ${Math.floor((completedEv?.duration_s ?? 0) / 60)}m ${(completedEv?.duration_s ?? 0) % 60}s` : sseEvents.length === 0 ? "Conectando al stream…" : `Sincronizando… ${globalPct !== null ? `${globalPct}%` : ""}`}
              </h3>
              {sseEvents.length === 0 && polledPhase && <p className="sse-polled-phase">{_PHASE_LABELS[polledPhase] ?? polledPhase} — actualizando cada 4s</p>}
              {!isCompleted && globalPct !== null ? <div className="sse-global-bar-wrap"><div className="sse-global-bar-fill" style={{ width: `${globalPct}%` }} /></div> : null}
              {!isCompleted && sseEvents.length > 0 && globalPct === null ? <div className="sse-indeterminate-wrap"><div className="sse-indeterminate-fill" /></div> : null}
              {sseEvents.length === 0 ? <div className="sse-indeterminate-wrap"><div className="sse-indeterminate-fill" /></div> : null}
            </div>
            <button className="sse-close-btn" onClick={() => setActiveRunId(null)}>✕</button>
          </div>
          {sseEvents.length === 0 ? (
            <p className="sse-connecting-hint">{polledPhase ? "Stream no disponible vía tunnel — usando polling" : "Esperando eventos del servidor…"}</p>
          ) : (
            <ul className="phase-list">
              {activePhases.map((phase) => {
                const st = phaseStatus(phase);
                const pct = phaseProgress(phase);
                const icon = st === "done" ? "✓" : st === "error" ? "✗" : st === "running" ? "⟳" : "○";
                const color = st === "done" ? "#16A34A" : st === "error" ? "#DC2626" : st === "running" ? "#2563EB" : "#94A3B8";
                return (
                  <li key={phase} className="phase-item">
                    <span className="phase-icon" style={{ color }}>{icon}</span>
                    <span className="phase-label">{_PHASE_LABELS[phase]}</span>
                    {st === "running" && pct === null ? <div className="progress-bar-wrap"><div className="progress-bar-indeterminate" /></div> : pct !== null ? <div className="progress-bar-wrap"><div className="progress-bar-fill" style={{ width: `${pct}%` }} /></div> : null}
                    {pct !== null ? <span className="phase-pct">{pct}%</span> : null}
                  </li>
                );
              })}
            </ul>
          )}
          {sseEvents.filter((e) => e.type === "progress" || e.type === "error").length > 0 ? (
            <div className="sse-log">
              {sseEvents.filter((e) => e.type === "progress" || e.type === "error").slice(-80).map((e, i) => (
                <div key={i} style={{ color: e.type === "error" ? "#DC2626" : undefined }}>
                  [{e.phase}]{e.resource ? ` ${e.resource}` : ""}{e.pct != null ? ` ${e.pct}%` : ""}{e.records != null ? ` (${e.records.toLocaleString()})` : ""}{e.msg ? ` — ${e.msg}` : ""}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="scheduler-section-header">
        <h3 className="scheduler-section-title" style={{ margin: 0 }}>Historial</h3>
        <span className="scheduler-total-count">{runs.total} ejecuciones</span>
      </div>
      <div className="table-scroll">
        <table className="scheduler-jobs-table runs-table">
          <thead><tr><th>Inicio</th><th className="hide-mobile">Fin</th><th>Duración</th><th>Estado</th><th>Tipo</th><th>Registros</th><th></th></tr></thead>
          <tbody>
            {runs.items.length === 0 ? (
              <tr><td colSpan={7} className="muted-copy" style={{ textAlign: "center", padding: "1rem" }}>Sin ejecuciones registradas.</td></tr>
            ) : runs.items.map((run) => {
              const isThisRunActive = run.status === "running" && activeRunId === run.id;
              return (
                <tr key={run.id}>
                  <td className="runs-date">{fmtDate(run.started_at)}</td>
                  <td className="runs-date hide-mobile">{fmtDate(run.finished_at)}</td>
                  <td className="runs-dur">{isThisRunActive && globalPct !== null ? <span className="runs-live-dur">⟳ {globalPct}%</span> : fmtDuration(run.started_at, run.finished_at)}</td>
                  <td>{statusBadge(run.status)}</td>
                  <td className="runs-type">{runTypeLabel(run.channels_processed, enabled)}</td>
                  <td className="runs-rec">{run.records_upserted != null ? <span className="runs-rec-val">{run.records_upserted.toLocaleString()}</span> : <span className="muted-copy">—</span>}</td>
                  <td>{run.status === "running" ? (isThisRunActive ? <span className="runs-watching-dot" title="Viendo en vivo">●</span> : <button className="runs-ver-btn" onClick={() => { setActiveRunId(run.id); setTriggeredChannels(undefined); }}>Ver en vivo</button>) : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {runs.items.some((r) => r.status === "running" && r.id === activeRunId) && globalPct !== null ? (
        <div className="runs-active-bar-wrap"><div className="runs-active-bar-fill" style={{ width: `${globalPct}%` }} /></div>
      ) : null}
      {hasMore ? (
        <div className="runs-load-more">
          <button className="runs-load-more-btn" disabled={loadingMore} onClick={loadMore}>
            {loadingMore ? "Cargando…" : `Ver más (${runs.total - runs.items.length} restantes)`}
          </button>
        </div>
      ) : null}
    </section>
  );
}
