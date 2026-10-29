import { describe, expect, it } from "vitest";
import {
  adaptTchClient, adaptTchClientDetail, adaptTchClientsPage, adaptTchSubscription, adaptTchSubscriptionDetail,
  adaptTchSubscriptionsPage, adaptTchSummary, adaptTchTransaction, adaptTchTransactionDetail, adaptTchTransactionsPage,
  provisionalTchClientDetail, provisionalTchSubscriptionDetail, provisionalTchTransactionDetail,
} from "./tchAdapter";

/** [clave del backend, clave interna, valor de prueba]: una fila por clave. Datos sintéticos. */
const SUBSCRIPTION_KEYS: Array<[string, string, unknown]> = [
  ["id", "id", "sub-1"], ["numero_ficha", "fileNumber", 1001], ["numero_mandato", "mandateNumber", 7],
  ["cliente_rut", "clientRut", "11111111-1"], ["banco_nombre", "bankName", "Banco Sintético"], ["tipo_mandato", "mandateType", "FISICO"],
  ["tipo_cuenta", "accountType", "CORRIENTE"], ["origen", "origin", "CALLE"], ["centro_costo", "costCenter", "CC-1"],
  ["captador", "recruiter", "Captador Uno"], ["monto", "amount", "10000"], ["fecha_activacion", "activationDate", "2025-01-15"],
  ["equivalente_pesos", "pesoEquivalent", "10500"], ["fecha_rechazo", "rejectionDate", "2025-02-01"], ["fecha_eliminacion", "deletionDate", "2025-03-01"],
  ["fecha_fin", "endDate", "2025-04-01"], ["razon_baja", "cancellationReason", "Motivo sintético"], ["estado", "status", "VIGENTE"],
  ["last_paid_date", "lastPaidDate", "2025-03-10T00:00:00"], ["secondary_status", "secondaryStatus", "cobrable"],
  ["created_at", "createdAt", "2025-01-01T00:00:00"], ["updated_at", "updatedAt", "2025-01-02T00:00:00"],
];
const TRANSACTION_KEYS: Array<[string, string, unknown]> = [
  ["id", "id", "trx-1"], ["numero_ficha", "fileNumber", 1001], ["periodo", "period", "2025-03"], ["numero_cuota", "installmentNumber", "3"],
  ["total_cuotas", "totalInstallments", "12"], ["monto", "amount", "10000"], ["fecha_cargo", "chargeDate", "2025-03-05"],
  ["tipo_transaccion", "transactionType", "COBRO"], ["estado", "status", "ACEPTADA"], ["entidad_recaudadora", "collectingEntity", "Entidad Sintética"],
  ["razon_rechazo", "rejectionReason", "Fondos insuficientes"], ["archivo_origen", "sourceFile", "reporte-2025-03.xlsx"],
];
const CLIENT_KEYS: Array<[string, string, unknown]> = [
  ["id", "id", "cli-1"], ["rut", "rut", "22222222-2"], ["nombre", "firstName", "Nombre1"], ["apellido", "lastName", "Apellido1"],
  ["fecha_nacimiento", "birthDate", "1990-01-01"], ["profesion", "profession", "Profesión Sintética"], ["tipo_persona", "personType", "NATURAL"],
  ["tipo_socio", "memberType", "REGULAR"], ["telefono", "phone", "000"], ["email", "email", "socio1@example.invalid"],
  ["direccion", "address", "Calle 1"], ["comuna", "commune", "Comuna Uno"], ["ciudad", "city", "Ciudad Uno"],
];

describe("tchAdapter: una prueba por clave del backend", () => {
  it.each(SUBSCRIPTION_KEYS)("suscripción: %s pasa a %s", (wireKey, domainKey, value) => {
    const adapted = adaptTchSubscription({ [wireKey]: value } as never) as unknown as Record<string, unknown>;
    expect(adapted[domainKey]).toBe(typeof value === "number" && !["fileNumber", "mandateNumber"].includes(domainKey) ? String(value) : value);
  });
  it.each(TRANSACTION_KEYS)("transacción: %s pasa a %s", (wireKey, domainKey, value) => {
    const adapted = adaptTchTransaction({ [wireKey]: value } as never) as unknown as Record<string, unknown>;
    expect(adapted[domainKey]).toBe(value);
  });
  it.each(CLIENT_KEYS)("cliente: %s pasa a %s", (wireKey, domainKey, value) => {
    const adapted = adaptTchClient({ [wireKey]: value } as never) as unknown as Record<string, unknown>;
    expect(adapted[domainKey]).toBe(value);
  });

  it("el resultado no conserva ninguna clave en español del backend", () => {
    const wire = Object.fromEntries(SUBSCRIPTION_KEYS.map(([k, , v]) => [k, v]));
    const keys = Object.keys(adaptTchSubscription(wire as never));
    for (const [wireKey] of SUBSCRIPTION_KEYS.filter(([k, d]) => k !== d)) expect(keys).not.toContain(wireKey);
  });
});

