import { stepText } from "./cancellationLabels";
import type { ApplyResponse } from "./types";

export type NoticeState = { tone: "ok" | "warning"; text: string };

/** Resultado de aplicar, en español: completada, en trámite (TCH), no ejecutable o ya aplicada; avisa los pasos manuales. */
export function applyOutcomeNotice(result: ApplyResponse): NoticeState {
  const manual = result.steps.filter((s) => s.status === "manual");
  const manualNote = manual.length > 0 ? ` Quedan pasos manuales por hacer: ${manual.map((s) => stepText(s.step)).join(", ")}.` : "";
  if (result.status === "not_executable") {
    return { tone: "warning", text: "La baja ya no es ejecutable: la suscripción dejó de estar activa. La solicitud se cerró sin aplicar cambios." };
  }
  if (result.already_applied) return { tone: "ok", text: `La baja ya estaba aplicada; no se repitió nada.${manualNote}` };
  if (result.status === "pending_external") {
    return { tone: "warning", text: `Baja registrada en trámite: se cierra sola cuando el siguiente Excel de TCH traiga la ficha eliminada.${manualNote}` };
  }
  return { tone: manual.length > 0 ? "warning" : "ok", text: `Baja aplicada.${manualNote}` };
}


/** Confirmar exige una simulación sin bloqueos y, si la baja es irreversible, la casilla marcada. */
export function canConfirmApply(simulation: ApplyResponse, acknowledged: boolean): boolean {
  const plan = simulation.plan;
  if (!plan || plan.blockers.length > 0) return false;
  return !plan.irreversible || acknowledged;
}
