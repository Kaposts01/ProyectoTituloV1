import { statusResourceOrder } from "../shared/constants";

export type StatusRow = { resource: string; status: string; count: number };

export function groupStatuses(statuses: StatusRow[]) {
  const grouped = new Map<string, { status: string; count: number }[]>();
  for (const entry of statuses) {
    const list = grouped.get(entry.resource) ?? [];
    list.push({ status: entry.status, count: entry.count });
    grouped.set(entry.resource, list);
  }
  return grouped;
}

/** Recursos que se dibujan (con estados o con total > 0), en el orden preferido del canal. */
export function statusBarResources(source: string, statuses: StatusRow[], resources: Record<string, number>): string[] {
  const grouped = groupStatuses(statuses);
  const preferred = statusResourceOrder[source] ?? [];
  return [...preferred, ...[...grouped.keys()].filter((r) => !preferred.includes(r))]
    .filter((r, i, arr) => arr.indexOf(r) === i && (grouped.has(r) || (resources[r] ?? 0) > 0));
}

