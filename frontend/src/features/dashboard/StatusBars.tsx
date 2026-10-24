import { chartStatusColor } from "../../chartColors";
import { statusResourceOrder, statusResourceLabels } from "../shared/constants";

export function StatusBars({
  source,
  statuses,
  resources,
}: {
  source: string;
  statuses: { resource: string; status: string; count: number }[];
  resources: Record<string, number>;
}) {
  const grouped = new Map<string, { status: string; count: number }[]>();
  for (const entry of statuses) {
    const list = grouped.get(entry.resource) ?? [];
    list.push({ status: entry.status, count: entry.count });
    grouped.set(entry.resource, list);
  }
  const preferred = statusResourceOrder[source] ?? [];
  const rows = [
    ...preferred,
    ...[...grouped.keys()].filter((r) => !preferred.includes(r)),
  ].filter((r, i, arr) => arr.indexOf(r) === i && (grouped.has(r) || (resources[r] ?? 0) > 0));
  if (!rows.length) return <p className="empty-chart">Este canal no entrega estados normalizados.</p>;
  return (
    <div className="status-bars">
      {rows.map((resource) => {
        const items = [...(grouped.get(resource) ?? [])].sort((a, b) => b.count - a.count);
        const total = items.reduce((s, item) => s + item.count, 0) || (resources[resource] ?? 0);
        return (
          <div key={resource} className="status-bar-row">
            <div className="status-bar-header">
              <span>{statusResourceLabels[resource] ?? resource}</span>
              <b>{total}</b>
            </div>
            <div className="status-bar-track">
              {items.length ? (
                items.map((item) => (
                  <div key={item.status} className="status-bar-segment" style={{ width: `${(item.count / total) * 100}%`, background: chartStatusColor(item.status) }} title={`${item.status}: ${item.count}`} />
                ))
              ) : (
                <div className="status-bar-segment status-bar-empty" />
              )}
            </div>
            {items.length > 0 && (
              <div className="status-bar-legend">
                {items.map((item) => (
                  <span key={item.status} className="status-legend-item">
                    <i style={{ background: chartStatusColor(item.status) }} />
                    {item.status}
                    <b>{item.count}</b>
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
