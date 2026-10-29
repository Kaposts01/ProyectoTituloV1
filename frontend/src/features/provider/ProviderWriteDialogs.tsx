import { deleteEndpoint, providerEditFields } from "../virtualpos/constants";
import { resourceTitle, text, title } from "../shared/utils";
import type { ProviderWritesState } from "./useProviderWrites";

/** Diálogos de escritura de Toku y Payku: cambio de estado de suscripción, edición y eliminación de registros. */
export function ProviderWriteDialogs({ writes }: { writes: ProviderWritesState }) {
  const {
    editingProviderRecord,
    setEditingProviderRecord,
    savingProviderEdit,
    providerEditError,
    deletingRecord,
    setDeletingRecord,
    savingProviderDelete,
    providerDeleteError,
    managingTokuSub,
    setManagingTokuSub,
    savingTokuSubStatus,
    tokuSubStatusError,
    saveProviderEdit,
    confirmProviderDelete,
    changeTokuSubscriptionStatus,
  } = writes;
  const isTokuWritable = editingProviderRecord?.source === "toku" && editingProviderRecord?.resourceType === "customer";
  const isPaykuWritable = editingProviderRecord?.source === "payku" && editingProviderRecord?.resourceType === "client";
  const isProviderWritable = isTokuWritable || isPaykuWritable;
  return (
    <>
    {managingTokuSub ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <form
          className="edit-dialog"
          aria-modal="true"
          aria-label="Gestionar estado suscripción Toku"
          noValidate
          onSubmit={changeTokuSubscriptionStatus}
        >
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">TOKU / SUSCRIPCIÓN</p>
              <h3>Cambiar estado</h3>
            </div>
            <span>{text(managingTokuSub.payload.id, managingTokuSub.external_id)}</span>
          </div>
          <p className="edit-dialog-note">
            Se enviará POST <code>/subscriptions/{text(managingTokuSub.payload.id, managingTokuSub.external_id)}/status</code> a Toku.
            Estado actual: <strong>{text(managingTokuSub.payload.status)}</strong>
          </p>
          <div className="edit-form-grid">
            <label>
              Nuevo estado<span className="field-required" aria-hidden="true"> *</span>
              <select name="status">
                <option value="">Seleccionar...</option>
                <option value="ACTIVE">ACTIVE — Activar</option>
                <option value="PAUSED">PAUSED — Pausar</option>
                <option value="CANCELLED">CANCELLED — Cancelar</option>
              </select>
            </label>
          </div>
          {tokuSubStatusError ? <p className="error-message form-error">{tokuSubStatusError}</p> : null}
          <div className="edit-dialog-actions">
            <button type="submit" className="save-button" disabled={savingTokuSubStatus}>
              {savingTokuSubStatus ? "Aplicando..." : "Confirmar cambio"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setManagingTokuSub(null)}>
              Volver
            </button>
          </div>
        </form>
      </div>
    ) : null}
    {editingProviderRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form
        className="edit-dialog"
        aria-modal="true"
        aria-label={`Editar ${resourceTitle(editingProviderRecord.resourceType)}`}
        noValidate
        onSubmit={isProviderWritable ? saveProviderEdit : (e) => e.preventDefault()}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(editingProviderRecord.source).toUpperCase()} / EDICIÓN
            </p>
            <h3>Editar {resourceTitle(editingProviderRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(editingProviderRecord.record.payload.id, editingProviderRecord.record.external_id)}
          </span>
        </div>
        {!isProviderWritable ? (
          <p className="edit-dialog-note">
            Formulario visual. El guardado remoto permanece deshabilitado mientras{" "}
            {title(editingProviderRecord.source)} opere en modo solo lectura.
          </p>
        ) : null}
        <div className="edit-form-grid">
          {(providerEditFields[editingProviderRecord.source]?.[editingProviderRecord.resourceType] ?? []).map(
            (field) => (
              <label key={field.name}>
                {field.label}
                <input
                  name={field.name}
                  type={field.type ?? "text"}
                  defaultValue={text(editingProviderRecord.record.payload[field.name], "")}
                />
              </label>
            ),
          )}
        </div>
        {providerEditError ? <p className="error-message form-error">{providerEditError}</p> : null}
        <div className="edit-dialog-actions">
          {isProviderWritable ? (
            <button type="submit" className="save-button" disabled={savingProviderEdit}>
              {savingProviderEdit ? "Guardando..." : "Guardar cambios"}
            </button>
          ) : (
            <button type="button" className="save-button" disabled title="Guardado remoto no habilitado">
              Guardar cambios
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setEditingProviderRecord(null)}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null}
    {deletingRecord ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section
        className="edit-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Eliminar ${resourceTitle(deletingRecord.resourceType)}`}
      >
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">
              {title(deletingRecord.source).toUpperCase()} / ELIMINACIÓN
            </p>
            <h3>Eliminar {resourceTitle(deletingRecord.resourceType).toLowerCase()}</h3>
          </div>
          <span>
            {text(deletingRecord.record.payload.id, deletingRecord.record.external_id)}
          </span>
        </div>
        <p className="edit-dialog-note">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription"))
            ? `Se enviará DELETE ${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)} a ${title(deletingRecord.source)}. Esta acción no se puede deshacer.`
            : `Esta acción utilizará DELETE \`${deleteEndpoint(deletingRecord.source, deletingRecord.resourceType, deletingRecord.record)}\` cuando se habilite la escritura. Actualmente ${title(deletingRecord.source)} permanece en modo solo lectura.`}
        </p>
        {providerDeleteError ? <p className="error-message form-error">{providerDeleteError}</p> : null}
        <div className="edit-dialog-actions">
          {(deletingRecord.source === "toku" && deletingRecord.resourceType === "customer") ||
           (deletingRecord.source === "payku" && (deletingRecord.resourceType === "client" || deletingRecord.resourceType === "subscription")) ? (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled={savingProviderDelete}
              onClick={() => void confirmProviderDelete()}
            >
              {savingProviderDelete ? "Eliminando..." : "Confirmar eliminación"}
            </button>
          ) : (
            <button
              type="button"
              className="cancel-subscription-button"
              disabled
              title="Eliminación remota no habilitada"
            >
              Confirmar eliminación
            </button>
          )}
          <button type="button" className="cancel-button" onClick={() => setDeletingRecord(null)}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null}
    </>
  );
}
