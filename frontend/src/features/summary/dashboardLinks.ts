import { serverNow } from "../../serverClock";
import { parseMonth } from "./summaryFormat";
import type { SummaryChannel, UnifiedSummary } from "./summaryTypes";
import type { PrimaryMetric } from "./dashboardContext";

export function observedMonthWindow(month: string, now = serverNow()) {
  const parts = parseMonth(month);
  if (!parts) return null;
  const todayParts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(now));
  const part = (type: string) => todayParts.find((p) => p.type === type)?.value ?? "";
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  const start = `${month}-01`;
  if (start > today) return null;
  const leap = parts.year % 4 === 0 && (parts.year % 100 !== 0 || parts.year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][parts.month - 1];
  const end = `${month}-${days}`;
  return { from: start, to: end > today ? today : end };
}

export const RECORD_COVERAGE = {
  virtualpos: "Cargos de ambas cuentas VirtualPOS, filtrados por fecha de cobro.",
  toku: "El Dashboard evalúa facturas e incluye las impagas o parcialmente pagadas vencidas en No cobrado; al revisar ese indicador el listado conserva todos los estados. La tasa de rechazo del listado usa intentos de cobro y no se compara directamente con la cobrabilidad del Dashboard.",
  payku: "El Dashboard utiliza pagos de Payku; se abre la pestaña Pagos, no los ciclos de cobro.",
  tch: "TCH usa controles mensuales oficiales cuando existen y, como respaldo, el período de las transacciones. El listado filtra por fecha de cargo: sus filas pueden diferir del total del Dashboard.",
} satisfies Record<SummaryChannel, string>;

export function metricRecordLinks(summary: UnifiedSummary, metric: PrimaryMetric, can: (permission: string) => boolean, now = serverNow()) {
  const generated = Date.parse(summary.generatedAt ?? "");
  const window = observedMonthWindow(summary.month, Number.isFinite(generated) ? Math.min(now, generated) : now);
  return summary.channels.flatMap((channel) => {
    const subscriptions = metric === "members";
    const permission = subscriptions
      ? { virtualpos: "virtualpos.subscriptions.view", toku: "toku.subscriptions.view", payku: "payku.subscriptions.view", tch: "tch.suscripciones.view" }[channel]
      : { virtualpos: "virtualpos.charges.view", toku: "toku.invoices.view", payku: "payku.transactions.view", tch: "tch.transacciones.view" }[channel];
    if (!can(permission) && !can(subscriptions ? "general.subscriptions.view" : "general.charges.view")) return [];
    if (!window) return [];
    const params = new URLSearchParams({ canal: channel, desde_dashboard: metric, mes: summary.month, canales: summary.channels.join(",") });
    if (!subscriptions) {
      params.set("tab", channel === "payku" ? "payments" : "charges");
      params.set("date_from", window.from); params.set("date_to", window.to);
      if (metric === "revenue") params.set("outcome", "paid");
      if (metric === "uncollected" && channel !== "toku") params.set("outcome", "rejected");
    }
    return [{ channel, href: `/central/${subscriptions ? "suscripciones" : "cobros"}?${params}`, note: subscriptions
      ? "Suscripciones en su estado actual. Este listado no reconstruye la base al cierre del mes ni identifica personas únicas."
      : RECORD_COVERAGE[channel] }];
  });
}
