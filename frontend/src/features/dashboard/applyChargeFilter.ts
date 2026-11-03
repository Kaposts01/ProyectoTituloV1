import type { MonthlyStatusEntry } from "../shared/monthly";

/** Filtro de la gráfica: «all» suma todo; «paid» y «rejected» se traducen al valor del backend (`charge_status`). */
export type ChargeFilter = "all" | "paid" | "rejected";
const WIRE_STATUS: Record<"paid" | "rejected", "pagada" | "rechazada"> = { paid: "pagada", rejected: "rechazada" };

type ChargeEntry = MonthlyStatusEntry & { charge_status: "pagada" | "rechazada" };

export function applyChargeFilter(data: ChargeEntry[], filter: ChargeFilter): MonthlyStatusEntry[] {
  const entries = filter === "all" ? data : data.filter((e) => e.charge_status === WIRE_STATUS[filter]);
  if (filter !== "all") return entries;
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