describe("tchAdapter: valores ausentes", () => {
  it("una suscripción vacía deja textos en null, estado vacío y ficha 0 (no inventa datos)", () => {
    const s = adaptTchSubscription({});
    expect(s.fileNumber).toBe(0);
    expect(s.status).toBe("");
    expect(s.secondaryStatus).toBe("");
    for (const key of ["mandateNumber", "clientRut", "bankName", "amount", "pesoEquivalent", "endDate", "lastPaidDate", "createdAt"] as const) {
      expect(s[key], key).toBeNull();
    }
  });
  it("null/undefined completos no revientan", () => {
    expect(adaptTchSubscription(null).fileNumber).toBe(0);
    expect(adaptTchTransaction(undefined).status).toBe("");
    expect(adaptTchClient(null).rut).toBe("");
    expect(adaptTchSummary(null).subscriptions.total).toBe(0);
  });
  it("monto 0 se conserva como \"0\" y un monto nulo queda en null", () => {
    expect(adaptTchSubscription({ monto: 0 }).amount).toBe("0");
    expect(adaptTchSubscription({ monto: null }).amount).toBeNull();
    expect(adaptTchTransaction({ numero_cuota: 0 }).installmentNumber).toBe("0");
  });
  it("tipos incorrectos se tratan como ausentes", () => {
    const s = adaptTchSubscription({ numero_ficha: "x" as never, estado: 5 as never, banco_nombre: {} as never });
    expect(s.fileNumber).toBe(0);
    expect(s.status).toBe("5");
    expect(s.bankName).toBeNull();
  });
});

describe("tchAdapter: detalles y páginas", () => {
  it("detalle de suscripción: transacciones a transactions", () => {
    const d = adaptTchSubscriptionDetail({ numero_ficha: 5, transacciones: [{ id: "t1", estado: "RECHAZADA", fecha_cargo: "2025-03-05" }] });
    expect(d.fileNumber).toBe(5);
    expect(d.transactions).toEqual([expect.objectContaining({ id: "t1", status: "RECHAZADA", chargeDate: "2025-03-05" })]);
    expect(adaptTchSubscriptionDetail({}).transactions).toEqual([]);
  });
  it("detalle de transacción: suscripcion a subscription (o null)", () => {
    expect(adaptTchTransactionDetail({ id: "t1", suscripcion: { cliente_rut: "11111111-1", banco_nombre: "Banco Sintético" } }).subscription).toEqual(
      expect.objectContaining({ clientRut: "11111111-1", bankName: "Banco Sintético" }),
    );
    expect(adaptTchTransactionDetail({ id: "t1" }).subscription).toBeNull();
    expect(adaptTchTransactionDetail({ id: "t1", suscripcion: null }).subscription).toBeNull();
  });
  it("detalle de cliente: suscripciones a subscriptions", () => {
    const d = adaptTchClientDetail({ rut: "22222222-2", suscripciones: [{ numero_ficha: 9, estado: "VIGENTE" }] });
    expect(d.subscriptions).toEqual([expect.objectContaining({ fileNumber: 9, status: "VIGENTE" })]);
    expect(adaptTchClientDetail({ rut: "x" }).subscriptions).toEqual([]);
  });
  it("las páginas convierten cada ítem y respetan total, page, limit y pages", () => {
    const wire = { total: 120, page: 2, limit: 50, pages: 3, items: [{ id: "a", numero_ficha: 1 }] };
    expect(adaptTchSubscriptionsPage(wire)).toEqual({ total: 120, page: 2, limit: 50, pages: 3, items: [expect.objectContaining({ id: "a", fileNumber: 1 })] });
    expect(adaptTchTransactionsPage({ items: [{ id: "t", estado: "ACEPTADA" }] }).items[0].status).toBe("ACEPTADA");
    expect(adaptTchClientsPage({ items: [{ rut: "r", nombre: "N" }] }).items[0].firstName).toBe("N");
  });
  it("una página ausente o sin items queda vacía con una sola página", () => {
    for (const page of [adaptTchSubscriptionsPage(null), adaptTchSubscriptionsPage({}), adaptTchSubscriptionsPage({ items: null })]) {
      expect(page).toEqual({ total: 0, page: 1, limit: 0, pages: 1, items: [] });
    }
  });
  it("los detalles provisionales solo traen la clave para pedir la ficha", () => {
    expect(provisionalTchSubscriptionDetail(77)).toEqual(expect.objectContaining({ fileNumber: 77, transactions: [] }));
    expect(provisionalTchTransactionDetail("t9")).toEqual(expect.objectContaining({ id: "t9", subscription: null }));
    expect(provisionalTchClientDetail("33333333-3")).toEqual(expect.objectContaining({ rut: "33333333-3", subscriptions: [] }));
  });
});

