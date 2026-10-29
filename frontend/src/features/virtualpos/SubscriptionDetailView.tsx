import type { ProviderSource } from "../../routes";
import type { StagingRecord, VirtualPosSubscriptionDetail } from "../shared/types";
import { text, nested, objectEntries, fieldLabel, renewalText, cardTypeText, isActiveSubscription, isPendingCharge, isRejectedCharge } from "../shared/utils";
import { virtualPosSubscriptionFields } from "./constants";
import { VirtualPosDetailTable } from "./VirtualPosDetailTable";

/** Ficha de una suscripción de VirtualPOS: datos, método de pago, cargos y transacciones. */
export function SubscriptionDetailView({
  detail: subscriptionDetail,
  showResourceList,
  openVirtualPosPlan,
  openVirtualPosCharge,
  openVirtualPosPayment,
  onCancelSubscription,
  onNewCharge,
  onCancelCharge,
  onRetryCharge,
  can,
  chargeSaveNotice,
}: {
  detail: VirtualPosSubscriptionDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openVirtualPosPlan: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosCharge: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosPayment: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onCancelSubscription: (record: StagingRecord) => void;
  onNewCharge: (record: StagingRecord) => void;
  onCancelCharge: (record: StagingRecord) => void;
  onRetryCharge: (record: StagingRecord) => void;
  can: (permission: string) => boolean;
  chargeSaveNotice: string | null;
}) {
  return (
  <main className="app-shell detail-page">
    <button
      className="back-button"
      onClick={() => showResourceList("virtualpos", "subscription")}
    >
      Volver al listado VirtualPOS
    </button>
    <p className="eyebrow">VIRTUALPOS / SUBSCRIPCIÓN</p>
    <h2>
      {text(
        subscriptionDetail.subscription.payload.plan_name,
        subscriptionDetail.subscription.external_id,
      )}
    </h2>
    {isActiveSubscription(subscriptionDetail.subscription) ? (
      <div className="client-detail-actions">
        <button
          className="cancel-subscription-button"
          onClick={() => onCancelSubscription(subscriptionDetail.subscription)}
        >
          Cancelar Sub
        </button>
        <button
          className="create-charge-button"
          onClick={() => onNewCharge(subscriptionDetail.subscription)}
        >
          + Nuevo cargo
        </button>
      </div>
    ) : null}
    {chargeSaveNotice ? <p className="save-notice">{chargeSaveNotice}</p> : null}
    <section className="panel">
      <p className="eyebrow">FICHA DE LA SUBSCRIPCIÓN</p>
      <dl className="field-list">
        {virtualPosSubscriptionFields.map((field) => (
          <div key={field}>
            <dt>{fieldLabel(field)}</dt>
            <dd>
              {field === "secondary_status"
                ? <span className={`badge badge-${subscriptionDetail.subscription.secondary_status === "cobrable" ? "green" : subscriptionDetail.subscription.secondary_status === "incobrable" ? "orange" : subscriptionDetail.subscription.secondary_status === "inactiva" ? "gray" : "blue"}`}>{subscriptionDetail.subscription.secondary_status ?? "—"}</span>
                : field === "last_paid_date"
                  ? (subscriptionDetail.subscription.last_paid_date ? String(subscriptionDetail.subscription.last_paid_date).slice(0, 10) : "—")
                : field === "id"
                ? text(
                    subscriptionDetail.subscription.payload.id,
                    subscriptionDetail.subscription.external_id,
                  )
                : field === "plan_name" && subscriptionDetail.subscription.payload.plan_id
                  ? <button className="record-link" onClick={() => void openVirtualPosPlan({ external_id: String(subscriptionDetail.subscription.payload.plan_id) })}>{text(subscriptionDetail.subscription.payload[field])}</button>
                  : field === "renewal"
                    ? renewalText(subscriptionDetail.subscription.payload[field])
                    : text(subscriptionDetail.subscription.payload[field])}
            </dd>
          </div>
        ))}
      </dl>
    </section>
    <section className="panel client-subscriptions">
      <p className="eyebrow">MÉTODO DE PAGO</p>
      {objectEntries(subscriptionDetail.payment_method).length ? (
        <dl className="field-list">
          {objectEntries(subscriptionDetail.payment_method).filter(([field]) => !["bin", "last4carddigit", "last4"].includes(field.toLowerCase())).map(
            ([field, value]) => (
              <div key={field}>
                <dt>{fieldLabel(field)}</dt>
                <dd>{field === "card_type" ? cardTypeText(value) : text(value)}</dd>
              </div>
            ),
          )}
        </dl>
      ) : (
        <p>Sin método de pago disponible en staging.</p>
      )}
    </section>
    <section className="panel client-subscriptions">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CARGOS</p>
          <h3>Asociados a la subscripción</h3>
        </div>
        <span>{subscriptionDetail.charge_total} total</span>
      </div>
      <VirtualPosDetailTable records={subscriptionDetail.charges} empty="Sin cargos asociados a la subscripción." columns={[
        { label: "Fecha de cargo", kind: "date", value: (record) => text(record.payload.charge_date, "") },
        { label: "ID Cargo", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosCharge(record)}>{text(record.payload.id, record.external_id)}</button> },
        { label: "Estado", value: (record) => text(record.payload.status) },
        { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
        { label: "Acción", filterable: false, value: () => "", render: (record) => isPendingCharge(record) && can("virtualpos.charges.cancel") ? <button className="cancel-charge-button" onClick={() => onCancelCharge(record)}>Cancelar</button> : isRejectedCharge(record) && can("virtualpos.charges.retry") ? <button className="retry-charge-button" onClick={() => onRetryCharge(record)}>Reintentar</button> : null },
      ]} />
    </section>
    <section className="panel client-subscriptions">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">TRANSACCIONES DEL CLIENTE</p>
          <h3>Disponibles por RUT en la misma cuenta</h3>
        </div>
        <span>{subscriptionDetail.payment_total} total</span>
      </div>
      <p className="field-hint">VirtualPOS no entrega un identificador de subscripción en las transacciones, por lo que esta tabla no las asigna individualmente.</p>
      <VirtualPosDetailTable records={subscriptionDetail.payments} empty="Sin transacciones disponibles para este cliente." columns={[
        { label: "Fecha autorización", kind: "date", value: (record) => text(nested(record.payload, "order", "authorized_at"), "") },
        { label: "ID Transacción", value: (record) => record.external_id, render: (record) => <button className="record-link" onClick={() => void openVirtualPosPayment(record)}>{record.external_id}</button> },
        { label: "Estado", value: (record) => text(nested(record.payload, "order", "status")) },
        { label: "Monto", kind: "amount", value: (record) => text(nested(record.payload, "order", "amount"), "0") },
      ]} />
    </section>
  </main>
  );
}
