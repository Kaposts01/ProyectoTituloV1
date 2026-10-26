import { formatKpi } from "../../components/formatKpi";

export function clpOrDash(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? formatKpi(numeric, "clp") : "—";
}
