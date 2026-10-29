import type { ProviderSource } from "../../routes";
import type { StagingRecord, VirtualPosPlanDetail } from "../shared/types";
import { label } from "../../i18n/label";
import { fieldValue } from "../shared/display";
import { text, fieldLabel, externalUrl } from "../shared/utils";
import { virtualPosPlanFields } from "./constants";
import { virtualPosClientName } from "./columns";
import { VirtualPosDetailTable } from "./VirtualPosDetailTable";

/** Ficha de un plan de VirtualPOS con sus suscripciones. */
export function PlanDetailView({
  detail: planDetail,
  showResourceList,
  openVirtualPosSubscription,
}: {
  detail: VirtualPosPlanDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openVirtualPosSubscription: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
}) {
  return (
  <main className="app-shell detail-page">
    <button className="back-button" onClick={() => showResourceList("virtualpos", "plan")}>
      Volver a planes VirtualPOS
    </button>
    <p className="eyebrow">VIRTUALPOS / PLAN</p>
    <h2>{text(planDetail.plan.payload.name, planDetail.plan.external_id)}</h2>
    <section className="panel">
      <p className="eyebrow">FICHA DEL PLAN</p>
      <dl className="field-list">
        {virtualPosPlanFields.map((field) => (
          <div key={field}>
            <dt>{fieldLabel(field)}</dt>
            <dd>
              {field === "id"
                ? text(
                    planDetail.plan.payload.id,
                    planDetail.plan.external_id,
                  )
                : (field === "return_url" || field === "suscription_url") && externalUrl(planDetail.plan.payload[field])
                  ? <a className="record-link" href={externalUrl(planDetail.plan.payload[field]) ?? undefined} target="_blank" rel="noreferrer">Abrir enlace</a>
                  : fieldValue(field, planDetail.plan.payload[field])}
            </dd>
          </div>
        ))}
      </dl>
    </section>
    <section className="panel client-subscriptions">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">SUBSCRIPCIONES VIRTUALPOS</p>
          <h3>Asociadas al plan</h3>
        </div>
        <span>{planDetail.subscription_total} total</span>
      </div>
      <VirtualPosDetailTable records={planDetail.subscriptions} empty="Sin suscripciones asociadas al plan." columns={[
        { label: "ID suscripción", value: (record) => text(record.payload.id, record.external_id), render: (record) => <button className="record-link" onClick={() => void openVirtualPosSubscription(record)}>{text(record.payload.id, record.external_id)}</button> },
        { label: "Nombre cliente", value: virtualPosClientName },
        { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
        { label: "Estado", value: (record) => label("status", record.payload.status) },
      ]} />
    </section>
  </main>
  );
}
