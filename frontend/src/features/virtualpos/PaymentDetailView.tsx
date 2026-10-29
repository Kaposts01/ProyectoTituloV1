import type { ProviderSource } from "../../routes";
import type { StagingRecord, VirtualPosPaymentDetail } from "../shared/types";
import { fieldValue } from "../shared/display";
import { text, nested, objectEntries, fieldLabel } from "../shared/utils";
import { vpClientRecordName } from "./columns";

/** Ficha de una transacción de VirtualPOS con sus relaciones. */
export function PaymentDetailView({
  detail: paymentDetail,
  showResourceList,
  openVirtualPosClient,
  openVirtualPosSubscription,
  openVirtualPosCharge,
  onDelete,
}: {
  detail: VirtualPosPaymentDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openVirtualPosClient: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosSubscription: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosCharge: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onDelete: (record: StagingRecord) => void;
}) {
  return (
  <main className="app-shell detail-page">
    <button className="back-button" onClick={() => showResourceList("virtualpos", "payment")}>
      Volver a transacciones VirtualPOS
    </button>
    <p className="eyebrow">VIRTUALPOS / TRANSACCIÓN</p>
    <h2>{text(nested(paymentDetail.payment.payload, "order", "uuid"), paymentDetail.payment.external_id)}</h2>
    <div className="client-detail-actions">
      <button
        className="delete-button"
        onClick={() => onDelete(paymentDetail.payment)}
      >
        Eliminar
      </button>
    </div>
    <section className="panel">
      <p className="eyebrow">FICHA DE LA TRANSACCIÓN</p>
      <dl className="field-list">
        {Object.entries(paymentDetail.payment.payload).flatMap(([field, value]) => {
          if ((field === "order" || field === "client") && objectEntries(value).length) {
            return objectEntries(value).map(([nestedField, nestedValue]) => (
              <div key={`${field}-${nestedField}`}>
                <dt>{fieldLabel(field)} {fieldLabel(nestedField)}</dt>
                <dd>{fieldValue(nestedField, nestedValue)}</dd>
              </div>
            ));
          }
          return [
            <div key={field}>
              <dt>{fieldLabel(field)}</dt>
              <dd>{fieldValue(field, value)}</dd>
            </div>,
          ];
        })}
      </dl>
    </section>
    <section className="panel">
      <p className="eyebrow">RELACIONES</p>
      <dl className="field-list">
        <div><dt>Cliente</dt><dd>{paymentDetail.client ? <button className="record-link" onClick={() => void openVirtualPosClient(paymentDetail.client!)}>{vpClientRecordName(paymentDetail.client)}</button> : "Sin cliente relacionado"}</dd></div>
        <div><dt>RUT cliente</dt><dd>{paymentDetail.client ? text(paymentDetail.client.payload.social_id) : "—"}</dd></div>
        <div><dt>Suscripción</dt><dd>{paymentDetail.subscription ? <button className="record-link" onClick={() => void openVirtualPosSubscription(paymentDetail.subscription!)}>{paymentDetail.subscription.plan_name ?? paymentDetail.subscription.external_id}</button> : "Sin suscripción relacionada"}</dd></div>
        <div><dt>Cargo</dt><dd>{paymentDetail.charge ? <button className="record-link" onClick={() => void openVirtualPosCharge(paymentDetail.charge!)}>{text(paymentDetail.charge.payload.id, paymentDetail.charge.external_id)}</button> : "Sin cargo relacionado"}</dd></div>
      </dl>
    </section>
  </main>
  );
}
