import type { ApplyResponse } from "./types";

export type ApplyOutcome = { tone: "ok" | "warning"; message: string };

/** Motivo (código estable del backend) por el que una solicitud aprobada resultó `no_ejecutable`. Texto fijo local. */
const NOT_EXECUTABLE_REASONS: Record<string, string> = {
  subscription_not_active: "la suscripción ya no es ejecutable (no está activa)",
  plan_changed: "el plan de la suscripción cambió desde la aprobación",
  invalid_plan: "el plan recalculado tiene errores",
};
const NOT_EXECUTABLE_DEFAULT = "la suscripción ya no es ejecutable";

function count(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Interpreta la respuesta 200 de apply. Un 200 puede ser `no_ejecutable`: nunca se presenta como éxito. */
export function applyOutcome(result: ApplyResponse): ApplyOutcome {
  if (result.already_applied) return { tone: "ok", message: "La solicitud ya estaba aplicada." };
  if (result.status !== "ejecutada") {
    const why = (result.reason && NOT_EXECUTABLE_REASONS[result.reason]) || NOT_EXECUTABLE_DEFAULT;
    return { tone: "warning", message: `La solicitud no se pudo ejecutar: ${why}.` };
  }
  const review = count(result.manual_review_months);
  const tail = review > 0 ? `; ${review} meses quedan en revisión manual` : "";
  return { tone: "ok", message: `Cambio aplicado: ${count(result.created)} cobros creados y ${count(result.cancelled)} cancelados${tail}.` };
}
