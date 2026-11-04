import { useCallback, useEffect, useRef, useState } from "react";
import { getJson } from "../../api";
import * as api from "./billingApi";
import { describeBillingError, type BillingErrorInfo } from "./billingErrors";
import { buildPolicyPatch, diffPolicyValues, patchIsEmpty, policyToDraft, type PolicyDraft } from "./billingForm";
import { formatDateTime } from "./billingLabels";
import type { Policy, PolicyAuditEntry } from "./types";
import { Notice } from "./ui";
import "./billing.css";

type RoleRef = { id: string; name: string };
type UserRef = { id: string; username: string; is_active: boolean };

type Props = {
  roles: RoleRef[];
  /** Si el actor puede listar usuarios (users.manage); si no, los usuarios aprobadores se muestran por ID. */
  canListUsers: boolean;
};

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...new Set([...list, value])] : list.filter((x) => x !== value);
}

/** Política de aprobadores: aprobadores, autoaprobación, doble aprobación, umbrales, expiración, horizonte y ventana. */
export function PolicyPanel({ roles, canListUsers }: Props) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [draft, setDraft] = useState<PolicyDraft | null>(null);
  const [users, setUsers] = useState<UserRef[]>([]);
  const [audit, setAudit] = useState<PolicyAuditEntry[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<BillingErrorInfo | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);

  const loadAudit = useCallback(async () => {
    try {
      setAudit((await api.fetchPolicyAudit(20, 0)).items);
      setAuditError(null);
    } catch (err) {
      setAuditError(describeBillingError(err, "No se pudo cargar el historial de cambios.").message);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const p = await api.fetchPolicy();
      setPolicy(p);
      setDraft(policyToDraft(p));
    } catch (err) {
      setLoadError(describeBillingError(err, "No se pudo cargar la política de aprobaciones.").message);
    } finally {
      setLoading(false);
    }
    void loadAudit();
  }, [loadAudit]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!canListUsers) return;
    getJson<UserRef[]>("/api/v1/admin/users").then((list) => setUsers(list.filter((u) => u.is_active))).catch(() => setUsers([]));
  }, [canListUsers]);

  const set = <K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
    setSaveError(null);
    setNotice(null);
  };

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!policy || !draft || inFlight.current) return;
    const { errors, patch } = buildPolicyPatch(policy, draft);
    setFieldErrors(errors as Record<string, string>);
    if (Object.keys(errors).length > 0) return;
    if (patchIsEmpty(patch)) { setNotice("No hay cambios para guardar."); return; }
    inFlight.current = true;
    setSaving(true);
    setSaveError(null);
    setNotice(null);
    try {
      const updated = await api.updatePolicy(patch);
      setPolicy(updated);
      setDraft(policyToDraft(updated));
      setNotice("Política actualizada. El cambio quedó registrado en el historial.");
      void loadAudit();
    } catch (err) {
      setSaveError(describeBillingError(err, "No se pudo guardar la política."));
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  if (loading && !policy) return <p className="muted-copy" role="status">Cargando política…</p>;
  if (loadError || !policy || !draft) {
    return (
      <div>
        <Notice tone="error">{loadError ?? "No se pudo cargar la política."}</Notice>
        <button className="bx-btn bx-btn-ghost" onClick={() => void load()}>Reintentar</button>
      </div>
    );
  }

  const known = new Set(users.map((u) => u.id));
  const orphanIds = draft.approverUserIds.filter((id) => !known.has(id));
  const err = (key: string) => fieldErrors[key];
  const noApprovers = draft.approverRoles.length === 0 && draft.approverUserIds.length === 0;
  // Cambios reales respecto de la política cargada (listas sin importar el orden). El motivo no cuenta: solo acompaña a un cambio.
  const norm = (d: PolicyDraft) => JSON.stringify({ ...d, reason: "", approverRoles: [...d.approverRoles].sort(), approverUserIds: [...d.approverUserIds].sort() });
  const dirty = norm(draft) !== norm(policyToDraft(policy));
  const canDiscard = dirty || draft.reason !== "" || Object.keys(fieldErrors).length > 0;
  /** Los umbrales solo aplican con doble aprobación: se atenúan, pero conservan el valor y siguen en el borrador/parche. */
  const DUAL_ONLY: Array<keyof PolicyDraft> = ["dualThresholdSubscriptions", "dualThresholdVariationPct"];
  const numberField = (key: keyof PolicyDraft, label: string, hint: string) => {
    const off = DUAL_ONLY.includes(key) && !draft.dualApproval;
    const hintId = `bx-pol-hint-${key}`;
    return (
      <label className={off ? "is-off" : undefined}>{label}
        <input
          className="mono" inputMode="decimal" value={String(draft[key])} disabled={saving || off} aria-invalid={err(key) ? true : undefined}
          aria-describedby={err(key) ? `${hintId} bx-pol-${key}` : hintId} onChange={(e) => set(key, e.target.value as never)}
        />
        <span id={hintId} className="bx-hint">{off ? "Solo aplica si se exige doble aprobación" : hint}</span>
        {err(key) ? <span id={`bx-pol-${key}`} className="bx-field-error" role="alert">{err(key)}</span> : null}
      </label>
    );
  };

  return (
    <div className="bx-form">
      <p className="muted-copy">
        Define quién puede aprobar cambios de cobro y cómo se aprueban. Solo se envían los campos que modifique y cada cambio queda auditado.
      </p>
      <form onSubmit={save} noValidate aria-label="Política de aprobaciones">
        <div className="bx-form-grid">
          <fieldset className="bx-group wide">
            <legend>Roles aprobadores</legend>
            <div className="bx-checklist">
              {roles.map((r) => (
                <label key={r.id} className="bx-check">
                  <input type="checkbox" checked={draft.approverRoles.includes(r.name)} disabled={saving} onChange={(e) => set("approverRoles", toggle(draft.approverRoles, r.name, e.target.checked))} />
                  <code>{r.name}</code>
                </label>
              ))}
              {roles.length === 0 ? <span className="muted-copy">Sin roles disponibles.</span> : null}
            </div>
          </fieldset>
          <hr className="bx-sep wide" />
          <fieldset className="bx-group wide">
            <legend>Usuarios aprobadores</legend>
            <div className="bx-checklist">
              {users.map((u) => (
                <label key={u.id} className="bx-check">
                  <input type="checkbox" checked={draft.approverUserIds.includes(u.id)} disabled={saving} onChange={(e) => set("approverUserIds", toggle(draft.approverUserIds, u.id, e.target.checked))} />
                  {u.username}
                </label>
              ))}
              {orphanIds.map((id) => (
                <label key={id} className="bx-check">
                  <input type="checkbox" checked disabled={saving} onChange={(e) => set("approverUserIds", toggle(draft.approverUserIds, id, e.target.checked))} />
                  <span className="mono">{id.slice(0, 8)}…</span>
                </label>
              ))}
              {users.length === 0 && orphanIds.length === 0 ? <span className="muted-copy">{canListUsers ? "Sin usuarios activos." : "No tiene permiso para listar usuarios; solo puede editar los roles."}</span> : null}
            </div>
          </fieldset>
          <p className="bx-hint wide">Aprueba quien tenga un rol marcado o esté marcado como usuario</p>
          {noApprovers ? <div className="wide"><Notice tone="warning">No hay ningún rol ni usuario aprobador seleccionado: la política no podrá guardarse (AP-23).</Notice></div> : null}

          <hr className="bx-sep wide" />
          <label className="bx-check wide">
            <input type="checkbox" checked={draft.selfApproval} disabled={saving} onChange={(e) => set("selfApproval", e.target.checked)} />
            Permitir autoaprobación (un aprobador aprueba sus propias solicitudes; queda auditado)
          </label>
          <label className="bx-check wide">
            <input type="checkbox" checked={draft.dualApproval} disabled={saving} onChange={(e) => set("dualApproval", e.target.checked)} />
            Exigir doble aprobación cuando se superen los umbrales
          </label>
          {numberField("dualThresholdSubscriptions", "Umbral de suscripciones", "Cantidad desde la cual se exige doble aprobación.")}
          {numberField("dualThresholdVariationPct", "Umbral de variación (%)", "Variación del monto desde la cual se exige doble aprobación.")}
          {numberField("renewalThresholdDays", "N de renovación (días)", "Días mínimos antes del fin del calendario para renovarlo.")}
          {numberField("requestExpiryDays", "Expiración de solicitudes (días)", "Días que una solicitud pendiente espera antes de expirar.")}
          {numberField("horizonMonths", "Horizonte (meses)", "Meses hacia adelante que cubre un cambio de cobro")}
          {numberField("windowDays", "Ventana (días)", "Días hacia atrás en los que un mes atrasado se reemplaza con fecha de mañana; más antiguo va a revisión manual")}
          <label className="wide">Motivo del cambio (opcional, queda en la auditoría)
            <textarea value={draft.reason} maxLength={1000} disabled={saving} onChange={(e) => set("reason", e.target.value)} />
            {err("reason") ? <span className="bx-field-error" role="alert">{err("reason")}</span> : null}
          </label>
        </div>

        {saveError ? <Notice tone="error">{saveError.message}</Notice> : null}
        <div aria-live="polite">{notice ? <Notice tone="ok" live>{notice}</Notice> : null}</div>
        <div className="bx-actions-row">
        <div className="bx-actions">
          <button type="submit" className="bx-btn bx-btn-primary" disabled={saving || !dirty}>{saving ? "Guardando…" : "Guardar política"}</button>
          <button type="button" className="bx-btn bx-btn-ghost" disabled={saving || !canDiscard} onClick={() => { setDraft(policyToDraft(policy)); setFieldErrors({}); setSaveError(null); }}>Descartar cambios</button>
        </div>
        {dirty ? <span className="bx-dirty" role="status">Cambios sin guardar</span> : null}
        </div>
      </form>

      <h3>Historial de cambios</h3>
      {auditError ? <Notice tone="error">{auditError}</Notice> : null}
      {audit.length === 0 && !auditError ? <p className="muted-copy">Aún no hay cambios registrados.</p> : null}
      {audit.length > 0 ? (
        <div className="table-wrap">
          <table className="bx-table">
            <caption className="bx-sr">Historial de cambios de la política</caption>
            <thead><tr><th scope="col">Fecha</th><th scope="col">Usuario</th><th scope="col">Cambios</th><th scope="col">Motivo</th></tr></thead>
            <tbody>
              {audit.map((a) => {
                const changes = diffPolicyValues(a.before_values, a.after_values);
                return (
                  <tr key={a.id}>
                    <td className="mono">{formatDateTime(a.changed_at)}</td>
                    <td className="mono">{a.changed_by ?? "—"}</td>
                    <td>
                      {changes.length === 0 ? "—" : (
                        <ul style={{ margin: 0, paddingLeft: 16 }}>
                          {changes.map((c) => <li key={c.field}>{c.label}: <span className="mono">{c.before}</span> → <span className="mono">{c.after}</span></li>)}
                        </ul>
                      )}
                    </td>
                    <td>{a.reason ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
