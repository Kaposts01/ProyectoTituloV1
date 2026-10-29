import { useEffect, useMemo, useRef, useState } from "react";
import { groupAlerts, normalizeSev, type AlertSev } from "./alertGroups";
import type { DashboardAlert } from "../shared/types";

export type { DashboardAlert };

export type AlertDetailItem = {
  external_id: string | null;
  rut: string | null;
  status: string | null;
  amount: number;
  suscription_date: string | null;
  ultimo_cobro?: string | null;
  ultimo_estado?: string | null;
  intentos?: number;
};

/** Cuántos grupos (los peores) se muestran antes de «Ver todas». */
export const ALERT_GROUPS_VISIBLE = 5;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function SevBadge({ sev }: { sev: AlertSev }) {
  return <span className={`alert-sev alert-sev-${sev}`}>{sev}</span>;
}

export function OperationalAlerts({
  alerts,
  loadDetail,
}: {
  alerts: DashboardAlert[];
  loadDetail?: (alertId: string) => Promise<AlertDetailItem[]>;
}) {
  const [expandedAlertId, setExpandedAlertId] = useState<string | null>(null);
  const [alertDetail, setAlertDetail] = useState<AlertDetailItem[] | null>(null);
  const [alertDetailLoading, setAlertDetailLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const groups = useMemo(() => groupAlerts(alerts), [alerts]);
  const groupRefs = useRef<(HTMLLIElement | null)[]>([]);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const focusAfter = useRef<"first-new" | "toggle" | null>(null);

  useEffect(() => {
    if (focusAfter.current === "first-new") groupRefs.current[ALERT_GROUPS_VISIBLE]?.focus();
    else if (focusAfter.current === "toggle") toggleRef.current?.focus();
    focusAfter.current = null;
  }, [showAll]);

  if (!alerts.length) return (
    <section className="panel dashboard-alerts-panel">
      <div className="panel-heading">
        <p className="eyebrow">ALERTAS OPERATIVAS</p>
      </div>
      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.875rem" }}>
        ✓ Sin alertas operativas — todo en orden.
      </p>
    </section>
  );

  function toggleAlert(alertId: string) {
    if (expandedAlertId === alertId) {
      setExpandedAlertId(null);
      setAlertDetail(null);
      return;
    }
    if (!loadDetail) return;
    setExpandedAlertId(alertId);
    setAlertDetail(null);
    setAlertDetailLoading(true);
    loadDetail(alertId)
      .then((items) => setAlertDetail(items))
      .catch(() => setAlertDetail(null))
      .finally(() => setAlertDetailLoading(false));
  }

  function toggleGroup(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  function toggleShowAll() {
    focusAfter.current = showAll ? "toggle" : "first-new";
    setShowAll(!showAll);
  }

  const high = alerts.filter((alert) => normalizeSev(alert.sev) === "alta").length;
  const medium = alerts.filter((alert) => normalizeSev(alert.sev) === "media").length;
  const visible = showAll ? groups : groups.slice(0, ALERT_GROUPS_VISIBLE);

  const verMas = (alert: DashboardAlert) =>
    alert.id && loadDetail ? (
      <button className="alert-ver-mas" onClick={() => toggleAlert(alert.id!)}>{expandedAlertId === alert.id ? "Cerrar" : "Ver más"}</button>
    ) : null;

  const detailPanel = (alert: DashboardAlert) =>
    alert.id && expandedAlertId === alert.id ? (
      <div className="alert-detail-panel">
        {alertDetailLoading ? <p className="alert-detail-loading">Cargando...</p> : !alertDetail?.length ? <p className="alert-detail-empty">Sin registros.</p> : (
          <div className="alert-detail-table-wrap">
            <table className="alert-detail-table">
              <thead><tr><th>RUT</th><th>ID suscripción</th><th>Estado</th><th>Monto</th><th>Fecha suscripción</th>{alertDetail[0]?.ultimo_cobro !== undefined && <th>Último cobro</th>}{alertDetail[0]?.ultimo_estado !== undefined && <th>Estado último cobro</th>}{alertDetail[0]?.intentos !== undefined && <th>Intentos</th>}</tr></thead>
              <tbody>{alertDetail.map((item, itemIndex) => <tr key={itemIndex}><td className="mono">{item.rut ?? "—"}</td><td className="alert-detail-id mono">{item.external_id ?? "—"}</td><td>{item.status ?? "—"}</td><td className="mono" style={{ textAlign: "right" }}>{item.amount ? `$${item.amount.toLocaleString("es-CL")}` : "—"}</td><td className="mono">{item.suscription_date?.slice(0, 10) ?? "—"}</td>{alertDetail[0]?.ultimo_cobro !== undefined && <td className="mono">{item.ultimo_cobro?.slice(0, 10) ?? "—"}</td>}{alertDetail[0]?.ultimo_estado !== undefined && <td>{item.ultimo_estado ?? "—"}</td>}{alertDetail[0]?.intentos !== undefined && <td className="mono">{item.intentos}</td>}</tr>)}</tbody>
            </table>
            <p className="alert-detail-count">{alertDetail.length} registro{alertDetail.length !== 1 ? "s" : ""}</p>
          </div>
        )}
      </div>
    ) : null;

  return (
    <section className="panel dashboard-alerts-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">ALERTAS OPERATIVAS</p>
          <h3>{plural(alerts.length, "alerta", "alertas")} en {plural(groups.length, "grupo", "grupos")}</h3>
          <p className="dashboard-alerts-summary">
            {high > 0 && <span className="alert-sev alert-sev-alta">{plural(high, "alta", "altas")}</span>}
            {medium > 0 && <span className="alert-sev alert-sev-media">{plural(medium, "media", "medias")}</span>}
          </p>
        </div>
      </div>
      <ul className="dashboard-alerts-list" aria-label="Alertas operativas">
        {visible.map((group, index) => {
          const open = openGroups.has(group.key);
          const multi = group.alerts.length > 1;
          const subId = `alert-group-${index}-periods`;
          return (
            <li
              key={group.key}
              ref={(el) => { groupRefs.current[index] = el; }}
              tabIndex={-1}
              data-testid="alert-group"
              className={`dashboard-alert-group dashboard-alert-${group.sev}`}
            >
              <div className="dashboard-alert-row">
                <SevBadge sev={group.sev} />
                <strong className="dashboard-alert-tipo">{group.tipo}</strong>
                <span className="dashboard-alert-canal">{group.canal}</span>
                <span className="dashboard-alert-detalle">{group.detalle}</span>
                {multi ? (
                  <button className="alert-ver-mas" aria-expanded={open} aria-controls={subId} onClick={() => toggleGroup(group.key)}>
                    {group.alerts.length} periodos
                  </button>
                ) : verMas(group.alerts[0])}
              </div>
              {!multi ? detailPanel(group.alerts[0]) : null}
              {multi && open ? (
                <ul id={subId} className="dashboard-alert-sublist" aria-label={`Periodos de ${group.tipo} en ${group.canal}`}>
                  {group.alerts.map((alert, i) => (
                    <li key={`${alert.id ?? alert.periodo ?? i}-${i}`} className="dashboard-alert-subrow">
                      <div className="dashboard-alert-row">
                        <SevBadge sev={normalizeSev(alert.sev)} />
                        <span className="dashboard-alert-periodo mono">{alert.periodo ?? "—"}</span>
                        <span className="dashboard-alert-detalle">{alert.detalle}</span>
                        {verMas(alert)}
                      </div>
                      {detailPanel(alert)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
      {groups.length > ALERT_GROUPS_VISIBLE ? (
        <button ref={toggleRef} className="alert-show-all" aria-expanded={showAll} onClick={toggleShowAll}>
          {showAll ? "Ver menos" : `Ver todas (${groups.length})`}
        </button>
      ) : null}
    </section>
  );
}
