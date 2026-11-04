import { describe, expect, it } from "vitest";
import { adaptAlert, adaptAlertDetailItem, adaptAlertDetailItems, adaptAlerts } from "./alertAdapter";
import { adaptGeneralClientDetail } from "./generalClientAdapter";

describe("alertAdapter: alertas", () => {
  it.each([
    ["sev", "severity", "alta"], ["tipo", "kind", "Rechazos altos"], ["canal", "channel", "Toku"],
    ["detalle", "detail", "12 cargos"], ["periodo", "period", "2026-05"], ["id", "id", "a1"],
  ])("%s pasa a %s", (wireKey, domainKey, value) => {
    const alert = adaptAlert({ [wireKey]: value } as never) as unknown as Record<string, unknown>;
    expect(alert[domainKey]).toBe(value);
  });
  it("valores ausentes: textos vacíos, severidad «baja» y sin id ni periodo", () => {
    expect(adaptAlert({})).toEqual({ severity: "baja", kind: "", channel: "", detail: "" });
    expect(adaptAlert({ sev: null, tipo: null, canal: null, detalle: null, periodo: null })).toEqual({ severity: "baja", kind: "", channel: "", detail: "" });
  });
  it("severidad con otras mayúsculas o desconocida", () => {
    expect(adaptAlert({ sev: "ALTA" }).severity).toBe("alta");
    expect(adaptAlert({ sev: "zz" }).severity).toBe("baja");
  });
  it("una lista ausente da lista vacía", () => {
    expect(adaptAlerts(undefined)).toEqual([]);
    expect(adaptAlerts(null)).toEqual([]);
    expect(adaptAlerts([{ sev: "media", tipo: "T", canal: "C", detalle: "1" }])).toHaveLength(1);
  });
});

describe("alertAdapter: detalle de una alerta", () => {
  it.each([
    ["external_id", "externalId", "s1"], ["rut", "rut", "11111111-1"], ["status", "status", "ACTIVE"], ["amount", "amount", 1000],
    ["suscription_date", "subscriptionDate", "2025-01-01"], ["ultimo_cobro", "lastCharge", "2025-03-01"],
    ["ultimo_estado", "lastChargeStatus", "FAILED"], ["intentos", "attempts", 2],
  ])("%s pasa a %s", (wireKey, domainKey, value) => {
    const item = adaptAlertDetailItem({ [wireKey]: value } as never) as unknown as Record<string, unknown>;
    expect(item[domainKey]).toBe(value);
  });
  it("las columnas opcionales ausentes siguen ausentes (la tabla no las muestra) y las nulas siguen nulas", () => {
    const bare = adaptAlertDetailItem({});
    expect(bare).toEqual({ externalId: null, rut: null, status: null, amount: 0, subscriptionDate: null });
    expect("lastCharge" in bare).toBe(false);
    expect(adaptAlertDetailItem({ ultimo_cobro: null }).lastCharge).toBeNull();
    expect(adaptAlertDetailItem({ intentos: 0 }).attempts).toBe(0);
  });
  it("lista ausente da lista vacía", () => {
    expect(adaptAlertDetailItems(undefined)).toEqual([]);
  });
});

describe("generalClientAdapter: ficha general", () => {
  it.each([
    ["clients", "id_cliente"], ["subscriptions", "id_subscription"], ["charges", "id_cargo"], ["transactions", "id_transaccion"],
  ])("%s: %s pasa a internalId", (section, key) => {
    const adapted = adaptGeneralClientDetail({ rut: "11111111-1", [section]: [{ portal: "Toku", [key]: "X-1", external_id: "e1" }] } as never);
    expect((adapted as unknown as Record<string, unknown[]>)[section]).toEqual([{ portal: "Toku", internalId: "X-1", externalId: "e1", status: null, amount: null }]);
  });
  it("estado y monto se conservan y los ausentes quedan en null; sin datos, secciones vacías", () => {
    const d = adaptGeneralClientDetail({ rut: "r", charges: [{ portal: "VirtualPOS", id_cargo: "G-1", external_id: "g1", status: "pagado", amount: "10000" }] });
    expect(d.charges[0]).toEqual({ portal: "VirtualPOS", internalId: "G-1", externalId: "g1", status: "pagado", amount: "10000" });
    expect(adaptGeneralClientDetail(null)).toEqual({ rut: "", clients: [], subscriptions: [], charges: [], transactions: [] });
  });
});
