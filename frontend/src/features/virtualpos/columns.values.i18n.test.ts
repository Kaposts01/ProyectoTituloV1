import { beforeEach, describe, expect, it, vi } from "vitest";
import { paykuColumns, tokuColumns, tokuRelatedColumns, virtualPosColumns } from "./columns";
import { resetUnknownWarnings } from "../../i18n/label";
import { paykuSubscription, rec, tokuSubscription, vpCharge, vpClient, vpPayment, vpSubscription } from "../../test/fixtures";
import type { StagingRecord, TableColumn } from "../shared/types";

beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

const cell = (columns: TableColumn[], label: string, r: unknown) => columns.find((c) => c.label === label)!.value(r as StagingRecord);

describe("columnas «Estado»: el valor del proveedor se muestra en español", () => {
  it("VirtualPOS: cliente, suscripción, cargo y transacción", () => {
    expect(cell(virtualPosColumns("client"), "Estado", vpClient(1, { status: "ACTIVO" }))).toBe("Activo");
    expect(cell(virtualPosColumns("client"), "Estado", vpClient(1, { status: "BLOQUEADO" }))).toBe("Bloqueado");
    expect(cell(virtualPosColumns("subscription"), "Estado", vpSubscription(1, { status: "ACTIVA" }))).toBe("Activa");
    expect(cell(virtualPosColumns("subscription"), "Estado", vpSubscription(1, { status: "CANCELADA" }))).toBe("Cancelada");
    expect(cell(virtualPosColumns("subscription"), "Estado sec.", vpSubscription(1))).toBe("Cobrable");
    expect(cell(virtualPosColumns("charge"), "Estado", vpCharge(1, "pendiente"))).toBe("Pendiente");
    expect(cell(virtualPosColumns("charge"), "Estado", vpCharge(1, "RECHAZADO"))).toBe("Rechazado");
    expect(cell(virtualPosColumns("payment"), "Estado", vpPayment(1))).toBe("Pagado");
  });

  it("Toku: suscripción, medio de pago, deuda y relacionados", () => {
    expect(cell(tokuColumns("subscription"), "Estado", tokuSubscription(1))).toBe("Activa");
    expect(cell(tokuColumns("subscription"), "Estado", tokuSubscription(1, { status: "PAUSED" }))).toBe("Pausada");
    expect(cell(tokuColumns("subscription"), "Estado sec.", tokuSubscription(1, {}, { secondary_status: "nunca_cobrado" }))).toBe("Nunca cobrado");
    expect(cell(tokuColumns("payment_method"), "Estado", rec("toku", "payment_method", "pm-1", { payment_method: { status: "ACTIVE" } }))).toBe("Activa");
    expect(cell(tokuColumns("invoice"), "Estado", rec("toku", "invoice", "inv-1", { status: "PAID" }))).toBe("Pagado");
    expect(cell(tokuRelatedColumns("customer"), "Estado", rec("toku", "customer", "c-1", { status: "active" }))).toBe("Activa");
  });

  it("Payku: plan, suscripción y transacción", () => {
    expect(cell(paykuColumns("subscription"), "Estado", paykuSubscription(1))).toBe("Activa");
    expect(cell(paykuColumns("subscription"), "Estado sec.", paykuSubscription(1))).toBe("Cobrable");
    expect(cell(paykuColumns("plan"), "Estado", rec("payku", "plan", "p-1", { status: "inactive" }))).toBe("Inactiva");
    expect(cell(paykuColumns("transaction"), "Estado", rec("payku", "transaction", "t-1", { status: "success" }))).toBe("Exitoso");
  });

  it("ausente da «Sin dato» (y «—» en el secundario); un valor desconocido da «Desconocido (X)»", () => {
    expect(cell(virtualPosColumns("subscription"), "Estado", vpSubscription(1, { status: null }))).toBe("Sin dato");
    expect(cell(virtualPosColumns("subscription"), "Estado sec.", vpSubscription(1, {}, { secondary_status: null }))).toBe("—");
    expect(cell(virtualPosColumns("subscription"), "Estado", vpSubscription(1, { status: "ZZ_NEW" }))).toBe("Desconocido (ZZ_NEW)");
    expect(cell(virtualPosColumns("subscription"), "Estado sec.", vpSubscription(1, {}, { secondary_status: "ZZ" }))).toBe("Desconocido (ZZ)");
  });
});
