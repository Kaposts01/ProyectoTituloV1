import type { SchedulerJob } from "../shared/types";

/** Jobs que el backend ejecuta a mano (POST /scheduler/jobs/{id}/run) si la API aún no envía `manual_run`. */
const KNOWN_MANUAL_JOBS = new Set([
  "sync_all_channels",
  "billing_renewal_check", "billing_expire_requests", "billing_sweep_applying",
  "cancellation_expire_requests", "cancellation_sweep_applying",
]);
export const SYNC_JOB_ID = "sync_all_channels";

/** 13D: ¿se puede lanzar a mano? Los demás procesos solo corren por calendario. */
export function isManualJob(job: Pick<SchedulerJob, "id" | "manual_run">): boolean {
  return job.manual_run ?? KNOWN_MANUAL_JOBS.has(job.id);
}

/** Orden de «Ejecutar todos»: primero la sincronización de canales y después el resto, en el orden del listado. */
export function manualJobsInOrder(jobs: SchedulerJob[]): SchedulerJob[] {
  const manual = jobs.filter(isManualJob);
  return [...manual.filter((job) => job.id === SYNC_JOB_ID), ...manual.filter((job) => job.id !== SYNC_JOB_ID)];
}

/**
 * ¿Es un proceso de sincronización/lectura? Los de facturación y bajas (`billing_*`, `cancellation_*`: renovación de
 * calendario, vencimiento de solicitudes, barrido de las que quedaron «aplicando») escriben o pueden escribir, así que
 * nunca cuentan como lectura aunque la API diga otra cosa. Sin `kind`, solo la sincronización de canales es lectura.
 */
export function isReadOnlyJob(job: Pick<SchedulerJob, "id" | "kind">): boolean {
  if (job.id.startsWith("billing_") || job.id.startsWith("cancellation_")) return false;
  return job.kind ? job.kind === "sync" : job.id === SYNC_JOB_ID;
}

/**
 * Lista de «Ejecutar todos»: por defecto solo los procesos de lectura. Facturación y bajas entran únicamente si se
 * marcó la casilla explícita del diálogo de confirmación (`includeWrites`).
 */
export function batchJobs(jobs: SchedulerJob[], includeWrites: boolean): SchedulerJob[] {
  const manual = manualJobsInOrder(jobs);
  return includeWrites ? manual : manual.filter(isReadOnlyJob);
}

export type BatchStepState = "queued" | "running" | "completed" | "partial" | "failed" | "skipped";
export type BatchStep = { jobId: string; name: string; state: BatchStepState; startedAt?: number; finishedAt?: number; note?: string };

export type BatchDeps = {
  /** Lanza el job y devuelve su `run_id`. Un 409 (ya hay una corrida activa) debe lanzar `BatchBusyError`. */
  trigger: (job: SchedulerJob) => Promise<string>;
  /** Espera a que la corrida termine y devuelve su estado final (`completed`, `partial` o `failed`). */
  waitDone: (job: SchedulerJob, runId: string) => Promise<string>;
  onUpdate: (steps: BatchStep[]) => void;
  /** Para cortar la cola si el panel se desmonta. */
  cancelled?: () => boolean;
  now?: () => number;
};

export class BatchBusyError extends Error {}

/**
 * 13D: corre los procesos UNO TRAS OTRO (nunca dos a la vez: respeta el lock de corridas del backend). Cada paso
 * pasa por «En cola» → «En curso» → «Completada / Parcial / Fallida»; si el backend dice que ya había una corrida
 * activa (409), el paso queda «Omitida» y la cola sigue. Un paso que falla no detiene a los siguientes.
 */
export async function runJobsSequentially(jobs: SchedulerJob[], deps: BatchDeps): Promise<BatchStep[]> {
  const now = deps.now ?? Date.now;
  let steps: BatchStep[] = jobs.map((job) => ({ jobId: job.id, name: job.name, state: "queued" }));
  const update = (index: number, patch: Partial<BatchStep>) => {
    steps = steps.map((step, i) => (i === index ? { ...step, ...patch } : step));
    deps.onUpdate(steps);
  };
  deps.onUpdate(steps);
  for (const [index, job] of jobs.entries()) {
    if (deps.cancelled?.()) break;
    update(index, { state: "running", startedAt: now() });
    try {
      const runId = await deps.trigger(job);
      const final = await deps.waitDone(job, runId);
      const state: BatchStepState = final === "completed" || final === "partial" ? final : "failed";
      update(index, { state, finishedAt: now() });
    } catch (err) {
      if (err instanceof BatchBusyError) update(index, { state: "skipped", finishedAt: now(), note: "Ya había una corrida en curso." });
      else update(index, { state: "failed", finishedAt: now(), note: err instanceof Error && err.message ? err.message : undefined });
    }
  }
  return steps;
}
