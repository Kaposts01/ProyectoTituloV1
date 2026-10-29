import type { ReactNode } from "react";
import { normalizeStatus, statusKindColor } from "../../statusColors";
import { statusResourceLabels } from "../shared/constants";
import { groupStatuses, statusBarResources, type StatusRow } from "./statusBarRows";

export function StatusBars({
  source,
  statuses,
  resources,
  emptyAction,
}: {
  source: string;
  statuses: StatusRow[];
  resources: Record<string, number>;
  /** Acción o instrucción que se muestra bajo el mensaje cuando no hay estados. */
  emptyAction?: ReactNode;
}) {
  const grouped = groupStatuses(statuses);
  const rows = statusBarResources(source, statuses, resources);
  if (!rows.length) return (
    <div className="empty-state">
      <p className="empty-chart">Este canal no entrega estados normalizados.</p>
      {emptyAction}
    </div>
  );
  return (
    <div className="status-bars">
      {rows.map((resource) => {
        const items = [...(grouped.get(resource) ?? [])].sort((a, b) => b.count - a.count);
        const total = items.reduce((s, item) => s + item.count, 0) || (resources[resource] ?? 0);
        return (
          <div key={resource} className="status-bar-row">
            <div className="status-bar-header">
              <span>{statusResourceLabels[resource] ?? resource}</span>
              <b className="mono">{total}</b>
            </div>
            <div className="status-bar-track">
              {items.length ? (
                items.map((item) => {
                  const kind = normalizeStatus(item.status);
                  return (
                    <div key={item.status} data-status-kind={kind} className="status-bar-segment" style={{ width: `${(item.count / total) * 100}%`, background: statusKindColor(kind) }} title={`${item.status}: ${item.count}`} />
                  );
                })
              ) : (
                <div className="status-bar-segment status-bar-empty" />
              )}
            </div>
            {items.length > 0 && (
              <div className="status-bar-legend">
                {items.map((item) => {
                  const kind = normalizeStatus(item.status);
                  return (
                    <span key={item.status} className="status-legend-item">
                      <i data-status-kind={kind} style={{ background: statusKindColor(kind) }} />
                      {item.status}
                      <b className="mono">{item.count}</b>
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
