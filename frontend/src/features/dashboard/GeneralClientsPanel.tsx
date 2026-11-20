import { useEffect, useRef, useState } from "react";
import { label } from "../../i18n/label";
import { getJson, friendlyError } from "../../api";
import { adaptGeneralClientDetail, type GeneralClientDetailWire } from "./generalClientAdapter";
import { ExportButton } from "../shared/ExportButton";
import { consolidatedExportTarget } from "../shared/exportMapping";
import type { GeneralState } from "./useGeneralDashboard";
import { PortfolioFilters, UnifiedPagination, type FilterChip } from "../general/UnifiedControls";
import { PortfolioTable, type PortfolioColumn } from "../general/PortfolioTable";
import type { GeneralClient } from "../shared/types";
import { Rut } from "../shared/RutCell";
import { MemberDetail } from "./MemberDetail";
import { rutText } from "../shared/rut";

const CLIENT_FIELDS = [
  { value: "all", label: "Todos los campos" }, { value: "rut", label: "RUT" }, { value: "name", label: "Nombre" },
  { value: "last_name", label: "Apellido" }, { value: "platform", label: "Plataforma" }, { value: "email", label: "Correo" },
  { value: "phone", label: "Teléfono" },
];
const CLIENT_CHANNELS = [
  { value: "virtualpos", label: "VirtualPOS" }, { value: "toku", label: "Toku" }, { value: "payku", label: "Payku" }, { value: "tch", label: "TCH" },
];
const CLIENT_STATUSES = [{ value: "active", label: "Con suscripción activa" }, { value: "inactive", label: "Sin suscripción activa" }];

