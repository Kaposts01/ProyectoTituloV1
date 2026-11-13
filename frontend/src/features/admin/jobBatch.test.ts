import { describe, expect, it } from "vitest";
import type { SchedulerJob } from "../shared/types";
import { BatchBusyError, isManualJob, manualJobsInOrder, runJobsSequentially, type BatchStep } from "./jobBatch";

const job = (id: string, extra: Partial<SchedulerJob> = {}): SchedulerJob => ({
  id, name: `Proceso ${id}`, cron: "0 3 * * *", next_run: null, last_run: null, status: "scheduled", ...extra,
});

describe("13D: qué procesos se lanzan con «Ejecutar todos»", () => {
  it("solo los manuales, con la sincronización de canales primero", () => {
    const jobs = [
      job("billing_renewal_check", { manual_run: true }),
      job("webhook_processor", { manual_run: false }),
      job("sync_all_channels", { manual_run: true }),
      job("alerts_check", { manual_run: false }),
    ];
    expect(manualJobsInOrder(jobs).map((j) => j.id)).toEqual(["sync_all_channels", "billing_renewal_check"]);
  });

  it("sin `manual_run` (backend anterior) usa la lista conocida", () => {
    expect(isManualJob(job("cancellation_sweep_applying"))).toBe(true);
    expect(isManualJob(job("retry_failed_channels"))).toBe(false);
  });
});

describe("13D: corrida secuencial", () => {
  it("lanza uno tras otro: nunca empieza el siguiente antes de que termine el anterior", async () => {
    const log: string[] = [];
    let active = 0;
    const updates: BatchStep[][] = [];
    const final = await runJobsSequentially([job("a"), job("b"), job("c")], {
      trigger: async (j) => { active += 1; expect(active).toBe(1); log.push(`start ${j.id}`); return `run-${j.id}`; },
      waitDone: async (j, runId) => {
        expect(runId).toBe(`run-${j.id}`);
        log.push(`done ${j.id}`);
        active -= 1;
        return j.id === "b" ? "failed" : j.id === "c" ? "partial" : "completed";
      },
      onUpdate: (steps) => updates.push(steps),
      now: () => 0,
    });
    expect(log).toEqual(["start a", "done a", "start b", "done b", "start c", "done c"]);
    expect(final.map((s) => s.state)).toEqual(["completed", "failed", "partial"]);
    expect(updates[0].map((s) => s.state)).toEqual(["queued", "queued", "queued"]);
    expect(updates.some((steps) => steps[1].state === "running" && steps[2].state === "queued")).toBe(true);
  });

  it("un 409 deja el paso «Omitida» y un error no detiene a los siguientes", async () => {
    const final = await runJobsSequentially([job("a"), job("b"), job("c")], {
      trigger: async (j) => {
        if (j.id === "a") throw new BatchBusyError("busy");
        if (j.id === "b") throw new Error("No se pudo iniciar el proceso.");
        return "r";
      },
      waitDone: async () => "completed",
      onUpdate: () => {},
    });
    expect(final.map((s) => s.state)).toEqual(["skipped", "failed", "completed"]);
    expect(final[0].note).toBe("Ya había una corrida en curso.");
    expect(final[1].note).toBe("No se pudo iniciar el proceso.");
  });
});
