export type KpiFormat = "clp" | "count" | "percent";

/** true si hay un número real (0 incluido); false para null/undefined/NaN/±Infinity. */
export function hasKpiValue(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function formatKpi(value: number | null | undefined, format: KpiFormat): string {
  if (!hasKpiValue(value)) return "—";
  if (format === "percent") {
    const rounded = Math.round(value * 10) / 10;
    return `${(rounded === 0 ? 0 : rounded).toLocaleString("es-CL", { maximumFractionDigits: 1 })}%`;
  }
  const rounded = Math.round(value);
  const abs = Math.abs(rounded).toLocaleString("es-CL");
  if (format === "clp") return `${rounded < 0 ? "-" : ""}$${abs}`;
  return `${rounded < 0 ? "-" : ""}${abs}`;
}
