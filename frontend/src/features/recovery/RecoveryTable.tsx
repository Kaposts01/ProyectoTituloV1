import { clpOrDash } from "./format";
import { recoveryAmount, recoveryDisplay, recoveryNestedValue, recoveryRowKey, recoveryValue, text } from "../shared/utils";
import type { RecoveryRow } from "../shared/types";
import type { RecoveryGroup, RecoveryTab } from "./recoveryQuery";

type Props = {
  tab: RecoveryTab;
  group: RecoveryGroup;
  items: RecoveryRow[];
  selected: Set<string>;
  submitting: boolean;
  canRetry: boolean;
  canChangeCard: boolean;
  onToggle: (key: string, checked: boolean) => void;
  onToggleAll: (checked: boolean) => void;
  onRetry: (item: RecoveryRow) => void;
  onCardLink: (item: RecoveryRow) => void;
};

function dateColumnLabel(tab: RecoveryTab, group: RecoveryGroup): string {
  if (tab === "cancelled") return group === "inactiva" ? "Fecha cancelación" : group === "incobrable" ? "Último cobro" : "Fecha inicio";
  return tab === "retry" ? "Cargo rechazado" : tab === "history" ? "Fecha reintento" : "Vencimiento";
}

function dateValue(item: RecoveryRow, tab: RecoveryTab, group: RecoveryGroup): unknown {
  if (tab === "cancelled") {
    return group === "inactiva" ? recoveryValue(item, "cancelled_at", "canceled_at") : group === "incobrable" ? recoveryValue(item, "last_paid_date") : recoveryValue(item, "started_at");
  }
  if (tab === "retry") return recoveryValue(item, "charge_date", "rejected_at", "date");
  if (tab === "history") return recoveryValue(item, "requested_at");
  return recoveryValue(item, "expires_at", "expiration_date", "card_expiration");
}

export function RecoveryTable({ tab, group, items, selected, submitting, canRetry, canChangeCard, onToggle, onToggleAll, onRetry, onCardLink }: Props) {
  const allSelected = items.length > 0 && selected.size === items.length;
  const showRejection = tab === "retry" || tab === "card";
  const showVigente = tab !== "history";
  const colSpan = 5 +(tab === "retry" ? 1 : 0) + (tab === "cancelled" ? 1 : 0) + (showVigente ? 1 : 0) + (showRejection ? 3 : 0) + (tab === "history" ? 2 : 0) + (tab === "retry" || tab === "card" ? 1 : 0);
  return (
    <section className="panel recovery-table"><div className="table-wrap"><table><thead><tr>
      {tab === "retry" ? <th><input aria-label="Seleccionar todos" type="checkbox" checked={allSelected} onChange={(event) => onToggleAll(event.target.checked)} /></th> : null}
      <th>Suscripción</th>
      {tab === "cancelled" ? <th>RUT</th> : null}
      <th>Cliente</th>
      <th>{dateColumnLabel(tab, group)}</th>
      <th>Cuenta</th>
      <th>Monto</th>
      {showVigente ? <th>Monto vigente (último cobrado)</th> : null}
      {showRejection ? <><th>Código</th><th>Motivo de rechazo</th><th>Fecha de rechazo</th></> : null}
      {tab === "history" ? <><th>Resultado</th><th>Fecha conciliación</th></> : null}
      {tab === "retry" || tab === "card" ? <th>Acción</th> : null}
    </tr></thead><tbody>
      {items.map((item) => {
        const key = recoveryRowKey(item);
        const subscription = recoveryValue(item, "subscription_id", "subscription_external_id", "subscription") ?? recoveryNestedValue(item, "subscription", "id", "external_id");
        const client = recoveryValue(item, "client_name", "client", "client_external_id", "customer") ?? recoveryNestedValue(item, "client", "name", "external_id", "id");
        const monto = recoveryValue(item, "monto");
        return (
          <tr key={key}>
            {tab === "retry" ? <td><input aria-label={`Seleccionar ${key}`} type="checkbox" checked={selected.has(key)} onChange={(event) => onToggle(key, event.target.checked)} /></td> : null}
            <td className="recovery-id">{recoveryDisplay(subscription)}</td>
            {tab === "cancelled" ? <td className="mono">{text(recoveryValue(item, "rut"), "—")}</td> : null}
            <td>{recoveryDisplay(client)}</td>
            <td className="mono">{text(dateValue(item, tab, group), "—")}</td>
            <td>{text(recoveryValue(item, "account", "source"), "—")}</td>
            <td className="mono">{monto !== undefined ? clpOrDash(monto) : recoveryAmount(item)}</td>
            {showVigente ? <td className="mono">{clpOrDash(recoveryValue(item, "monto_vigente"))}</td> : null}
            {showRejection ? <>
              <td className="mono">{text(recoveryValue(item, "rejection_code"), "—")}</td>
              <td>{text(recoveryValue(item, "rejection_reason", "reason"), "—")}</td>
              <td className="mono">{text(recoveryValue(item, "rejection_at"), "—")}</td>
            </> : null}
            {tab === "history" ? <><td>{text(recoveryValue(item, "result"), "—")}</td><td className="mono">{text(recoveryValue(item, "observed_at"), "—")}</td></> : null}
            {tab === "retry" ? <td>{canRetry ? <button className="secondary-button" disabled={submitting} onClick={() => onRetry(item)}>Reintentar</button> : "—"}</td> : null}
            {tab === "card" ? <td>{canChangeCard ? <button className="secondary-button" disabled={submitting || !subscription} onClick={() => onCardLink(item)}>Generar enlace</button> : "—"}</td> : null}
          </tr>
        );
      })}
      {items.length === 0 ? <tr><td colSpan={colSpan}>Sin registros para los filtros seleccionados.</td></tr> : null}
    </tbody></table></div></section>
  );
}
