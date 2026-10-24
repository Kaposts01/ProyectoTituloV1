import type { MonthlyStatusEntry } from "../../MonthlyStatusChart";

type ChargeEntry = MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" };

export function applyChargeFilter(data: ChargeEntry[], filter: "todas" | "pagada" | "rechazada"): MonthlyStatusEntry[] {
  const entries = filter === "todas" ? data : data.filter((e) => e.charge_status === filter);
  if (filter !== "todas") return entries;
  const map = new Map<string, MonthlyStatusEntry>();
  for (const e of entries) {
    const key = `${e.year}-${e.month}-${e.status}`;
    const existing = map.get(key);
    if (existing) { existing.count += e.count; existing.amount += e.amount; }
    else map.set(key, { ...e });
  }
  return [...map.values()];
}

export type { ChargeEntry };
