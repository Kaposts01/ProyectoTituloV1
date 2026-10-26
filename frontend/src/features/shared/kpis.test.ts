import { describe, expect, it } from "vitest";
import { normalizeKpis, type Channel } from "./kpis";

const full = {
  mrr: 1000, arpu: 500, active_subscribers: 2, active_clients: 2, churn_rate: 1.5, ltv: 900,
  rejected_charges: { count: 3, amount: 1500 },
};

describe("normalizeKpis", () => {
  it.each(["virtualpos", "toku", "payku", "tch"] as Channel[])("mapea campos completos y tolera faltantes en %s", (channel) => {
    const k = normalizeKpis(channel, full);
    expect(k.mrr).toBe(1000);
    expect(k.activeSubscribers).toBe(2);
    expect(k.churnRate).toBe(1.5);
    expect(k.rejectedCharges).toEqual({ count: 3, amount: 1500 });
    for (const raw of [undefined, null, {}, "x"]) {
      const empty = normalizeKpis(channel, raw);
      expect(empty.mrr).toBeNull();
      expect(empty.rejectedCharges).toEqual({ count: null, amount: null });
    }
  });

  it("convierte numéricos string y descarta valores no finitos", () => {
    const k = normalizeKpis("toku", { mrr: "1500", arpu: " ", churn_rate: NaN, active_subscribers: Infinity, active_clients: "2" });
    expect(k.mrr).toBe(1500);
    expect(k.arpu).toBeNull();
    expect(k.churnRate).toBeNull();
    expect(k.activeSubscribers).toBeNull();
    expect(k.activeClients).toBe(2);
  });

  it("agrega notas solo para payku y tch", () => {
    expect(normalizeKpis("payku", {}).note).toBe("Cobertura histórica no certificada · MRR desde última transacción success");
    expect(normalizeKpis("tch", {}).note).toBe("Fuente: reportes Excel oficiales");
    expect(normalizeKpis("toku", {}).note).toBe("MRR desde suscripciones activas con medio de pago chargeable · Campos específicos de Toku");
    expect(normalizeKpis("virtualpos", {}).note).toBeUndefined();
  });

  it("mapea el bloque recaudo_mensual de TCH y lo omite si falta", () => {
    const k = normalizeKpis("tch", {
      ...full,
      recaudo_mensual: { period: "2026-09", mrr: 46687623, accepted_transactions: 5644, active_clients: 1, arpu: 8272, rejected_count: 10, rejected_amount: 90000 },
    });
    expect(k.recaudoMensual).toEqual({
      period: "2026-09", mrr: 46687623, acceptedTransactions: 5644, arpu: 8272, rejectedCount: 10, rejectedAmount: 90000,
    });
    const legacy = normalizeKpis("tch", { recaudo_mensual: { active_clients: 7 } });
    expect(legacy.recaudoMensual?.acceptedTransactions).toBe(7);
    expect(normalizeKpis("tch", full).recaudoMensual).toBeUndefined();
    expect(normalizeKpis("tch", { recaudo_mensual: null }).recaudoMensual).toBeUndefined();
  });
});