describe("tchAdapter: resumen", () => {
  const wire = {
    suscripciones: { vigentes: 40, eliminadas: 10, total: 50, monto_vigentes: 400000, monto_eliminadas: 100000, monto_total: 500000 },
    transacciones: { total: 200, aceptadas: 180, rechazadas: 20, tasa_rechazo_pct: 10, monto: 1800000 },
    kpis: { mrr: 400000, arpu: 10000, active_clients: 38, active_subscribers: 40, churn_rate: 2.5, ltv: 120000, churn_window_label: "mes calendario" },
    churn_window_label: "Promedio de 3 meses",
    years: [2024, 2025],
    transacciones_mensuales: [{ year: 2025, month: 3, status: "Aceptadas", count: 90, amount: 900000 }],
    transacciones_fuente: "transacciones",
    activaciones_mensuales: [{ year: 2025, month: 3, status: null, count: 5, amount: 50000 }],
    bajas_mensuales: [{ year: 2025, month: 3, status: null, count: 2, amount: 20000 }],
    active_subs_monthly: [{ year: 2025, month: 3, count: 40 }],
    churn_rate_monthly: [{ year: 2025, month: 3, rate: 2.5 }],
    ultimo_etl: { id: "etl-1", status: "completed", started_at: "2025-03-31T10:00:00", records_upserted: 1234 },
    alerts: [{ sev: "alta" as const, tipo: "t", canal: "tch", detalle: "d" }],
  };
  const s = adaptTchSummary(wire);

  it.each([
    ["suscripciones.vigentes", s.subscriptions.active, 40], ["suscripciones.eliminadas", s.subscriptions.deleted, 10],
    ["suscripciones.total", s.subscriptions.total, 50], ["suscripciones.monto_vigentes", s.subscriptions.activeAmount, 400000],
    ["suscripciones.monto_eliminadas", s.subscriptions.deletedAmount, 100000], ["suscripciones.monto_total", s.subscriptions.totalAmount, 500000],
    ["transacciones.total", s.transactions.total, 200], ["transacciones.aceptadas", s.transactions.accepted, 180],
    ["transacciones.rechazadas", s.transactions.rejected, 20], ["transacciones.tasa_rechazo_pct", s.transactions.rejectionRatePct, 10],
    ["transacciones.monto", s.transactions.amount, 1800000], ["churn_window_label", s.churnWindowLabel, "Promedio de 3 meses"],
    ["years", s.years, [2024, 2025]], ["transacciones_fuente", s.transactionsSource, "transacciones"],
    ["ultimo_etl.id", s.lastEtl.id, "etl-1"], ["ultimo_etl.status", s.lastEtl.status, "completed"],
    ["ultimo_etl.started_at", s.lastEtl.startedAt, "2025-03-31T10:00:00"], ["ultimo_etl.records_upserted", s.lastEtl.recordsUpserted, 1234],
    ["kpis.mrr", s.kpis.mrr, 400000], ["kpis.churn_rate", s.kpis.churn_rate, 2.5],
  ])("%s", (_key, actual, expected) => {
    expect(actual).toEqual(expected);
  });

  it("las series mensuales pasan sin cambios y las alertas pasan por el adaptador de alertas", () => {
    expect(s.monthlyTransactions).toEqual(wire.transacciones_mensuales);
    expect(s.monthlyActivations).toEqual(wire.activaciones_mensuales);
    expect(s.monthlyCancellations).toEqual(wire.bajas_mensuales);
    expect(s.activeSubsMonthly).toEqual(wire.active_subs_monthly);
    expect(s.churnRateMonthly).toEqual(wire.churn_rate_monthly);
    expect(s.alerts).toEqual([{ severity: "alta", kind: "t", channel: "tch", detail: "d" }]);
  });

  it("sin datos: ceros, listas vacías y ETL sin ejecutar (igual que el normalizador anterior)", () => {
    const empty = adaptTchSummary({});
    expect(empty.subscriptions).toEqual({ active: 0, deleted: 0, total: 0, activeAmount: 0, deletedAmount: 0, totalAmount: 0 });
    expect(empty.transactions).toEqual({ total: 0, accepted: 0, rejected: 0, rejectionRatePct: null, amount: 0 });
    expect(empty.kpis).toEqual({ mrr: 0, arpu: 0, active_clients: 0, active_subscribers: 0, churn_rate: 0, ltv: 0 });
    expect(empty.years).toEqual([]);
    expect(empty.transactionsSource).toBeUndefined();
    expect(empty.churnWindowLabel).toBeNull();
    expect(empty.lastEtl).toEqual({ id: null, status: null, startedAt: null, recordsUpserted: null });
    expect(empty.alerts).toEqual([]);
  });

  it("el churn_window_label de kpis sirve de respaldo y una tasa de rechazo nula sigue nula", () => {
    const r = adaptTchSummary({ kpis: { mrr: 1, churn_window_label: "ventana" }, transacciones: { tasa_rechazo_pct: null } });
    expect(r.churnWindowLabel).toBe("ventana");
    expect(r.transactions.rejectionRatePct).toBeNull();
    expect(r.kpis.arpu).toBeNull();
  });
});
