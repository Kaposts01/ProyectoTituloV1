import { useEffect, useRef } from "react";
import { useDirectCancel } from "../cancellations/directCancel";
import { DirectCancelNote } from "../cancellations/DirectCancelNote";
import type { ProviderSource } from "../../routes";
import type { StagingRecord, VirtualPosClientDetail } from "../shared/types";
import { label, labelOr } from "../../i18n/label";
import { fieldValue } from "../shared/display";
import { text, nested, isActiveSubscription } from "../shared/utils";
import { virtualPosClientFields, virtualPosClientFieldLabels, virtualPosDocumentTypes } from "./constants";
import { VirtualPosDetailTable } from "./VirtualPosDetailTable";

/** Ficha de un cliente de VirtualPOS con sus suscripciones, cargos y transacciones. */
export function ClientDetailView({
  detail: clientDetail,
  showResourceList,
  openVirtualPosSubscription,
  openVirtualPosCharge,
  openVirtualPosPayment,
  onEdit,
  onCancelSubscription,
  can,
}: {
  detail: VirtualPosClientDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openVirtualPosSubscription: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosCharge: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosPayment: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onEdit: (record: StagingRecord) => void;
  onCancelSubscription: (record: StagingRecord) => void;
  can: (permission: string) => boolean;
}) {
  const { isAdmin } = useDirectCancel();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [clientDetail.client.external_id]);
  const clientName = `${text(clientDetail.client.payload.first_name, "")} ${text(clientDetail.client.payload.last_name, "")}`.trim() || "Cliente sin nombre informado";
  return (
  <main className="app-shell detail-page">
    <button className="back-button" onClick={() => showResourceList("virtualpos", "client")}>
      Volver a clientes VirtualPOS
    </button>
    <p className="eyebrow">VIRTUALPOS / CLIENTE</p>
    <h1 ref={heading} tabIndex={-1}>{clientName}</h1>
    <p className="muted-copy">{clientDetail.client.source === "virtualpos1" ? "VP 1" : clientDetail.client.source === "virtualpos2" ? "VP 2" : "VirtualPOS"} · ID {clientDetail.client.external_id}</p>
    {can("virtualpos.clients.update") ? <div className="client-detail-actions">
      <button className="edit-button" onClick={() => onEdit(clientDetail.client)}>
        Editar cliente
      </button>
    </div> : null}
    <section className="panel">
      <p className="eyebrow">FICHA DEL CLIENTE</p>
      <dl className="field-list">
        {virtualPosClientFields.map((field) => (
          <div key={field}>
            <dt>{virtualPosClientFieldLabels[field]}</dt>
            <dd>
              {field === "uuid"
                ? text(
                    clientDetail.client.payload.uuid,
                    clientDetail.client.external_id,
                  )
                : field === "social_id_type"
                  ? (virtualPosDocumentTypes[text(clientDetail.client.payload[field], "")] ?? text(clientDetail.client.payload[field]))
                : field === "type" && clientDetail.client.payload.type
                  ? label("personType", clientDetail.client.payload.type)
                  : fieldValue(field, clientDetail.client.payload[field])}
            </dd>
          </div>
        ))}
      </dl>
    </section>
    <section className="panel client-subscriptions">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">SUSCRIPCIONES VIRTUALPOS</p>
          <h3>Relacionadas por RUT</h3>
        </div>
        <span>{clientDetail.subscription_total} total</span>
      </div>
      <VirtualPosDetailTable records={clientDetail.subscriptions} empty="Sin suscripciones asociadas por RUT." columns={[
        { label: "ID suscripción", value: (record) => text(record.payload.id, record.external_id), render: (record) => can("virtualpos.subscriptions.view") ? <button className="record-link" onClick={() => void openVirtualPosSubscription(record)}>{text(record.payload.id, record.external_id)}</button> : text(record.payload.id, record.external_id) },
        { label: "Estado", value: (record) => label("status", record.payload.status) },
        { label: "Estado sec.", value: (record) => labelOr("secondaryStatus", record.secondary_status, "—") },
        { label: "Último cobro", kind: "date", value: (record) => record.last_paid_date ? String(record.last_paid_date).slice(0, 10) : "" },
        { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
        { label: "F. Inicio", kind: "date", value: (record) => text(record.payload.suscription_date, "") },
        { label: "Acción", filterable: false, value: () => "", render: (record) => isActiveSubscription(record) && can("virtualpos.subscriptions.cancel") ? (isAdmin ? <button className="cancel-subscription-button" onClick={() => onCancelSubscription(record)}>Cancelar</button> : <DirectCancelNote compact />) : null },
      ]} />
    </section>
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CARGOS</p>
          <h3>Cobros generados por suscripción</h3>
        </div>
        <span>{clientDetail.charge_total} total{clientDetail.charge_total > 100 ? " · mostrando últimos 100" : ""}</span>
      </div>
      <VirtualPosDetailTable records={clientDetail.charges} empty="Sin cargos registrados para este cliente." columns={[
        { label: "Fecha", kind: "date", value: (record) => text(record.payload.charge_date, "") },
        { label: "ID Cargo", value: (record) => text(record.payload.id, record.external_id), render: (record) => can("virtualpos.charges.view") ? <button className="record-link" onClick={() => void openVirtualPosCharge(record)}>{text(record.payload.id, record.external_id)}</button> : text(record.payload.id, record.external_id) },
        { label: "Plan", value: (record) => record.plan_name ?? "", render: (record) => record.subscription_id && can("virtualpos.subscriptions.view") ? <button className="record-link" onClick={() => void openVirtualPosSubscription({ external_id: record.subscription_id! })}>{record.plan_name ?? "Sin plan"}</button> : record.plan_name ?? "Sin plan" },
        { label: "Estado", value: (record) => label("status", record.payload.status) },
        { label: "Monto", kind: "amount", value: (record) => text(record.payload.amount, "0") },
      ]} />
    </section>
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">TRANSACCIONES</p>
          <h3>Pagos procesados</h3>
        </div>
        <span>{clientDetail.payment_total} total</span>
      </div>
      <VirtualPosDetailTable records={clientDetail.payments} empty="Sin transacciones procesadas para este cliente." columns={[
        { label: "Fecha autorización", kind: "date", value: (record) => text(nested(record.payload, "order", "authorized_at"), "") },
        { label: "ID Transacción", value: (record) => record.external_id, render: (record) => can("virtualpos.payments.view") ? <button className="record-link" onClick={() => void openVirtualPosPayment(record)}>{record.external_id}</button> : record.external_id },
        { label: "Estado", value: (record) => label("status", nested(record.payload, "order", "status")) },
        { label: "Monto bruto", kind: "amount", value: (record) => text(nested(record.payload, "order", "amount"), "0") },
        { label: "Abono neto", kind: "amount", value: (record) => { const order = record.payload.order as Record<string, unknown> | undefined; const deposit = Array.isArray(order?.deposits) ? order.deposits[0] as Record<string, unknown> : undefined; return text(deposit?.payout_amount, "0"); } },
        { label: "Tipo", value: (record) => labelOr("paymentType", nested(record.payload, "order", "payment_type_code"), "") },
      ]} />
    </section>
  </main>
  );
}
