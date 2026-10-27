import { useState } from "react";
import { downloadFile, friendlyError, getJson, postJson } from "../../api";
import type { RecoveryResponse, RecoveryRow } from "../shared/types";
import { recoveryNestedValue, recoveryRowKey, recoveryValue } from "../shared/utils";
import { useEnabledChannels } from "../shared/environment";
import { RECOVERY_CHANNELS, enabledAccounts, type RecoveryChannelId } from "./recoveryChannels";
import { RecoveryTable } from "./RecoveryTable";
import {
  EMPTY_FILTERS, canExport, exportTarget, listPath, tabAcceptsFilters,
  type RecoveryFilterValues, type RecoveryGroup, type RecoveryQueryState, type RecoveryTab,
} from "./recoveryQuery";

const TAB_LABELS: Record<RecoveryTab, string> = { cancelled: "Socios cancelados", retry: "Cargos reintentables", history: "Historial de reintentos", card: "Tarjetas por vencer" };
const GROUP_LABELS: Record<RecoveryGroup, string> = { inactiva: "Inactivas", incobrable: "Incobrables", nunca_cobrado: "Nunca cobrado" };
const SECONDARY_LABELS: Record<string, string> = { inactiva: "Inactiva", incobrable: "Incobrable", nunca_cobrado: "Nunca cobrado", cobrable: "Cobrable" };
const PAGE_SIZE = 50;

type Props = {
  channel: RecoveryChannelId;
  can: (permission: string) => boolean;
};

