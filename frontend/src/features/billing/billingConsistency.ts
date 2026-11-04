import type { Tone } from "./billingLabels";
import type { ConsistencyFinding, ConsistencySeverity, ReconciliationKind } from "./types";

/** Texto de cada hallazgo de los controles GB-CS-02..14 (BILL-10). Desconocido: se muestra el código tal cual. */
export const FINDING_LABELS: Record<string, string> = {
  amount_mismatch: "Pendiente con monto distinto del programado",
  double_pending: "Mes con dos cobros pendientes",
  missing_month: "Mes del horizonte sin cobro",
  overdue_pending: "Cobro pendiente vencido",
  duplicate_local_charge: "Cobro duplicado en la base",
  managed_not_synced: "Cobro del CRM aún no sincronizado",
  unregistered_charge: "Cobro no registrado por el CRM (posible doble cobro)",
  managed_cancelled_externally: "Cobro del CRM cancelado fuera del CRM",
  subscription_not_active: "Suscripción no activa con gestión abierta",
  reconciliation_required: "Requiere conciliación",
  payment_amount_mismatch: "Pago con monto distinto de la cuota",
  double_paid: "Dos cobros pagados en el mismo mes",
  current_amount_family_mismatch: "Monto vigente distinto entre tablas",
  managed_without_approval: "Cobro del CRM sin solicitud aprobada",
  reverted_to_old_amount: "Volvió al monto antiguo tras el horizonte",
};

export const KIND_LABELS: Record<ReconciliationKind, string> = {
  request: "Solicitud",
  managed_charge: "Cobro del CRM",
  write_run: "Escritura registrada",
};

export function findingLabel(code: string): string {
  return FINDING_LABELS[code] ?? code;
}

export function severityTone(severity: ConsistencySeverity | string): Tone {
  if (severity === "P0") return "error";
  if (severity === "P1") return "warning";
  return "neutral";
}

/** P0 primero, luego los que bloquean, luego por suscripción y mes (orden estable para la tabla). */
export function sortFindings(findings: ConsistencyFinding[]): ConsistencyFinding[] {
  const rank = (s: string) => (s === "P0" ? 0 : s === "P1" ? 1 : 2);
  return [...findings].sort((a, b) =>
    rank(a.severity) - rank(b.severity)
    || Number(b.blocks) - Number(a.blocks)
    || a.subscription_external_id.localeCompare(b.subscription_external_id)
    || (a.month ?? "").localeCompare(b.month ?? "")
    || a.code.localeCompare(b.code));
}

/** Cargo o cargos afectados, sin texto libre del proveedor (solo ids que el backend ya acotó). */
export function findingCharges(finding: ConsistencyFinding): string {
  const ids = finding.detail.charge_ids;
  if (Array.isArray(ids)) return ids.filter((x) => typeof x === "string").join(", ");
  const id = finding.detail.charge_id;
  return typeof id === "string" ? id : "";
}
