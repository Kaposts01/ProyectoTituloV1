import type { ChangeEvent } from "react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { getJson, postJson, postForm, friendlyError } from "../../api";
import { invalidateCache } from "../../apiCache";
import { CHANNEL_NAME, CHANNEL_ORDER, ageText, channelText, entryState } from "../../components/healthLabels";
import { useChannelHealth } from "../../hooks/useChannelHealth";
import { label } from "../../i18n/label";
import { CHANNEL_UNAVAILABLE_TITLE, useEnabledChannels } from "../shared/environment";
import type { EtlRun, SchedulerJob, SseEvent } from "../shared/types";
import { API_CHANNELS, phaseText, failedChannelsLabel, fmtDuration, jobBadge, runTypeLabel } from "./schedulerLabels";
import { RunResourceStats } from "./RunResourceStats";
import { SseLogEntry } from "./SseLogEntry";
import { BatchBusyError, SYNC_JOB_ID, batchJobs, isManualJob, isReadOnlyJob, manualJobsInOrder, runJobsSequentially, type BatchStep } from "./jobBatch";

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
const _API_CHANNELS = API_CHANNELS;

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

/**
 * REV-01 (origin/sprint-5/estabilizacion-dashboard 1005a26, adaptado): el backend emite `error` por cada fase que
 * falla y la corrida sigue (queda `partial`); el cierre es `completed` (con su `status`) o `error` de fase `fatal`.
 * Antes el stream se cerraba en el primer error de una fase y dejaba de seguir la corrida.
 */
export function isTerminalSseEvent(ev: { type: string; phase?: string | null }): boolean {
  return ev.type === "completed" || (ev.type === "error" && ev.phase === "fatal");
}

