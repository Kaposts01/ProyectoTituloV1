import { Fragment, useState } from "react";

export type DashboardAlert = {
  id?: string;
  sev: "alta" | "media" | "baja";
  tipo: string;
  canal: string;
  detalle: string;
};

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

  if (!alerts.length) return null;

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

  const high = alerts.filter((alert) => alert.sev === "alta").length;
  const medium = alerts.filter((alert) => alert.sev === "media").length;
  return (
    <section className="panel dashboard-alerts-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">ALERTAS OPERATIVAS</p>
          <h3>
            {high > 0 && <span className="badge badge-orange" style={{ marginRight: "0.5rem" }}>{high} alta{high !== 1 ? "s" : ""}</span>}
            {medium > 0 && <span className="badge badge-blue" style={{ marginRight: "0.5rem" }}>{medium} media{medium !== 1 ? "s" : ""}</span>}
            {alerts.length} alerta{alerts.length !== 1 ? "s" : ""} detectada{alerts.length !== 1 ? "s" : ""}
          </h3>
        </div>
      </div>
      <div className="dashboard-alerts-list">
        {alerts.map((alert, index) => (
          <Fragment key={`${alert.id ?? alert.tipo}-${index}`}>
            <div className={`dashboard-alert-row dashboard-alert-${alert.sev}`}>
              <span className={`badge ${alert.sev === "alta" ? "badge-orange" : alert.sev === "media" ? "badge-blue" : "badge-gray"}`}>{alert.sev}</span>
              <strong className="dashboard-alert-tipo">{alert.tipo}</strong>
              <span className="dashboard-alert-canal">{alert.canal}</span>
              <span className="dashboard-alert-detalle">{alert.detalle}</span>
              {alert.id && loadDetail && <button className="alert-ver-mas" onClick={() => toggleAlert(alert.id!)}>{expandedAlertId === alert.id ? "Cerrar" : "Ver más"}</button>}
            </div>
            {alert.id && expandedAlertId === alert.id && (
              <div className="alert-detail-panel">
                {alertDetailLoading ? <p className="alert-detail-loading">Cargando...</p> : !alertDetail?.length ? <p className="alert-detail-empty">Sin registros.</p> : (
                  <div className="alert-detail-table-wrap">
                    <table className="alert-detail-table">
                      <thead><tr><th>RUT</th><th>ID suscripción</th><th>Estado</th><th>Monto</th><th>Fecha suscripción</th>{alertDetail[0]?.ultimo_cobro !== undefined && <th>Último cobro</th>}{alertDetail[0]?.ultimo_estado !== undefined && <th>Estado último cobro</th>}{alertDetail[0]?.intentos !== undefined && <th>Intentos</th>}</tr></thead>
                      <tbody>{alertDetail.map((item, itemIndex) => <tr key={itemIndex}><td>{item.rut ?? "—"}</td><td className="alert-detail-id">{item.external_id ?? "—"}</td><td>{item.status ?? "—"}</td><td>{item.amount ? `$${item.amount.toLocaleString("es-CL")}` : "—"}</td><td>{item.suscription_date?.slice(0, 10) ?? "—"}</td>{alertDetail[0]?.ultimo_cobro !== undefined && <td>{item.ultimo_cobro?.slice(0, 10) ?? "—"}</td>}{alertDetail[0]?.ultimo_estado !== undefined && <td>{item.ultimo_estado ?? "—"}</td>}{alertDetail[0]?.intentos !== undefined && <td>{item.intentos}</td>}</tr>)}</tbody>
                    </table>
                    <p className="alert-detail-count">{alertDetail.length} registro{alertDetail.length !== 1 ? "s" : ""}</p>
                  </div>
                )}
              </div>
            )}
          </Fragment>
        ))}
      </div>
    </section>
  );
}
