import { SUMMARY_CHANNELS, type SummaryChannel } from "./summaryTypes";
import { parseMonth } from "./summaryFormat";

export const PRIMARY_METRICS = ["revenue", "members", "collectability", "uncollected"] as const;
export type PrimaryMetric = (typeof PRIMARY_METRICS)[number];
export const METRIC_LABELS: Record<PrimaryMetric, string> = {
  revenue: "Ingreso total", members: "Socios totales", collectability: "Cobrabilidad", uncollected: "No cobrado",
};
export function isPrimaryMetric(value: string | null): value is PrimaryMetric {
  return PRIMARY_METRICS.some((key) => key === value);
}
export function selectedChannels(value: string | null): SummaryChannel[] | undefined {
  if (!value) return undefined;
  const values = value.split(",");
  if (!values.every((v) => SUMMARY_CHANNELS.some((channel) => channel === v))) return undefined;
  return SUMMARY_CHANNELS.filter((channel) => values.includes(channel));
}
export function dashboardSelection(search: string) {
  const params = new URLSearchParams(search);
  const month = params.get("mes");
  return { month: month && parseMonth(month) ? month : undefined, channels: selectedChannels(params.get("canales")) };
}
export function dashboardHref(month: string, channels: SummaryChannel[]) {
  return `/central/resumen?${new URLSearchParams({ mes: month, canales: channels.join(",") })}`;
}
export function readDashboardContext(search: string) {
  const params = new URLSearchParams(search);
  const metric = params.get("desde_dashboard");
  const { month, channels } = dashboardSelection(search);
  return isPrimaryMetric(metric) && month && channels?.length ? { metric, month, channels } : null;
}

/** Only documented filter values enter initial list state. Search terms are never read from URLs. */
export function readPortfolioLocation(search: string) {
  const params = new URLSearchParams(search);
  const canal = params.get("canal") ?? "";
  const validDay = (value: string | null) => {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
    const date = new Date(`${value}T12:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : "";
  };
  const offset = Number(params.get("offset") ?? "0");
  const outcome = params.get("outcome") ?? "";
  const from = validDay(params.get("date_from")), to = validDay(params.get("date_to"));
  return {
    channel: [...SUMMARY_CHANNELS, "virtualpos1", "virtualpos2"].some((c) => c === canal) ? canal : "",
    tab: params.get("tab") === "payments" ? "payments" as const : "charges" as const,
    outcome: ["paid", "rejected", "pending", "excluded", "other"].includes(outcome) ? outcome : "",
    dateFrom: from && to && from > to ? "" : from, dateTo: from && to && from > to ? "" : to,
    offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0,
  };
}
