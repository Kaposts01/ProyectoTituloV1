import { describe, expect, it } from "vitest";
import { currentAmount, requestedAmount } from "./recoveryAdapter";

describe("recoveryAdapter", () => {
  it("monto pasa a requestedAmount y monto_vigente a currentAmount", () => {
    const row = { source: "virtualpos1", monto: 12500, monto_vigente: 9900 };
    expect(requestedAmount(row)).toBe(12500);
    expect(currentAmount(row)).toBe(9900);
  });
  it("sin las claves devuelve undefined (la pantalla decide el respaldo)", () => {
    expect(requestedAmount({ source: "toku" })).toBeUndefined();
    expect(currentAmount({ source: "toku" })).toBeUndefined();
  });
  it("un monto 0 se conserva como 0", () => {
    expect(requestedAmount({ monto: 0 })).toBe(0);
  });
});
