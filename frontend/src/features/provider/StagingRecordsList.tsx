import type { ProviderSection, ProviderSource } from "../../routes";
import type { StagingRecord, TableColumn } from "../shared/types";
import { RECORDS_PAGE_SIZE, isActiveSubscription, isPendingCharge, isRejectedCharge, title } from "../shared/utils";
import { filterFieldForColumn, stagingFilters, providerEditFields, virtualPosFieldForColumn } from "../virtualpos/constants";
import { virtualPosColumns, tokuColumns, paykuColumns } from "../virtualpos/columns";
import type { StagingRecordsState } from "./useStagingRecords";

/**
 * Lista de registros de staging de una sección (VirtualPOS, Toku o Payku): filtros, tabla con columnas
 * por recurso, acciones por fila y «Ver más». El estado vive en `useStagingRecords` (AppCore).
 */
export function StagingRecordsList({
  activeSection,
  list,
  loading,
  error,
  vp2Enabled,
  can,
  notices,
  showChannel,
  openVirtualPosClient,
  openVirtualPosPlan,
  openVirtualPosSubscription,
  openVirtualPosPayment,
  openProviderRecord,
  onNewClient,
  onNewPlan,
  onNewSubscription,
  onEditClient,
  onCancelSubscription,
  onNewCharge,
  onCancelCharge,
  onRetryCharge,
  onEditRecord,
  onDeleteRecord,
}: {
  activeSection: ProviderSection;
  list: StagingRecordsState;
  loading: boolean;
  error: string | null;
  vp2Enabled: boolean;
  can: (permission: string) => boolean;
  notices: { client: string | null; plan: string | null; subscription: string | null; charge: string | null };
  showChannel: (source: ProviderSource) => void;
  openVirtualPosClient: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosPlan: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosSubscription: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openVirtualPosPayment: (record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  openProviderRecord: (source: ProviderSource, resource: string, record: Pick<StagingRecord, "external_id">) => void | Promise<void>;
  onNewClient: () => void;
  onNewPlan: () => void;
  onNewSubscription: () => void;
  onEditClient: (record: StagingRecord) => void;
  onCancelSubscription: (record: StagingRecord) => void;
  onNewCharge: (record: StagingRecord) => void;
  onCancelCharge: (record: StagingRecord) => void;
  onRetryCharge: (record: StagingRecord) => void;
  onEditRecord: (record: StagingRecord, source: string, resourceType: string) => void;
  onDeleteRecord: (record: StagingRecord, source: string, resourceType: string) => void;
}) {
  const {
    records,
    setRecordsOffset,
    statusValues,
    filterField,
    setFilterField,
    filterQuery,
    setFilterQuery,
    vpColumnFilters,
    setVpColumnFilters,
    sortColumn,
    setSortColumn,
    sortDirection,
    setSortDirection,
    vpPlatform,
    setVpPlatform,
  } = list;
  const { client: clientSaveNotice, plan: planSaveNotice, subscription: subscriptionSaveNotice, charge: chargeSaveNotice } = notices;
  const columns: TableColumn[] =
    activeSection?.source === "virtualpos"
      ? virtualPosColumns(activeSection.resource)
      : activeSection?.source === "toku"
        ? tokuColumns(activeSection.resource)
        : activeSection?.source === "payku"
          ? paykuColumns(activeSection.resource)
          : [];
  function toggleColumnSort(column: TableColumn) {
    if (!activeSection || !filterFieldForColumn(activeSection.source, activeSection.resource, column.label)) return;
    if (sortColumn === column.label) {
      setRecordsOffset(0);
      setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
      return;
    }
    setRecordsOffset(0);
    setSortColumn(column.label);
    setSortDirection("asc");
  }
  const filterOptions = activeSection
    ? (stagingFilters[activeSection.source]?.[activeSection.resource] ?? [])
    : [];
  const availableStatuses = ["status", "secondary_status"].includes(filterField) ? statusValues : [];
  const isStatusFilter = ["status", "secondary_status"].includes(filterField);
  const filterControls = activeSection?.source === "virtualpos" ? null : filterOptions.length ? (
    <section
      className="record-filters"
      aria-label={`Filtros ${activeSection?.label}`}
    >
      <div className="record-filters-copy">
        <p className="eyebrow">BÚSQUEDA</p>
        <strong>Filtrar registros</strong>
      </div>
      <label>
        Campo
        <select
          value={filterField}
          onChange={(event) => {
            setFilterField(event.target.value);
            setFilterQuery("");
            setRecordsOffset(0);
          }}
        >
          {filterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="record-filter-query">
        {isStatusFilter ? (filterField === "secondary_status" ? "Estado secundario" : "Estado") : "Buscar"}
        {isStatusFilter ? (
          <select
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
          >
            <option value="">Todos los estados</option>
            {availableStatuses.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        ) : (
          <input
            value={filterQuery}
            onChange={(event) => { setFilterQuery(event.target.value); setRecordsOffset(0); }}
            placeholder={`Buscar por ${filterOptions.find((option) => option.value === filterField)?.label ?? "campo"}`}
          />
        )}
      </label>
      <button
        className="clear-filter-button"
        disabled={!filterQuery && filterField === filterOptions[0]?.value}
        onClick={() => {
          setFilterField(filterOptions[0]?.value ?? "");
          setFilterQuery("");
          setRecordsOffset(0);
        }}
      >
        Restablecer
      </button>
    </section>
  ) : null;
  return (
    <main className="app-shell detail-page provider-page">
      <button
        className="back-button"
        onClick={() => showChannel(activeSection.source)}
      >
        Volver al resumen {title(activeSection.source)}
      </button>
      <p className="eyebrow">
        {title(activeSection.source).toUpperCase()} / STAGING
      </p>
      <h2>{activeSection.label}</h2>
      {filterControls}
      {activeSection.source === "virtualpos" ? (
        <div className="vp-platform-filter">
          {(["all", "virtualpos1", "virtualpos2"] as const).filter((p) => p !== "virtualpos2" || vp2Enabled).map((p) => (
            <button
              key={p}
              className={`vp-platform-btn${vpPlatform === p ? " active" : ""}`}
              onClick={() => { setVpPlatform(p); setRecordsOffset(0); }}
            >
              {p === "all" ? "Todas" : p === "virtualpos1" ? "VP 1" : "VP 2"}
            </button>
          ))}
          <button
            className="clear-filter-button"
            disabled={!Object.values(vpColumnFilters).some((value) => value.trim())}
            onClick={() => { setVpColumnFilters({}); setRecordsOffset(0); }}
          >
            Limpiar filtros
          </button>
        </div>
      ) : null}
      <section className="panel provider-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SOURCE RECORDS</p>
            <h3>Payloads saneados almacenados localmente</h3>
          </div>
          <span aria-live="polite">{loading ? "Cargando" : `${records.total} registros`}</span>
        </div>
        {activeSection.source === "virtualpos" && activeSection.resource === "client" ? (
          <button className="new-client-button" onClick={onNewClient}>+ Nuevo cliente</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "plan" ? (
          <button className="new-client-button" onClick={onNewPlan}>+ Nuevo plan</button>
        ) : null}
        {activeSection.source === "virtualpos" && activeSection.resource === "subscription" ? (
          <button className="new-client-button" onClick={onNewSubscription}>+ Nueva suscripción</button>
        ) : null}
        {clientSaveNotice ? <p className="success-message" role="status">{clientSaveNotice}</p> : null}
        {planSaveNotice ? <p className="success-message" role="status">{planSaveNotice}</p> : null}
        {subscriptionSaveNotice ? <p className="success-message" role="status">{subscriptionSaveNotice}</p> : null}
        {chargeSaveNotice ? <p className="success-message" role="status">{chargeSaveNotice}</p> : null}
        {error ? <p className="error-message">{error}</p> : null}
        {!loading && !error && records.items.length === 0 ? (
          <p>Sin registros sincronizados para este recurso.</p>
        ) : null}
        {records.items.length > 0 ? (
          <div className="table-wrap">
            <table>
                <thead>
                  <tr>
                  {columns.map((column) => {
                    const sortable = Boolean(activeSection && filterFieldForColumn(activeSection.source, activeSection.resource, column.label));
                    const activeSort = sortColumn === column.label;
                    return (
                      <th
                        key={column.label}
                        aria-sort={activeSort ? (sortDirection === "asc" ? "ascending" : "descending") : undefined}
                      >
                        {sortable ? (
                          <button
                            className={`table-sort-button${activeSort ? " active" : ""}`}
                            title={`Ordenar por ${column.label}${activeSort ? " en sentido inverso" : ""}`}
                            onClick={() => toggleColumnSort(column)}
                          >
                            {column.label}
                            <span className="table-sort-indicator" aria-hidden="true">
                              {activeSort ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
                            </span>
                          </button>
                        ) : column.label}
                      </th>
                    );
                  })}
                  </tr>
                  {activeSection.source === "virtualpos" ? (
                    <tr className="table-column-filters">
                      {columns.map((column) => {
                        const field = virtualPosFieldForColumn(activeSection.resource, column.label);
                        if (!field) return <th key={column.label} />;
                        const update = (key: string, value: string) => {
                          setVpColumnFilters((current) => ({ ...current, [key]: value }));
                          setRecordsOffset(0);
                        };
                        if (field === "amount") {
                          return <th key={column.label} className="range-filter"><input aria-label="Monto mínimo" type="number" value={vpColumnFilters.amount_min ?? ""} onChange={(event) => update("amount_min", event.target.value)} placeholder="Mín." /><input aria-label="Monto máximo" type="number" value={vpColumnFilters.amount_max ?? ""} onChange={(event) => update("amount_max", event.target.value)} placeholder="Máx." /></th>;
                        }
                        if (["suscription_date", "canceled_at", "charge_date", "authorized_at"].includes(field)) {
                          return <th key={column.label} className="range-filter"><input aria-label={`${column.label} desde`} type="date" value={vpColumnFilters.date_from ?? ""} onChange={(event) => update("date_from", event.target.value)} /><input aria-label={`${column.label} hasta`} type="date" value={vpColumnFilters.date_to ?? ""} onChange={(event) => update("date_to", event.target.value)} /></th>;
                        }
                        return <th key={column.label}><input aria-label={`Buscar por ${column.label}`} value={vpColumnFilters[field] ?? ""} onChange={(event) => update(field, event.target.value)} placeholder="Buscar" /></th>;
                      })}
                    </tr>
                  ) : null}
                </thead>
              <tbody>
                {records.items.map((record) => (
                  <tr key={record.id}>
                    {columns.map((column) => (
                      <td key={column.label}>
                        {activeSection.source === "virtualpos" &&
                        activeSection.resource === "subscription" &&
                        column.label === "Acciones" ? (
                          isActiveSubscription(record) ? (
                            <div className="table-actions-group">
                              <button
                                className="cancel-subscription-button cancel-subscription-button-table"
                                onClick={() => onCancelSubscription(record)}
                              >
                                Cancelar Sub
                              </button>
                              <button
                                className="create-charge-button create-charge-button-table"
                                onClick={() => onNewCharge(record)}
                              >
                                + Cargo
                              </button>
                            </div>
                          ) : (
                            "-"
                          )
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "charge" &&
                          column.label === "ID subscripción" ? (
                          record.subscription_id ? (
                            <button
                              className="record-link"
                              aria-label={`Ver ficha de subscripción ${record.subscription_id}`}
                              onClick={() => void openVirtualPosSubscription({ external_id: record.subscription_id! })}
                            >
                              {record.subscription_id}
                            </button>
                          ) : (
                            <span>{column.value(record)}</span>
                          )
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "payment" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de transacción ${column.value(record)}`}
                            onClick={() => void openVirtualPosPayment(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "charge" &&
                          column.label === "Acciones" ? (
                          <div className="table-actions-group">
                            {isPendingCharge(record) ? (
                              <button
                                className="cancel-charge-button"
                                onClick={() => onCancelCharge(record)}
                              >
                                Cancelar
                              </button>
                            ) : isRejectedCharge(record) && can("virtualpos.charges.retry") ? (
                              <button
                                className="retry-charge-button"
                                onClick={() => onRetryCharge(record)}
                              >
                                Reintentar
                              </button>
                            ) : null}
                          </div>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "Acciones" ? (
                          <button
                            className="edit-button edit-button-table"
                            onClick={() => onEditClient(record)}
                          >
                            Editar
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "client" &&
                          column.label === "RUT" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cliente ${column.value(record)}`}
                            onClick={() => void openVirtualPosClient(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "plan" &&
                          column.label === "Nombre" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de plan ${column.value(record)}`}
                            onClick={() => void openVirtualPosPlan(record)}
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "virtualpos" &&
                          activeSection.resource === "subscription" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de subscripción ${column.value(record)}`}
                            onClick={() =>
                              void openVirtualPosSubscription(record)
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "toku" &&
                          activeSection.resource === "customer" &&
                          column.label === "RUT" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de cliente ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord("toku", "customer", record)
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : activeSection.source === "toku" &&
                          column.label === "RUT cliente" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord(
                                "toku",
                                activeSection.resource,
                                record,
                              )
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : (activeSection.source === "toku" ||
                            activeSection.source === "payku") &&
                          column.label === "ID" ? (
                          <button
                            className="record-link"
                            aria-label={`Ver ficha de ${activeSection.label} ${column.value(record)}`}
                            onClick={() =>
                              void openProviderRecord(
                                activeSection.source,
                                activeSection.resource,
                                record,
                              )
                            }
                          >
                            {column.value(record)}
                          </button>
                        ) : column.label === "Acciones" ? (
                          <div className="table-actions">
                            {(providerEditFields[activeSection.source]?.[activeSection.resource] ?? []).length > 0 ? (
                              <button
                                className="edit-button edit-button-table"
                                onClick={() => onEditRecord(record, activeSection.source, activeSection.resource)}
                              >
                                Editar
                              </button>
                            ) : null}
                            <button
                              className="delete-button delete-button-table"
                              onClick={() => onDeleteRecord(record, activeSection.source, activeSection.resource)}
                            >
                              Eliminar
                            </button>
                          </div>
                        ) : column.label === "Estado sec." && record.resource_type === "subscription" ? (
                          <span className={`badge badge-${record.secondary_status === "cobrable" ? "green" : record.secondary_status === "incobrable" ? "orange" : record.secondary_status === "inactiva" ? "gray" : "blue"}`}>{record.secondary_status ?? "—"}</span>
                        ) : (
                          column.value(record)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {records.items.length < records.total ? (
          <div className="table-load-more">
            <span>Mostrando {records.items.length.toLocaleString("es-CL")} de {records.total.toLocaleString("es-CL")}</span>
            <button disabled={loading} onClick={() => setRecordsOffset((offset) => offset + RECORDS_PAGE_SIZE)}>
              {loading ? "Cargando..." : "Ver más"}
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}
