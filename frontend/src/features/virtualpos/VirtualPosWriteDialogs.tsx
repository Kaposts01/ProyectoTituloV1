import { text, documentType } from "../shared/utils";
import {
  virtualPosClientEditFields, virtualPosPlanCreateFields, planDefaultValues, virtualPosSubscriptionCreateFields,
  subscriptionRequiredFields,
} from "./constants";
import type { VirtualPosWritesState } from "./useVirtualPosWrites";

/** Diálogos de escritura de VirtualPOS: cliente, plan, suscripción, cancelaciones, reintento y cargo nuevo. */
export function VirtualPosWriteDialogs({ writes, vp2Enabled }: { writes: VirtualPosWritesState; vp2Enabled: boolean }) {
  const {
    editingClient,
    setEditingClient,
    creatingClient,
    setCreatingClient,
    clientVpPlatform,
    setClientVpPlatform,
    savingClient,
    clientFormError,
    clientFieldErrors,
    creatingPlan,
    setCreatingPlan,
    planVpPlatform,
    setPlanVpPlatform,
    savingPlan,
    planFormError,
    planFieldErrors,
    creatingSubscription,
    setCreatingSubscription,
    subVpPlatform,
    setSubVpPlatform,
    savingSubscription,
    subscriptionFormError,
    subscriptionFieldErrors,
    cancelingSubscription,
    setCancelingSubscription,
    savingCancelSubscription,
    cancelSubscriptionError,
    setCancelSubscriptionError,
    creatingCharge,
    setCreatingCharge,
    savingCharge,
    chargeFormError,
    chargeFieldErrors,
    cancelingCharge,
    setCancelingCharge,
    savingCancelCharge,
    cancelChargeError,
    retryingCharge,
    setRetryingCharge,
    savingRetryCharge,
    retryChargeError,
    saveVirtualPOSClient,
    createVirtualPOSClient,
    createVirtualPOSPlan,
    createVirtualPOSSubscription,
    createVirtualPOSCharge,
    cancelVirtualPOSSubscription,
    cancelVirtualPOSCharge,
    retryVirtualPOSCharge,
  } = writes;
  const createRequiredFields = new Set(["first_name", "email", "social_id", "social_id_type"]);
  const createDefaultValues: Record<string, string> = { status: "ACTIVO", type: "PERSONA", social_id_type: "1" };
  return (
    <>
    {editingClient || creatingClient ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <form className="edit-dialog" aria-modal="true" aria-label={creatingClient ? "Crear cliente VirtualPOS" : "Editar cliente VirtualPOS"} noValidate onSubmit={creatingClient ? createVirtualPOSClient : saveVirtualPOSClient}>
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / {creatingClient ? "CREACIÓN" : "EDICIÓN"}</p>
            <h3>{creatingClient ? "Nuevo cliente" : "Editar cliente"}</h3>
          </div>
          {!creatingClient && editingClient ? <span>{text(editingClient.payload.uuid, editingClient.external_id)}</span> : null}
        </div>
        <p className="edit-dialog-note">
          {creatingClient
            ? "Los campos marcados con * son obligatorios. El cliente se creará en VirtualPOS y en la base de datos local."
            : "Los cambios se aplican mediante la API interna. VirtualPOS debe estar habilitado localmente para completar el guardado."}
        </p>
        {creatingClient && (
          <div className="vp-account-selector">
            <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
            <div className="vp-account-selector-buttons">
              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos1")}>
                Cuenta 1
              </button>
{vp2Enabled && (              <button type="button" className={`vp-account-btn${clientVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setClientVpPlatform("virtualpos2")}>
                Cuenta 2
              </button>)}
            </div>
          </div>
        )}
        <div className="edit-form-grid">
          {virtualPosClientEditFields.map((field) => {
            const isRequired = creatingClient && createRequiredFields.has(field.name);
            const hasError = Boolean(clientFieldErrors[field.name]);
            const defaultVal = creatingClient
              ? (createDefaultValues[field.name] ?? "")
              : (field.name === "social_id_type" ? documentType(editingClient!.payload[field.name]) : text(editingClient!.payload[field.name], ""));
            return (
              <label className={hasError ? "field-error" : ""} key={field.name}>
                {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                {field.options ? (
                  <select
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    name={field.name}
                    defaultValue={defaultVal}
                  >
                    {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                ) : (
                  <input
                    name={field.name}
                    type={field.type ?? "text"}
                    defaultValue={defaultVal}
                    aria-invalid={hasError}
                    aria-required={isRequired}
                    placeholder={field.name === "social_id" ? (creatingClient ? "Ej: 12345678-9" : undefined) : undefined}
                  />
                )}
                {hasError ? <span className="field-error-message">{clientFieldErrors[field.name]}</span> : null}
              </label>
            );
          })}
          <label className="edit-form-wide">
            Nota privada
            <textarea name="private_note" defaultValue={creatingClient ? "" : text(editingClient!.payload.private_note, "")} />
          </label>
        </div>
        {clientFormError ? <p className="error-message form-error">{clientFormError}</p> : null}
        <div className="edit-dialog-actions">
          <button type="submit" className="save-button" disabled={savingClient}>
            {savingClient ? "Guardando..." : creatingClient ? "Crear cliente" : "Guardar cambios"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setEditingClient(null); setCreatingClient(false); }}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  ) : null}
    {creatingPlan ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <form
          className="edit-dialog edit-dialog-wide"
          aria-modal="true"
          aria-label="Crear plan VirtualPOS"
          noValidate
          onSubmit={createVirtualPOSPlan}
        >
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">VIRTUALPOS / PLANES</p>
              <h3>Nuevo plan</h3>
            </div>
          </div>
          <p className="edit-dialog-note">
            Los campos marcados con * son obligatorios. El plan se creará en VirtualPOS y en la base de datos local.
          </p>
          <div className="vp-account-selector">
            <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
            <div className="vp-account-selector-buttons">
              <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos1")}>
                Cuenta 1
              </button>
{vp2Enabled && (              <button type="button" className={`vp-account-btn${planVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setPlanVpPlatform("virtualpos2")}>
                Cuenta 2
              </button>)}
            </div>
          </div>
          <div className="edit-form-grid">
            {virtualPosPlanCreateFields.map((field) => {
              const hasError = Boolean(planFieldErrors[field.name]);
              const defaultVal = planDefaultValues[field.name] ?? "";
              return (
                <label className={hasError ? "field-error" : ""} key={field.name}>
                  {field.label}{field.required ? <span className="field-required" aria-hidden="true"> *</span> : null}
                  {field.options ? (
                    <select name={field.name} defaultValue={defaultVal} aria-invalid={hasError} aria-required={field.required}>
                      {!field.required && <option value="">Sin especificar</option>}
                      {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                    </select>
                  ) : (
                    <input
                      name={field.name}
                      type={field.type ?? "text"}
                      defaultValue={defaultVal}
                      aria-invalid={hasError}
                      aria-required={field.required}
                      placeholder={field.name === "amount" ? "Ej: 9990" : field.name === "num_charges" ? "0 = ilimitado" : undefined}
                    />
                  )}
                  {hasError ? <span className="field-error-message">{planFieldErrors[field.name]}</span> : null}
                </label>
              );
            })}
          </div>
          {planFormError ? <p className="error-message form-error">{planFormError}</p> : null}
          <div className="edit-dialog-actions">
            <button type="submit" className="save-button" disabled={savingPlan}>
              {savingPlan ? "Creando..." : "Crear plan"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setCreatingPlan(false)}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    ) : null}
    {creatingSubscription ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <form
          className="edit-dialog edit-dialog-wide"
          aria-modal="true"
          aria-label="Crear suscripción VirtualPOS"
          noValidate
          onSubmit={createVirtualPOSSubscription}
        >
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">VIRTUALPOS / SUSCRIPCIONES</p>
              <h3>Nueva suscripción</h3>
            </div>
          </div>
          <p className="edit-dialog-note">
            Los campos marcados con * son obligatorios. El RUT será validado. Las URLs de retorno y callback se codificarán en Base64 automáticamente.
          </p>
          <div className="vp-account-selector">
            <span className="vp-account-selector-label">Cuenta VirtualPOS:</span>
            <div className="vp-account-selector-buttons">
              <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos1" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos1")}>
                Cuenta 1
              </button>
{vp2Enabled && (              <button type="button" className={`vp-account-btn${subVpPlatform === "virtualpos2" ? " active" : ""}`} onClick={() => setSubVpPlatform("virtualpos2")}>
                Cuenta 2
              </button>)}
            </div>
          </div>
          <div className="edit-form-grid">
            {virtualPosSubscriptionCreateFields.map((field) => {
              const hasError = Boolean(subscriptionFieldErrors[field.name]);
              const isRequired = subscriptionRequiredFields.has(field.name);
              return (
                <label className={hasError ? "field-error" : ""} key={field.name}>
                  {field.label}{isRequired ? <span className="field-required" aria-hidden="true"> *</span> : null}
                  {field.options ? (
                    <select name={field.name} aria-invalid={hasError} aria-required={isRequired}>
                      <option value="">Sin especificar</option>
                      {field.options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                    </select>
                  ) : (
                    <input
                      name={field.name}
                      type={field.type ?? "text"}
                      aria-invalid={hasError}
                      aria-required={isRequired}
                      placeholder={
                        field.name === "social_id" ? "Ej: 12345678-9"
                        : field.name === "plan_id" ? "ID exacto del plan en VirtualPOS"
                        : field.name === "phone_number" ? "Ej: 56912345678"
                        : undefined
                      }
                    />
                  )}
                  {hasError ? <span className="field-error-message">{subscriptionFieldErrors[field.name]}</span> : null}
                </label>
              );
            })}
          </div>
          {subscriptionFormError ? <p className="error-message form-error">{subscriptionFormError}</p> : null}
          <div className="edit-dialog-actions">
            <button type="submit" className="save-button" disabled={savingSubscription}>
              {savingSubscription ? "Creando..." : "Crear suscripción"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setCreatingSubscription(false)}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    ) : null}
    {cancelingSubscription ? (
    <div className="edit-dialog-backdrop" role="presentation">
      <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar subscripción VirtualPOS">
        <div className="edit-dialog-heading">
          <div>
            <p className="eyebrow">VIRTUALPOS / CANCELACIÓN</p>
            <h3>¿Estás seguro de cancelar esta suscripción?</h3>
          </div>
          <span>{text(cancelingSubscription.payload.id, cancelingSubscription.external_id)}</span>
        </div>
        <p className="edit-dialog-note">
          Esta acción cancelará la suscripción en VirtualPOS (DELETE /v3/suscription/…). Los cargos futuros se detendrán y no se puede deshacer.
        </p>
        {cancelSubscriptionError && <p className="edit-dialog-error">{cancelSubscriptionError}</p>}
        <div className="edit-dialog-actions">
          <button
            type="button"
            className="cancel-subscription-button"
            disabled={savingCancelSubscription}
            onClick={() => void cancelVirtualPOSSubscription()}
          >
            {savingCancelSubscription ? "Cancelando..." : "Confirmar cancelación"}
          </button>
          <button type="button" className="cancel-button" onClick={() => { setCancelingSubscription(null); setCancelSubscriptionError(null); }}>
            Volver
          </button>
        </div>
      </section>
    </div>
  ) : null}
    {cancelingCharge ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Cancelar cargo VirtualPOS">
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">VIRTUALPOS / CARGO</p>
              <h3>Cancelar cargo</h3>
            </div>
            <span>{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</span>
          </div>
          <p className="edit-dialog-note">
            Se enviará DELETE <code>/v3/charge/{text(cancelingCharge.payload.id, cancelingCharge.external_id)}</code> a VirtualPOS.
            Solo cargos en estado <strong>pendiente</strong> pueden cancelarse. Esta acción no se puede deshacer.
          </p>
          {cancelChargeError ? <p className="error-message form-error">{cancelChargeError}</p> : null}
          <div className="edit-dialog-actions">
            <button
              type="button"
              className="cancel-subscription-button"
              disabled={savingCancelCharge}
              onClick={() => void cancelVirtualPOSCharge()}
            >
              {savingCancelCharge ? "Cancelando..." : "Confirmar cancelación"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setCancelingCharge(null)}>
              Volver
            </button>
          </div>
        </section>
      </div>
    ) : null}
    {retryingCharge ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <section className="edit-dialog" role="dialog" aria-modal="true" aria-label="Reintentar cargo VirtualPOS">
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">VIRTUALPOS / CARGO</p>
              <h3>Reintentar cargo</h3>
            </div>
            <span>{text(retryingCharge.payload.id, retryingCharge.external_id)}</span>
          </div>
          <p className="edit-dialog-note">
            Se enviará GET <code>/v3/charge/{text(retryingCharge.payload.id, retryingCharge.external_id)}/retry</code> a VirtualPOS.
            Solo cargos en estado <strong>rechazado</strong> pueden reintentarse (máximo una vez diaria durante tres días consecutivos).
          </p>
          {retryChargeError ? <p className="error-message form-error">{retryChargeError}</p> : null}
          <div className="edit-dialog-actions">
            <button
              type="button"
              className="retry-charge-button"
              disabled={savingRetryCharge}
              onClick={() => void retryVirtualPOSCharge()}
            >
              {savingRetryCharge ? "Reintentando..." : "Confirmar reintento"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setRetryingCharge(null)}>
              Volver
            </button>
          </div>
        </section>
      </div>
    ) : null}
    {creatingCharge ? (
      <div className="edit-dialog-backdrop" role="presentation">
        <form
          className="edit-dialog"
          aria-modal="true"
          aria-label="Crear cargo VirtualPOS"
          noValidate
          onSubmit={createVirtualPOSCharge}
        >
          <div className="edit-dialog-heading">
            <div>
              <p className="eyebrow">VIRTUALPOS / CARGO</p>
              <h3>Nuevo cargo</h3>
            </div>
            <span className="edit-dialog-subtitle">Sub: {text(creatingCharge.payload.id, creatingCharge.external_id)}</span>
          </div>
          <p className="edit-dialog-note">
            Los campos marcados con * son obligatorios. La fecha del cargo no puede ser pasada.
          </p>
          <div className="edit-form-grid">
            <label className={chargeFieldErrors.charge_date ? "field-error" : ""}>
              Fecha del cargo<span className="field-required" aria-hidden="true"> *</span>
              <input
                name="charge_date"
                type="date"
                aria-required="true"
                aria-invalid={Boolean(chargeFieldErrors.charge_date)}
                min={new Date().toISOString().split("T")[0]}
              />
              {chargeFieldErrors.charge_date ? <span className="field-error-message">{chargeFieldErrors.charge_date}</span> : null}
            </label>
            <label className={chargeFieldErrors.amount ? "field-error" : ""}>
              Monto<span className="field-required" aria-hidden="true"> *</span>
              <input
                name="amount"
                type="number"
                min="1"
                step="1"
                placeholder="Ej: 9990"
                aria-required="true"
                aria-invalid={Boolean(chargeFieldErrors.amount)}
              />
              {chargeFieldErrors.amount ? <span className="field-error-message">{chargeFieldErrors.amount}</span> : null}
            </label>
            <label>
              Descripción
              <input name="description" type="text" placeholder="Ej: Cuota agosto 2026" />
            </label>
            <label>
              Código interno
              <input name="internal_code" type="text" placeholder="Ej: AGO2026" />
            </label>
          </div>
          {chargeFormError ? <p className="error-message form-error">{chargeFormError}</p> : null}
          <div className="edit-dialog-actions">
            <button type="submit" className="save-button" disabled={savingCharge}>
              {savingCharge ? "Creando..." : "Crear cargo"}
            </button>
            <button type="button" className="cancel-button" onClick={() => setCreatingCharge(null)}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    ) : null}
    </>
  );
}
