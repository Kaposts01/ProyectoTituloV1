import type { ProviderSource } from "../../routes";
import type { StagingRecord, VirtualPosChargeDetail } from "../shared/types";
import { fieldValue } from "../shared/display";
import { text, fieldLabel, isPendingCharge, isRejectedCharge } from "../shared/utils";
import { vpClientRecordName } from "./columns";

/** Ficha de un cargo de VirtualPOS con sus relaciones. */
export function ChargeDetailView({
  detail: chargeDetail,
  showResourceList,
  openVirtualPosClient,
  openVirtualPosSubscription,
  openVirtualPosPayment,
  onCancelCharge,
  onRetryCharge,
  can,
}: {
  detail: VirtualPosChargeDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openVirtualPosClient: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosSubscription: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosPayment: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onCancelCharge: (record: StagingRecord) => void;
  onRetryCharge: (record: StagingRecord) => void;
  can: (permission: string) => boolean;
}) {
  return (
  <main className="app-shell detail-page">
    <button className="back-button" onClick={() => showResourceList("virtualpos", "charge")}>
      Volver a cargos VirtualPOS
    </button>
    <p className="eyebrow">VIRTUALPOS / CARGO</p>
    <h2>{text(chargeDetail.charge.payload.id, chargeDetail.charge.external_id)}</h2>
    <div className="client-detail-actions">
      {isPendingCharge(chargeDetail.charge) ? (
        <button
          className="cancel-charge-button"
          onClick={() => onCancelCharge(chargeDetail.charge)}
        >
          Cancelar en VP
        </button>
      ) : null}
      {isRejectedCharge(chargeDetail.charge) && can("virtualpos.charges.retry") ? (
        <button
          className="retry-charge-button"
          onClick={() => onRetryCharge(chargeDetail.charge)}
        >
          Reintentar en VP
        </button>
      ) : null}
    </div>
    <section className="panel">
      <p className="eyebrow">FICHA DEL CARGO</p>
      <dl className="field-list">
        {Object.entries(chargeDetail.charge.payload).map(([field, value]) => (
          <div key={field}>
            <dt>{fieldLabel(field)}</dt>
            <dd>{fieldValue(field, value)}</dd>
          </div>
        ))}
      </dl>
    </section>
    <section className="panel">
      <p className="eyebrow">RELACIONES</p>
      <dl className="field-list">
        <div><dt>Cliente</dt><dd>{chargeDetail.client ? <button className="record-link" onClick={() => void openVirtualPosClient(chargeDetail.client!)}>{vpClientRecordName(chargeDetail.client)}</button> : "Sin cliente relacionado"}</dd></div>
        <div><dt>RUT cliente</dt><dd>{chargeDetail.client ? text(chargeDetail.client.payload.social_id) : "—"}</dd></div>
        <div><dt>Subscripción</dt><dd>{chargeDetail.subscription ? <button className="record-link" onClick={() => void openVirtualPosSubscription(chargeDetail.subscription!)}>{chargeDetail.subscription.plan_name ?? chargeDetail.subscription.external_id}</button> : "Sin subscripción relacionada"}</dd></div>
        <div><dt>Transacción</dt><dd>{chargeDetail.payment ? <button className="record-link" onClick={() => void openVirtualPosPayment(chargeDetail.payment!)}>{chargeDetail.payment.external_id}</button> : "Sin transacción relacionada"}</dd></div>
      </dl>
    </section>
  </main>
  );
}
