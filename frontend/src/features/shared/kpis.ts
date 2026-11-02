export type Channel = "virtualpos" | "toku" | "payku" | "tch";

export type MonthlyCollection = {
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
  /** Ventana sobre la que se calculó el churn («promedio de 3 meses»…); null si el backend no la informa. */
  churnWindowLabel: string | null;
  /** `basis`: «cargos» (VirtualPOS, TCH) o «transacciones» (Toku, Payku) según lo que el canal marca como rechazado (UI-29). */
  rejectedCharges: { count: number | null; amount: number | null; basis?: "cargos" | "transacciones"; basisLabel?: string };
  note?: string;
  /** Solo TCH: recaudo aceptado del último período (reportes Excel oficiales). */
  monthlyCollection?: MonthlyCollection;
};

export const PAYKU_COVERAGE_NOTE = "Cobertura histórica no certificada";
export const TCH_SOURCE_NOTE = "Fuente: reportes Excel oficiales";

export const CHANNEL_KPI_NOTES: Partial<Record<Channel, string>> = {
  payku: `${PAYKU_COVERAGE_NOTE} · MRR desde última transacción success`,
  toku: "MRR desde suscripciones activas efectivas (no eliminadas y con medio de pago cobrable) · Campos específicos de Toku",
  tch: TCH_SOURCE_NOTE,
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
function label(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

/**
 * `fallbackChurnLabel`: etiqueta de ventana del churn a nivel de payload (por si el backend la
 * envía fuera de `kpis`). La del propio bloque `kpis` tiene prioridad.
 */
export function normalizeKpis(channel: Channel, raw: unknown, fallbackChurnLabel?: unknown): ChannelKpis {
  const k = rec(raw);
  const rejected = rec(k.rejected_charges);
  const collection = k.recaudo_mensual !== null && typeof k.recaudo_mensual === "object" ? rec(k.recaudo_mensual) : null;
  return {
    mrr: num(k.mrr),
    arpu: num(k.arpu),
    activeSubscribers: num(k.active_subscribers),
    activeClients: num(k.active_clients),
    churnRate: num(k.churn_rate),
    ltv: num(k.ltv),
    churnWindowLabel: label(k.churn_window_label) ?? label(fallbackChurnLabel),
    rejectedCharges: {
      count: num(rejected.count),
      amount: num(rejected.amount),
      ...(rejected.basis === "cargos" || rejected.basis === "transacciones" ? { basis: rejected.basis } : {}),
      ...(label(rejected.basis_label) ? { basisLabel: label(rejected.basis_label) as string } : {}),
    },
    note: CHANNEL_KPI_NOTES[channel],
    ...(collection
      ? {
          monthlyCollection: {
            period: typeof collection.period === "string" ? collection.period : null,
            mrr: num(collection.mrr),
            acceptedTransactions: num(collection.accepted_transactions) ?? num(collection.active_clients),
            arpu: num(collection.arpu),
            rejectedCount: num(collection.rejected_count),
            rejectedAmount: num(collection.rejected_amount),
          },
        }
      : {}),
  };
}
