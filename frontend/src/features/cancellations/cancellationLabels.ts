import { label, tryLabel, unknownLabel } from "../../i18n/label";
import type { Tone } from "../billing/billingLabels";
import type { CancellationStatus, StepStatus } from "./types";

/** Tono visual de cada estado (el color nunca va solo: el badge lleva punto y texto). */
const STATUS_TONE: Record<CancellationStatus, Tone> = {
  pending: "warning",
  approved: "ok",
  applying: "neutral",
  pending_external: "warning",
  completed: "ok",
  failed: "error",
  requires_reconciliation: "error",
  rejected: "neutral",
  withdrawn: "neutral",
  expired: "neutral",
  not_executable: "neutral",
};

const STEP_TONE: Record<StepStatus, Tone> = { pending: "neutral", done: "ok", failed: "error", skipped: "neutral", manual: "warning" };

export const statusText = (status: string) => label("cancellationStatus", status);
export const statusTone = (status: string): Tone => STATUS_TONE[status as CancellationStatus] ?? "neutral";
export const channelText = (channel: string) => label("channel", channel);
export const reasonText = (reason: string) => label("cancellationReason", reason);
export const stepText = (step: string) => label("cancellationStep", step);
export const stepStatusText = (status: string) => label("cancellationStepStatus", status);
export const stepTone = (status: string): Tone => STEP_TONE[status as StepStatus] ?? "neutral";
export const actionText = (action: string) => label("cancellationAction", action);
export const eventText = (eventType: string) => label("cancellationEvent", eventType);
export const stopModeText = (mode: string) => label("cancellationStopMode", mode);

/** Código de un paso o de un bloqueo (`PENDING_CHARGES_REMAIN`, `INVOICE_IN_PROGRESS`…): siempre del catálogo. */
export function codeText(code: string): string {
  return tryLabel("cancellationError", code) ?? unknownLabel(code);
}

/** Instrucción de una tarea manual (por código del paso o por motivo de la vista previa). */
export function manualText(code: string): string {
  return tryLabel("cancellationManual", code) ?? unknownLabel(code);
}


export type DetailActions = { approve: boolean; reject: boolean; withdraw: boolean; reopen: boolean; apply: boolean };

/**
 * Acciones visibles para el estado y los permisos. El servidor decide en último término (`not_approver`,
 * `invalid_request_state`…). «Retirar» exige además ser el solicitante o admin (`canWithdraw`).
 */
export function availableActions(
  request: { status: string },
  can: (permission: string) => boolean,
  perms: { request: string; approve: string },
): DetailActions {
  const approver = can(perms.approve);
  const requester = can(perms.request);
  return {
    approve: approver && request.status === "pending",
    reject: approver && request.status === "pending",
    withdraw: requester && request.status === "pending",
    reopen: approver && (request.status === "failed" || request.status === "requires_reconciliation"),
    apply: approver && request.status === "approved",
  };
}

/** Retirar: solo el solicitante o un admin (el API responde 403 antes que 409). Sin usuario no se oculta nada. */
export function canWithdraw(request: { requested_by_user_id: string }, currentUserId: string | undefined, isAdmin: boolean): boolean {
  return !currentUserId || isAdmin || request.requested_by_user_id === currentUserId;
}
