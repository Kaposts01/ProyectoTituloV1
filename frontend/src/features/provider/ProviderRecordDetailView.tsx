import type { ProviderSource } from "../../routes";
import type { StagingRecord, ProviderRecordDetail } from "../shared/types";
import { fieldValue } from "../shared/display";
import { text, objectEntries, fieldLabel, providerRecordHeading, title, resourceTitle } from "../shared/utils";
import { recurringFieldLabels, providerEditFields, deletableResources } from "../virtualpos/constants";
import { tokuRelatedColumns } from "../virtualpos/columns";
import { TokuPaymentMethodProfile } from "../toku/TokuPaymentMethodProfile";

/** Ficha genérica de un registro de Toku o Payku con sus registros relacionados. */
export function ProviderRecordDetailView({
  detail: providerRecordDetail,
  showResourceList,
  openProviderRecord,
  onEditRecord,
  onManageTokuSubscription,
  onDeleteRecord,
}: {
  detail: ProviderRecordDetail;
  showResourceList: (source: ProviderSource, resource: string) => void;
  openProviderRecord: (source: ProviderSource, resource: string, record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onEditRecord: (record: StagingRecord, source: string, resourceType: string) => void;
  onManageTokuSubscription: (record: StagingRecord) => void;
  onDeleteRecord: (record: StagingRecord, source: string, resourceType: string) => void;
}) {
  return (
  <main className="app-shell detail-page">
    <button
      className="back-button"
      onClick={() => showResourceList(providerRecordDetail.record.source as ProviderSource, providerRecordDetail.record.resource_type)}
    >
      Volver al listado {title(providerRecordDetail.record.source)}
    </button>
    <p className="eyebrow">
      {title(providerRecordDetail.record.source).toUpperCase()} /{" "}
      {resourceTitle(providerRecordDetail.record.resource_type).toUpperCase()}
    </p>
    <h2>{providerRecordHeading(providerRecordDetail.record)}</h2>
    <div className="client-detail-actions">
      {(providerEditFields[providerRecordDetail.record.source]?.[providerRecordDetail.record.resource_type] ?? []).length > 0 ? (
        <button
          className="edit-button"
          onClick={() => onEditRecord(providerRecordDetail.record, providerRecordDetail.record.source, providerRecordDetail.record.resource_type)}
        >
          Editar
        </button>
      ) : null}
      {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "subscription" ? (
        <button
          className="edit-button"
          onClick={() => onManageTokuSubscription(providerRecordDetail.record)}
        >
          Gestionar estado
        </button>
      ) : null}
      {(deletableResources[providerRecordDetail.record.source] ?? []).includes(providerRecordDetail.record.resource_type) ? (
        <button
          className="delete-button"
          onClick={() => onDeleteRecord(providerRecordDetail.record, providerRecordDetail.record.source, providerRecordDetail.record.resource_type)}
        >
          Eliminar
        </button>
      ) : null}
    </div>
    {providerRecordDetail.record.source === "toku" && providerRecordDetail.record.resource_type === "payment_method" ? (
      <TokuPaymentMethodProfile payload={providerRecordDetail.record.payload} />
    ) : (
      <section className="panel">
        <p className="eyebrow">FICHA COMPLETA</p>
        <dl className="field-list">
          {Object.entries(providerRecordDetail.record.payload).flatMap(
            ([field, value]) => {
              const entries = objectEntries(value);
              if (entries.length) {
                return entries.map(([subField, subValue]) => (
                  <div key={`${field}-${subField}`}>
                    <dt>
                      {field === "recurring"
                        ? `Recurrencia ${recurringFieldLabels[subField] ?? fieldLabel(subField)}`
                        : `${fieldLabel(field)} — ${fieldLabel(subField)}`}
                    </dt>
                    <dd>{fieldValue(subField, subValue)}</dd>
                  </div>
                ));
              }
              return [
                <div key={field}>
                  <dt>{fieldLabel(field)}</dt>
                  <dd>{fieldValue(field, value)}</dd>
                </div>,
              ];
            },
          )}
        </dl>
      </section>
    )}
    {providerRecordDetail.related.map((group) => (
      <section
        className="panel client-subscriptions"
        key={group.resource_type}
      >
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{group.label.toUpperCase()}</p>
            <h3>Registros relacionados</h3>
          </div>
          <span>{group.items.length} total</span>
        </div>
        {group.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  {tokuRelatedColumns(group.resource_type).map((column) => (
                    <th key={column.label}>{column.label}</th>
                  ))}
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {group.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <button
                        className="record-link"
                        onClick={() =>
                          void openProviderRecord(
                            item.source as ProviderSource,
                            group.resource_type,
                            item,
                          )
                        }
                      >
                        {text(item.payload.id, item.external_id)}
                      </button>
                    </td>
                    {tokuRelatedColumns(group.resource_type).map((column) => (
                      <td key={column.label}>{column.value(item)}</td>
                    ))}
                    <td className="action-cell">
                      {item.source === "toku" && group.resource_type === "subscription" ? (
                        <button
                          className="edit-button"
                          onClick={() => onManageTokuSubscription(item)}
                        >
                          Gestionar estado
                        </button>
                      ) : null}
                      {(providerEditFields[item.source]?.[group.resource_type] ?? []).length > 0 && !(item.source === "toku" && group.resource_type === "subscription") ? (
                        <button
                          className="edit-button"
                          onClick={() => onEditRecord(item, item.source, group.resource_type)}
                        >
                          Editar
                        </button>
                      ) : null}
                      {(deletableResources[item.source] ?? []).includes(group.resource_type) && !(item.source === "toku" && group.resource_type === "subscription") ? (
                        <button
                          className="delete-button"
                          onClick={() => onDeleteRecord(item, item.source, group.resource_type)}
                        >
                          Eliminar
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Sin registros relacionados.</p>
        )}
      </section>
    ))}
  </main>
  );
}