export function RecoveryPanel({ channel, can }: Props) {
  const config = RECOVERY_CHANNELS[channel];
  const { enabled: enabledChannels } = useEnabledChannels();
  const accounts = enabledAccounts(config.accounts, enabledChannels);
  const [tab, setTab] = useState<RecoveryTab>("cancelled");
  const [group, setGroup] = useState<RecoveryGroup>("inactiva");
  const [filters, setFilters] = useState<RecoveryFilterValues>(EMPTY_FILTERS);
  // Query that produced the rows on screen; export and the table headers use it so they match the data.
  const [applied, setApplied] = useState<RecoveryQueryState | null>(null);
  const [rows, setRows] = useState<RecoveryResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cardLink, setCardLink] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const setFilter = (key: keyof RecoveryFilterValues, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  const resetResults = () => { setRows(null); setApplied(null); setOffset(0); setSelected(new Set()); setError(null); setNotice(null); setCardLink(null); };
  const showExport = Boolean(rows && applied && exportTarget(applied) && canExport(can));

  async function load(nextOffset = 0, state: RecoveryQueryState = { tab, group, filters }) {
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const data = await getJson<RecoveryResponse>(listPath(state, nextOffset, PAGE_SIZE));
      setRows(data);
      setApplied(state);
      setOffset(nextOffset);
      setSelected(new Set());
    } catch (err) {
      setError(friendlyError(err, "No se pudieron cargar los registros de recuperación."));
    } finally {
      setLoading(false);
    }
  }

  async function retryMany() {
    if (selected.size === 0 || submitting) return;
    const items = (rows?.items ?? []).filter((item) => selected.has(recoveryRowKey(item))).flatMap((item) => {
      const source = recoveryValue(item, "source");
      const externalId = recoveryValue(item, "external_id", "id");
      return source && externalId ? [{ source: String(source), external_id: String(externalId) }] : [];
    });
    if (items.length === 0) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await postJson<{ succeeded: number }>("/api/v1/recovery/retries", { items });
      const failed = items.length - result.succeeded;
      setNotice(`Reintentos solicitados: ${result.succeeded} exitosos y ${failed} fallidos.`);
      await load(offset, applied ?? undefined);
    } catch (err) {
      setError(friendlyError(err, "No se pudieron solicitar los reintentos."));
    } finally {
      setSubmitting(false);
    }
  }

  async function retryOne(item: RecoveryRow) {
    const source = recoveryValue(item, "source");
    const externalId = recoveryValue(item, "external_id", "id");
    if (!source || !externalId || submitting) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await postJson<{ succeeded: number }>("/api/v1/recovery/retries", { items: [{ source: String(source), external_id: String(externalId) }] });
      setNotice(`Reintento del cargo ${String(externalId)}: ${result.succeeded} exitoso y ${1 - result.succeeded} fallido.`);
      await load(offset, applied ?? undefined);
    } catch (err) {
      setError(friendlyError(err, "No se pudo solicitar el reintento."));
    } finally {
      setSubmitting(false);
    }
  }

  async function exportCsv() {
    const target = applied ? exportTarget(applied) : null;
    if (!target) return;
    setError(null);
    try {
      await downloadFile(target.path, target.filename);
    } catch (err) {
      setError(friendlyError(err, "No se pudo descargar la exportación."));
    }
  }

  async function createCardLink(item: RecoveryRow) {
    const subscriptionId = recoveryValue(item, "subscription_id", "id") ?? recoveryNestedValue(item, "subscription", "id", "external_id");
    if (!subscriptionId || submitting) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setCardLink(null);
    try {
      const source = recoveryValue(item, "source") ?? "virtualpos1";
      const result = await postJson<Record<string, unknown>>(`/api/v1/recovery/card-change-links/${encodeURIComponent(String(subscriptionId))}?source=${encodeURIComponent(String(source))}`);
      const url = recoveryValue(result, "url", "link", "card_change_url");
      setCardLink(typeof url === "string" ? url : null);
      setNotice(url ? "Enlace de cambio de tarjeta generado." : "Se solicitó el enlace de cambio de tarjeta.");
    } catch (err) {
      setError(friendlyError(err, "No se pudo generar el enlace de cambio de tarjeta."));
    } finally {
      setSubmitting(false);
    }
  }

  const dateLabelFrom = tab === "cancelled" && group === "inactiva" ? "Canceladas desde" : tab === "cancelled" ? "Inicio desde" : "Desde";
  const dateLabelTo = tab === "cancelled" && group === "inactiva" ? "Canceladas hasta" : tab === "cancelled" ? "Inicio hasta" : "Hasta";
  const showRejectionFilters = tab === "retry" || tab === "card";

  return (
    <main className="app-shell recovery-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">{config.label}</p>
          <h1>{config.title}</h1>
        </div>
      </div>
      <div className="recovery-tabs" role="tablist" aria-label="Vistas de recuperación">
        {(Object.keys(TAB_LABELS) as RecoveryTab[]).map((key) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => { setTab(key); resetResults(); }}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      {tab === "cancelled" ? (
        <div className="recovery-tabs" role="tablist" aria-label="Grupo de socios" style={{ marginTop: "8px", gap: "6px" }}>
          {(Object.keys(GROUP_LABELS) as RecoveryGroup[]).map((key) => (
            <button key={key} role="tab" aria-selected={group === key} className={group === key ? "active" : ""} style={{ fontSize: "13px", padding: "5px 12px" }} onClick={() => { setGroup(key); setRows(null); setApplied(null); setOffset(0); setError(null); }}>
              {GROUP_LABELS[key]}
            </button>
          ))}
        </div>
      ) : null}
      <div className="recovery-controls">
        {tab !== "card" ? <>
          <label>{dateLabelFrom}<input type="date" value={filters.dateFrom} onChange={(event) => setFilter("dateFrom", event.target.value)} /></label>
          <label>{dateLabelTo}<input type="date" value={filters.dateTo} onChange={(event) => setFilter("dateTo", event.target.value)} /></label>
        </> : null}
        {tabAcceptsFilters(tab) ? <>
          <label>Cuenta
            <select value={filters.account} onChange={(event) => setFilter("account", event.target.value)}>
              <option value="">Todas</option>
              {accounts.map((account) => <option key={account.value} value={account.value}>{account.label}</option>)}
            </select>
          </label>
          <label>Monto mínimo<input className="mono" type="number" min="0" inputMode="numeric" value={filters.minAmount} onChange={(event) => setFilter("minAmount", event.target.value)} /></label>
          <label>Monto máximo<input className="mono" type="number" min="0" inputMode="numeric" value={filters.maxAmount} onChange={(event) => setFilter("maxAmount", event.target.value)} /></label>
        </> : null}
        {showRejectionFilters ? <>
          <label>Código de rechazo<input className="mono" type="text" maxLength={100} value={filters.rejectionCode} onChange={(event) => setFilter("rejectionCode", event.target.value)} /></label>
          <label>Estado secundario
            <select value={filters.secondaryStatus} onChange={(event) => setFilter("secondaryStatus", event.target.value)}>
              <option value="">Todos</option>
              {Object.entries(SECONDARY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>Rechazo desde<input type="date" value={filters.rejectedFrom} onChange={(event) => setFilter("rejectedFrom", event.target.value)} /></label>
          <label>Rechazo hasta<input type="date" value={filters.rejectedTo} onChange={(event) => setFilter("rejectedTo", event.target.value)} /></label>
        </> : null}
        <button className="primary-button" onClick={() => void load(0)} disabled={loading}>{loading ? "Cargando..." : "Buscar"}</button>
        {tab === "retry" && selected.size > 0 && can(config.retryPermission) ? <button className="primary-button" onClick={() => void retryMany()} disabled={submitting}>{submitting ? "Solicitando..." : `Reintentar seleccionados (${selected.size})`}</button> : null}
      </div>
      {showExport && rows ? (
        <div className="recovery-export">
          <button className="secondary-button" onClick={() => void exportCsv()}>Exportar CSV (<span className="mono">{rows.total.toLocaleString("es-CL")}</span> filas)</button>
          <p className="muted-copy">El archivo contiene datos personales (RUT, nombre, correo y teléfono). La exportación queda registrada en la auditoría.</p>
        </div>
      ) : null}
      {error ? <p className="error-message">{error}</p> : null}
      {notice ? <p className="success-message">{notice}</p> : null}
      {cardLink ? <p className="success-message">Enlace: <a href={cardLink} target="_blank" rel="noreferrer">Abrir cambio de tarjeta</a></p> : null}
      {rows && applied ? <>
        <RecoveryTable
          tab={applied.tab} group={applied.group} items={rows.items} selected={selected} submitting={submitting}
          canRetry={can(config.retryPermission)} canChangeCard={can(config.cardChangePermission)}
          onToggle={(key, checked) => setSelected((current) => { const next = new Set(current); if (checked) next.add(key); else next.delete(key); return next; })}
          onToggleAll={(checked) => setSelected(checked ? new Set(rows.items.map(recoveryRowKey)) : new Set())}
          onRetry={(item) => void retryOne(item)} onCardLink={(item) => void createCardLink(item)}
        />
        <div className="recovery-pagination">
          <button className="secondary-button" disabled={offset === 0 || loading} onClick={() => void load(Math.max(0, offset - PAGE_SIZE), applied)}>Anterior</button>
          <span className="mono">{rows.total ? `${offset + 1}-${Math.min(offset + rows.limit, rows.total)} de ${rows.total}` : "0 registros"}</span>
          <button className="secondary-button" disabled={offset + rows.limit >= rows.total || loading} onClick={() => void load(offset + rows.limit, applied)}>Siguiente</button>
        </div>
      </> : !loading ? <p className="muted-copy">Selecciona una pestaña y consulta los registros disponibles.</p> : null}
    </main>
  );
}