/** Tabla de clientes consolidados por RUT, con búsqueda, paginación y ficha general. */
export function GeneralClientsPanel({ general, setError, can, onOpenPath }: { general: GeneralState; setError: (message: string | null) => void; can?: (permission: string) => boolean; onOpenPath?: (path: string) => void }) {
  const {
    generalClients, generalClientsLoading, generalClientsError, generalClientsForbidden, reloadGeneralClients,
    generalClientQuery,
    setGeneralClientQuery,
    generalClientFilter,
    setGeneralClientFilter,
    generalClientOffset,
    setGeneralClientOffset,
    generalClientDetail,
    setGeneralClientDetail,
    generalClientChannel,
    setGeneralClientChannel,
    generalClientStatus,
    setGeneralClientStatus,
  } = general;
  const exportTarget = consolidatedExportTarget("clientes", generalClientFilter, generalClientQuery);
  const [opening, setOpening] = useState(false);
  const [selectedMember, setSelectedMember] = useState<GeneralClient | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const restoringFocus = useRef(false);
  useEffect(() => () => detailRequest.current?.abort(), []);
  useEffect(() => {
    if (!generalClientDetail && restoringFocus.current) {
      const trigger = selectedMember ? document.getElementById(`member-open-${encodeURIComponent(selectedMember.rut)}`) : null;
      (trigger ?? document.querySelector<HTMLInputElement>('[aria-label="Buscar socios"]'))?.focus();
      restoringFocus.current = false;
    }
  }, [generalClientDetail, selectedMember]);
  const resetOffset = () => { detailRequest.current?.abort(); setGeneralClientDetail(null); setOpening(false); setDetailError(null); setGeneralClientOffset(0); };
  const optionLabel = (options: { value: string; label: string }[], value: string) => options.find((option) => option.value === value)?.label ?? value;
  const chips: FilterChip[] = [];
  if (generalClientQuery.trim()) {
    const where = generalClientFilter === "all" ? "Texto" : optionLabel(CLIENT_FIELDS, generalClientFilter);
    chips.push({ key: "texto", label: `${where}: «${generalClientQuery.trim()}»`, onRemove: () => { setGeneralClientQuery(""); setGeneralClientFilter("all"); resetOffset(); } });
  }
  if (generalClientChannel) chips.push({ key: "canal", label: `Canal: ${optionLabel(CLIENT_CHANNELS, generalClientChannel)}`, onRemove: () => { setGeneralClientChannel(""); resetOffset(); } });
  if (generalClientStatus) chips.push({ key: "estado", label: `Estado: ${optionLabel(CLIENT_STATUSES, generalClientStatus)}`, onRemove: () => { setGeneralClientStatus(""); resetOffset(); } });
  const clearAll = () => { setGeneralClientQuery(""); setGeneralClientFilter("all"); setGeneralClientChannel(""); setGeneralClientStatus(""); resetOffset(); };
  async function openMember(client: GeneralClient) {
    detailRequest.current?.abort();
    const controller = new AbortController(); detailRequest.current = controller;
    setError(null); setDetailError(null); setSelectedMember(client); setOpening(true);
    try {
      const result = await getJson<GeneralClientDetailWire>(`/api/v1/staging/dashboard/general/clients/${encodeURIComponent(client.rut)}`, controller.signal);
      if (!controller.signal.aborted) setGeneralClientDetail(adaptGeneralClientDetail(result));
    } catch (err: unknown) {
      if (!controller.signal.aborted) setDetailError(friendlyError(err, "No se pudo abrir la ficha. Inténtalo nuevamente."));
    } finally { if (!controller.signal.aborted) setOpening(false); }
  }
  function closeMember() {
    restoringFocus.current = true;
    setGeneralClientDetail(null);
  }
  const columns: PortfolioColumn<GeneralClient>[] = [
    { id: "rut", label: "RUT", required: true, cell: (client) => <button id={`member-open-${encodeURIComponent(client.rut)}`} className="record-link" aria-label={rutText(client.rut)} disabled={opening} onClick={() => { void openMember(client); }}><Rut value={client.rut} /><span className="member-open-label">Ver ficha</span></button> },
    { id: "name", label: "Nombre completo", required: true, cell: (client) => client.name || "—" },
    { id: "origins", label: "Plataforma de origen", cell: (client) => client.origins.map((origin) => label("channel", origin)).join(" · ") },
    { id: "active", label: "Suscripciones activas", cell: (client) => client.active_origins.map((origin) => label("channel", origin)).join(" · ") || "—" },
  ];
  return (
    <section className="panel">
      <div className="panel-heading sr-only"><div><p className="eyebrow">Cartera</p><h3>Listado de socios</h3></div></div>
      <PortfolioFilters searchLabel="Buscar socios" placeholder="Nombre, RUT, correo o teléfono" query={generalClientQuery} busy={generalClientsLoading}
        onQuery={(value) => { setGeneralClientQuery(value); resetOffset(); }} fieldLabel={optionLabel(CLIENT_FIELDS, generalClientFilter)}
        count={generalClientsLoading ? null : generalClients?.total ?? null} noun="socios" chips={chips} onClear={clearAll}
        activeCount={Number(Boolean(generalClientStatus)) + Number(generalClientFilter !== "all")}
        channelControl={<label className="filter-field"><span>Canal</span>
          <select aria-label="Canal de los socios" value={generalClientChannel} onChange={(event) => { setGeneralClientChannel(event.target.value as typeof generalClientChannel); resetOffset(); }}>
            <option value="">Todos los canales</option>{CLIENT_CHANNELS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>}
        advanced={<>
          <label className="filter-field"><span>Buscar en</span>
            <select aria-label="Buscar en" value={generalClientFilter} onChange={(event) => { setGeneralClientFilter(event.target.value as typeof generalClientFilter); resetOffset(); }}>
              {CLIENT_FIELDS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="filter-field"><span>Estado</span>
            <select aria-label="Estado de los socios" value={generalClientStatus} onChange={(event) => { setGeneralClientStatus(event.target.value as typeof generalClientStatus); resetOffset(); }}>
              <option value="">Todos</option>{CLIENT_STATUSES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </>}
        actions={<ExportButton entity="clientes" canal={generalClientChannel || undefined} ignoredFilters={generalClientStatus ? [generalClientStatus === "active" ? "estado: con suscripción activa" : "estado: sin suscripción activa"] : []} params={exportTarget.params} window={{ offset: generalClientOffset, limit: 50 }} canPii={can?.("export.pii")} notes={["El archivo lista un registro por canal, no uno por RUT: sus filas pueden diferir de las de la pantalla."]} />}
      />
      <aside className="member-identity-note"><p>Agrupación por RUT · Identidad sin confirmar</p><details><summary>Qué significa</summary><p>Agrupado por RUT <strong>no verificado</strong>: un RUT compartido entre canales se agrupa, pero no confirma que corresponda a la misma persona. La identidad centralizada sigue pendiente.</p></details></aside>
      {opening ? <p className="member-loading" role="status" aria-live="polite">Abriendo ficha de {selectedMember?.name || "socio"}…</p> : null}
      {detailError ? <div className="error-message" role="alert"><p>{detailError}</p><button className="secondary-button" type="button" onClick={() => { if (selectedMember) void openMember(selectedMember); }}>Reintentar ficha</button></div> : null}
      {generalClientDetail ? (
        <MemberDetail member={selectedMember} detail={generalClientDetail} can={can} onOpenPath={onOpenPath} onClose={closeMember} />
      ) : <>
        <PortfolioTable view="members" caption="socios" columns={columns} rows={generalClients?.items ?? []} rowKey={(row) => row.rut}
          loading={generalClientsLoading} error={generalClientsError} forbidden={generalClientsForbidden} onRetry={reloadGeneralClients}
          filtered={chips.length > 0} onClear={clearAll} />
        {generalClients ? <UnifiedPagination offset={generalClientOffset} limit={generalClients.limit} total={generalClients.total}
          shown={generalClients.items.length} onOffset={setGeneralClientOffset} loading={generalClientsLoading} /> : null}
      </>}

    </section>
  );
}