const STEP_BADGE: Record<BatchStep["state"], string> = {
  queued: "badge-gray", running: "badge-blue", completed: "badge-green", partial: "badge-orange", failed: "badge-red", skipped: "badge-gray",
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function SchedulerPanel({ canSync, canViewRuns, canImportTch, batchPollMs = 3000 }: { canSync: boolean; canViewRuns: boolean; canImportTch: boolean; batchPollMs?: number }) {
  const { enabled } = useEnabledChannels();
  const health = useChannelHealth(canViewRuns);
  const [batchSteps, setBatchSteps] = useState<BatchStep[] | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  // 13D: confirmación inline (mismo patrón que «Sync completo», QA-02): "all" = todos los procesos, o el id del job.
  const [confirming, setConfirming] = useState<string | null>(null);
  // «Ejecutar todos» deja fuera facturación y bajas salvo que se marque esta casilla en la confirmación.
  const [includeWrites, setIncludeWrites] = useState(false);
  const unmountedRef = useRef(false);
  // Reloj del panel para «hace X» y la duración en vivo de cada paso (cada 1 s mientras corre una ejecución).
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), batchRunning ? 1000 : 30000);
    return () => clearInterval(timer);
  }, [batchRunning]);
  useEffect(() => { unmountedRef.current = false; return () => { unmountedRef.current = true; }; }, []);
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
  const [jobsError, setJobsError] = useState(false);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);

  const activeRunIdRef = useRef<string | null>(null);
  const reportInputRef = useRef<HTMLInputElement>(null);
  activeRunIdRef.current = activeRunId;

  function refreshData() {
    if (!canViewRuns) return;
    getJson<SchedulerJob[]>("/api/v1/scheduler/jobs").then((data) => {
      setJobs(data);
      setJobsError(false);
      const running = data.find((j) => j.active_run_id);
      if (running?.active_run_id && !activeRunIdRef.current) {
        setActiveRunId(running.active_run_id);
        setTriggeredChannels(undefined);
      }
    }).catch(() => { setJobsError(true); });
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
              // REV-01 (1005a26): una corrida parcial o fallida tambien pudo escribir datos.
              invalidateCache();
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
      if (isTerminalSseEvent(ev)) {
        es.close();
        invalidateCache();
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

  /** Canales que pide la sincronización según el selector (null = todos los habilitados). */
  function selectedSyncChannels(): string[] | null {
    const opt = CHANNEL_OPTS.find((o) => o.key === selectedChannelKey)!;
    const vpOpts = vpSubOptions(enabled);
    const vpChosen = vpOpts.find((o) => o.key === vpSubKey) ?? vpOpts[0];
    const selected = selectedChannelKey === "virtualpos" ? (vpChosen?.channels ?? []) : opt.channels;
    return syncPayloadChannels(selected, enabled);
  }

  /** Lanza un job; la sincronización de canales además abre el progreso en vivo por fase. */
  async function triggerJob(job: SchedulerJob): Promise<string> {
    const isSync = job.id === SYNC_JOB_ID;
    const channels = isSync ? selectedSyncChannels() : undefined;
    if (isSync && channels && channels.length === 0) {
      throw new Error("No hay canales habilitados para sincronizar en este ambiente.");
    }
    try {
      const r = await postJson<{ run_id: string }>(`/api/v1/scheduler/jobs/${job.id}/run`, isSync ? { channels } : {});
      if (isSync) { setTriggeredChannels(channels); setActiveRunId(r.run_id); }
      return r.run_id;
    } catch (err) {
      if ((err as { status?: number } | null)?.status === 409) {
        // Ya hay una corrida activa: el paso queda «Omitida» y se muestra el texto del catálogo.
        setTriggerError(friendlyError(err, "Ya hay una sincronización en curso. Espera a que termine."));
        throw new BatchBusyError("busy");
      }
      throw new Error(friendlyError(err, "No se pudo iniciar el proceso."));
    }
  }

  /** Espera a que el job deje de estar en curso (lee /scheduler/jobs) y devuelve el estado de su última corrida. */
  async function waitJobDone(job: SchedulerJob, runId: string): Promise<string> {
    for (;;) {
      await sleep(batchPollMs);
      if (unmountedRef.current) return "failed";
      let data: SchedulerJob[];
      try { data = await getJson<SchedulerJob[]>("/api/v1/scheduler/jobs"); } catch { continue; }
      setJobs(data);
      const current = data.find((j) => j.id === job.id);
      if (!current) return "failed";
      if (current.status === "running" && (!current.active_run_id || current.active_run_id === runId)) continue;
      return current.last_run?.status ?? "completed";
    }
  }

  /** 13D: corre los procesos uno tras otro (respeta el lock: nunca dos a la vez) y muestra el avance de cada uno. */
  async function runBatch(list: SchedulerJob[]) {
    setConfirming(null);
    setTriggerError(null);
    setBatchRunning(true);
    try {
      await runJobsSequentially(list, {
        trigger: triggerJob,
        waitDone: waitJobDone,
        onUpdate: (steps) => { if (!unmountedRef.current) setBatchSteps(steps); },
        cancelled: () => unmountedRef.current,
      });
    } finally {
      if (!unmountedRef.current) {
        setBatchRunning(false);
        invalidateCache();
        refreshData();
      }
    }
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
  function statusBadge(st: string) {
    // `partial`: corrida con errores parciales (p. ej. billing_renewal_check). Advertencia, no error ni éxito.
    const cls = st === "completed" ? "badge-green" : st === "failed" ? "badge-red" : st === "running" ? "badge-blue" : st === "partial" ? "badge-orange" : "badge-gray";
    // Vocabulario compacto propio del panel para los cuatro estados habituales; el resto sale del catálogo.
    const text = st === "completed" ? "OK" : st === "failed" ? "Error" : st === "running" ? "En curso" : st === "partial" ? "Parcial" : label("runStatus", st);
    return <span className={`badge ${cls}`}>{text}</span>;
  }

  const channelAvailable = (key: ChannelKey): boolean => {
    if (key === "all") return true;
    if (key === "virtualpos") return enabled.includes("virtualpos1") || enabled.includes("virtualpos2");
    return enabled.includes(key);
  };
  const unavailableLabels = CHANNEL_OPTS
    .filter((opt) => opt.key !== "all" && (opt.key !== "tch" || canImportTch) && !channelAvailable(opt.key))
    .map((opt) => opt.label);
  const unavailableNote = unavailableLabels.length === 0 ? null
    : unavailableLabels.length === 1 ? `${unavailableLabels[0]} no está habilitado en este ambiente.`
    : `${unavailableLabels.slice(0, -1).join(", ")} y ${unavailableLabels[unavailableLabels.length - 1]} no están habilitados en este ambiente.`;
  const vpOptions = vpSubOptions(enabled);
  const effectiveVpSubKey = vpOptions.some((o) => o.key === vpSubKey) ? vpSubKey : vpOptions[0]?.key;
  useEffect(() => {
    if (!channelAvailable(selectedChannelKey)) setSelectedChannelKey("all");
  }, [enabled, selectedChannelKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const isRunning = jobs.some((j) => j.status === "running");
  const busy = isRunning || triggering || batchRunning;
  const hasMore = runs.items.length < runs.total;
  const manualJobs = manualJobsInOrder(jobs);
  const automaticCount = jobs.length - manualJobs.length;
  // Facturación y bajas: fuera de «Ejecutar todos» por defecto; solo entran con la casilla explícita.
  const writeJobs = manualJobs.filter((job) => !isReadOnlyJob(job));
  const readJobs = batchJobs(jobs, false);
  const runAllJobs = batchJobs(jobs, includeWrites);
  const channelLabel = selectedChannelKey === "all" ? "todos los canales habilitados" : CHANNEL_OPTS.find((o) => o.key === selectedChannelKey)?.label ?? "";
  const healthEntries = CHANNEL_ORDER.map((channel) => health[channel]).filter((entry) => entry !== undefined);

  function confirmBox(id: string, list: SchedulerJob[]) {
    if (confirming !== id || busy) return null;
    const includesSync = list.some((j) => j.id === SYNC_JOB_ID);
    return (
      <div role="alertdialog" aria-label={id === "all" ? "Confirmar ejecutar todos los procesos" : `Confirmar ${list[0]?.name ?? "proceso"}`} className="environment-confirm scheduler-confirm">
        <p>
          {id === "all" ? <>Se {list.length === 1 ? "va" : "van"} a ejecutar <strong className="mono">{list.length}</strong> {list.length === 1 ? "proceso" : "procesos, uno tras otro (nunca dos a la vez)"}:</> : <>Se va a ejecutar <strong>{list[0]?.name}</strong>.</>}
        </p>
        {id === "all" ? <ol className="scheduler-confirm-list">{list.map((j) => <li key={j.id}>{j.name}</li>)}</ol> : null}
        {includesSync ? <p>La sincronización lee las APIs de {channelLabel} y luego consolida la base unificada; puede tardar varios minutos. TCH no se lee: entra por su Excel.</p> : null}
        {id === "all" && automaticCount > 0 ? <p className="muted-copy">{automaticCount === 1 ? "1 proceso solo corre por calendario y no se incluye." : `${automaticCount} procesos solo corren por calendario y no se incluyen.`}</p> : null}
        {id === "all" && writeJobs.length > 0 ? (
          <label className="scheduler-confirm-writes">
            <input type="checkbox" checked={includeWrites} onChange={(e) => setIncludeWrites(e.target.checked)} />
            <span>
              Incluir también facturación y bajas ({writeJobs.length}): {writeJobs.map((j) => j.name).join(", ")}. No son
              de lectura: renuevan el calendario de facturación, vencen solicitudes de cambio y de baja, y barren las que
              quedaron «aplicando», así que escriben en la base.
            </span>
          </label>
        ) : null}
        <button type="button" className="primary-button" disabled={list.length === 0} onClick={() => void runBatch(list)}>{id === "all" ? `Sí, ejecutar ${list.length} ${list.length === 1 ? "proceso" : "procesos"}` : "Sí, ejecutar"}</button>
        <button type="button" className="secondary-button" onClick={() => setConfirming(null)}>Cancelar</button>
      </div>
    );
  }

  return (
    <section className="panel scheduler-panel">
      <p className="eyebrow">ADMINISTRACIÓN / SINCRONIZACIÓN</p>
      <h1>Orquestador</h1>
      {canSync ? (
        <div className="channel-selector-wrap">
          <span className="channel-selector-label">Canal:</span>
          <div className="channel-selector">
            {CHANNEL_OPTS.filter((opt) => opt.key !== "tch" || canImportTch).map((opt) => (
              <button key={opt.key} className={`channel-btn${selectedChannelKey === opt.key ? " active" : ""}${channelAvailable(opt.key) ? "" : " unavailable"}`} disabled={isRunning || triggering || !channelAvailable(opt.key)} title={channelAvailable(opt.key) ? undefined : CHANNEL_UNAVAILABLE_TITLE} onClick={() => setSelectedChannelKey(opt.key)}>{opt.label}</button>
            ))}
          </div>
          {selectedChannelKey === "virtualpos" && (
            <div className="channel-selector vp-sub-selector">
              {vpOptions.map((sub) => (
                <button key={sub.key} className={`channel-btn channel-btn-sm${effectiveVpSubKey === sub.key ? " active" : ""}`} disabled={isRunning || triggering} onClick={() => setVpSubKey(sub.key)}>{sub.label}</button>
              ))}
            </div>
          )}
          {unavailableNote ? <p className="channel-unavailable-note">{unavailableNote}</p> : null}
        </div>
      ) : null}
      {healthEntries.length > 0 ? (
        <section className="scheduler-health" aria-label="Estado de sincronización por canal">
          <ul className="scheduler-health-list">
            {healthEntries.map((entry) => (
              <li key={entry.channel} data-state={entryState(entry)}>
                <span className={`health-dot ${entry.level}`} data-level={entry.level} aria-hidden="true" />
                <span className="scheduler-health-name">{CHANNEL_NAME[entry.channel]}</span>
                <span className="scheduler-health-text mono">{channelText(entry)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="scheduler-section-header scheduler-processes-header">
        <h3 className="scheduler-section-title">Procesos programados</h3>
        {canSync && manualJobs.length > 0 ? (
          <button type="button" className="primary-button sjc-run-all" disabled={busy} aria-expanded={confirming === "all"} onClick={() => { setIncludeWrites(false); setConfirming("all"); }}>
            {batchRunning ? "Ejecutando procesos…" : `Ejecutar todos (${readJobs.length})`}
          </button>
        ) : null}
      </div>
      {confirmBox("all", runAllJobs)}
      {triggerError ? <p className="scheduler-error">{triggerError}</p> : null}
      {batchSteps ? (
        <section className="scheduler-batch" aria-label="Avance de la ejecución">
          <div className="scheduler-batch-head">
            <strong>{batchRunning ? "Ejecutando procesos" : "Última ejecución manual"}</strong>
            <span className="muted-copy mono">{batchSteps.filter((st) => st.state !== "queued" && st.state !== "running").length}/{batchSteps.length}</span>
            {!batchRunning ? <button type="button" className="text-button" onClick={() => setBatchSteps(null)}>Ocultar</button> : null}
          </div>
          <ol className="scheduler-batch-list">
            {batchSteps.map((st) => (
              <li key={st.jobId} data-state={st.state}>
                <span className={`badge ${STEP_BADGE[st.state]}`}>{label("runStatus", st.state)}</span>
                <span className="scheduler-batch-name">{st.name}</span>
                <span className="mono scheduler-batch-dur">{st.startedAt ? fmtDuration(st.startedAt, st.finishedAt ?? nowMs) : "—"}</span>
                {st.note ? <span className="scheduler-batch-note">{st.note}</span> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {jobs.length === 0 && jobsError ? (
        <p className="muted-copy">No se pudieron cargar los jobs. <button className="text-button" onClick={refreshData}>Reintentar</button></p>
      ) : jobs.length === 0 ? (
        <p className="muted-copy">
          No hay jobs programados. Puede que el scheduler esté apagado en este ambiente: revise su configuración{canSync ? " o use el selector de Canal para sincronizar manualmente" : ""}.
        </p>
      ) : jobs.map((job) => {
        const badge = jobBadge(job);
        const manual = isManualJob(job);
        const isSync = job.id === SYNC_JOB_ID;
        const last = job.last_run;
        const lastAge = last?.finished_at ? ageText((nowMs - new Date(last.finished_at).getTime()) / 3_600_000) : null;
        return (
          <div key={job.id} className="scheduler-job-card" data-job={job.id}>
            <div className="sjc-top">
              <div className="sjc-title">
                <span className="sjc-name">{job.name}</span>
                <span className="sjc-kind">{job.kind === "sync" || isSync ? "Sincronización" : "Mantenimiento"}</span>
              </div>
              <div className="sjc-top-right">
                <span className={`badge ${badge.cls}`}>{badge.text}</span>
                {job.status === "running" && isSync && globalPct !== null ? <span className="sjc-live-pct">{globalPct}%</span> : null}
              </div>
            </div>
            <div className="sjc-meta">
              <span className="sjc-schedule">{cronLabel(job.cron)}</span>
              <span className="sjc-next">Próx: <span className="mono">{fmtDate(job.next_run)}</span></span>
              {last ? (
                <>
                  <span className="sjc-last">Última: <span className="mono">{fmtDate(last.started_at)}</span>{lastAge ? ` (${lastAge})` : ""}</span>
                  <span className="sjc-dur">Duración: <span className="mono">{fmtDuration(last.started_at, last.finished_at)}</span></span>
                </>
              ) : <span className="sjc-last">Sin corridas registradas</span>}
            </div>
            {job.status === "running" && isSync && globalPct !== null ? (
              <div className="sjc-progress-wrap"><div className="sjc-progress-fill" style={{ width: `${globalPct}%` }} /></div>
            ) : null}
            <div className="sjc-actions">
              {isSync && selectedChannelKey === "tch" && canImportTch && !busy ? (
                <>
                  <input ref={reportInputRef} type="file" accept=".xlsx" hidden onChange={importTchReport} />
                  <button className="save-button sjc-btn" disabled={triggering} onClick={() => reportInputRef.current?.click()}>{triggering ? "Importando…" : "Importar reporte"}</button>
                </>
              ) : canSync && manual ? (
                <button className="save-button sjc-btn" disabled={busy} aria-expanded={confirming === job.id} onClick={() => setConfirming(job.id)}>
                  {isSync ? (selectedChannelKey === "all" ? "Sincronizar todos los canales" : `Sincronizar ${CHANNEL_OPTS.find((o) => o.key === selectedChannelKey)?.label}`) : "Ejecutar"}
                </button>
              ) : !manual ? <span className="sjc-auto-note">Solo automático: corre según su calendario.</span> : null}
              {job.status === "running" && isSync && job.active_run_id ? (
                <button className="save-button sjc-btn sjc-btn-live" onClick={() => { setActiveRunId(job.active_run_id!); setTriggeredChannels(undefined); }}>Ver progreso en vivo</button>
              ) : null}
            </div>
            {confirmBox(job.id, [job])}
          </div>
        );
      })}
      {activeRunId ? (
        <div className="sse-panel">
          <div className="sse-header">
            <div className="sse-header-left">
              <h3 className="sse-title">
                {isCompleted ? `✓ Completado — ${(completedEv?.total_records ?? 0).toLocaleString("es-CL")} registros en ${Math.floor((completedEv?.duration_s ?? 0) / 60)}m ${(completedEv?.duration_s ?? 0) % 60}s` : sseEvents.length === 0 ? "Conectando al stream…" : `Sincronizando… ${globalPct !== null ? `${globalPct}%` : ""}`}
              </h3>
              {sseEvents.length === 0 && polledPhase && <p className="sse-polled-phase">{phaseText(polledPhase)} — actualizando cada 4s</p>}
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
                    <span className="phase-label">{phaseText(phase)}</span>
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
                  <SseLogEntry event={e} />
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
              <tr><td colSpan={7} className="muted-copy" style={{ textAlign: "center", padding: "1rem" }}>{canSync ? "Aún no hay ejecuciones. Ejecute una sincronización manual desde un job programado." : "Aún no hay ejecuciones registradas."}</td></tr>
            ) : runs.items.map((run) => {
              const isThisRunActive = run.status === "running" && activeRunId === run.id;
              const showDetail = detailRunId === run.id;
              return (
                <Fragment key={run.id}>
                <tr>
                  <td className="runs-date">{fmtDate(run.started_at)}</td>
                  <td className="runs-date hide-mobile">{fmtDate(run.finished_at)}</td>
                  <td className="runs-dur">{isThisRunActive && globalPct !== null ? <span className="runs-live-dur">⟳ {globalPct}%</span> : fmtDuration(run.started_at, run.finished_at)}</td>
                  <td>{statusBadge(run.status)}</td>
                  <td className="runs-type">{runTypeLabel(run.channels_processed, enabled)}{failedChannelsLabel(run.channels_failed) ? <span className="runs-failed"> · {failedChannelsLabel(run.channels_failed)}</span> : null}</td>
                  <td className="runs-rec">{run.records_upserted != null ? <span className="runs-rec-val">{run.records_upserted.toLocaleString("es-CL")}</span> : <span className="muted-copy">—</span>}</td>
                  <td>{run.status === "running" ? (isThisRunActive ? <span className="runs-watching-dot" title="Viendo en vivo">●</span> : <button className="runs-ver-btn" onClick={() => { setActiveRunId(run.id); setTriggeredChannels(undefined); }}>Ver en vivo</button>) : <button className="runs-ver-btn" aria-expanded={showDetail} onClick={() => setDetailRunId(showDetail ? null : run.id)}>{showDetail ? "Ocultar" : "Detalle"}</button>}</td>
                </tr>
                {showDetail ? (
                  <tr className="runs-detail-row"><td colSpan={7}><RunResourceStats etlRunId={run.id} /></td></tr>
                ) : null}
                </Fragment>
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
