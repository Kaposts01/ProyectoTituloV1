export type Channel = "virtualpos" | "toku" | "payku" | "tch";

export type RecaudoMensual = {
  period: string | null;
  mrr: number | null;
  /** Transacciones aceptadas (no clientes distintos). */
  acceptedTransactions: number | null;
  arpu: number | null;
  rejectedCount: number | null;
  rejectedAmount: number | null;
};

export type ChannelKpis = {
  mrr: number | null;
  arpu: number | null;
  activeSubscribers: number | null;
  activeClients: number | null;
  churnRate: number | null;
  ltv: number | null;
  rejectedCharges: { count: number | null; amount: number | null };
  note?: string;
  /** Solo TCH: recaudo aceptado del último período (reportes Excel oficiales). */
  recaudoMensual?: RecaudoMensual;
};

export const CHANNEL_KPI_NOTES: Partial<Record<Channel, string>> = {
  payku: "Cobertura histórica no certificada · MRR desde última transacción success",
  tch: "Fuente: reportes Excel oficiales",
};

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function rec(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/** Tolerante a campos faltantes: lo ausente queda en null (se muestra "—"). */
export function normalizeKpis(channel: Channel, raw: unknown): ChannelKpis {
  const k = rec(raw);
  const rejected = rec(k.rejected_charges);
  const recaudo = k.recaudo_mensual !== null && typeof k.recaudo_mensual === "object" ? rec(k.recaudo_mensual) : null;
  return {
    mrr: num(k.mrr),
    arpu: num(k.arpu),
    activeSubscribers: num(k.active_subscribers),
    activeClients: num(k.active_clients),
    churnRate: num(k.churn_rate),
    ltv: num(k.ltv),
    rejectedCharges: { count: num(rejected.count), amount: num(rejected.amount) },
    note: CHANNEL_KPI_NOTES[channel],
    ...(recaudo
      ? {
          recaudoMensual: {
            period: typeof recaudo.period === "string" ? recaudo.period : null,
            mrr: num(recaudo.mrr),
            acceptedTransactions: num(recaudo.accepted_transactions) ?? num(recaudo.active_clients),
            arpu: num(recaudo.arpu),
            rejectedCount: num(recaudo.rejected_count),
            rejectedAmount: num(recaudo.rejected_amount),
          },
        }
      : {}),
  };
}
