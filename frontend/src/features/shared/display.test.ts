import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetUnknownWarnings } from "../../i18n/label";
import { fieldValue } from "./display";

beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("fieldValue: valor de un campo de ficha", () => {
  it("traduce los campos de estado", () => {
    expect(fieldValue("status", "ACTIVE")).toBe("Activa");
    expect(fieldValue("status", "CANCELADA")).toBe("Cancelada");
    expect(fieldValue("secondary_status", "nunca_cobrado")).toBe("Nunca cobrado");
    expect(fieldValue("charge_status", "pagada")).toBe("Pagada");
  });

  it("un estado desconocido se ve «Desconocido (X)»", () => {
    expect(fieldValue("status", "ZZ_NEW")).toBe("Desconocido (ZZ_NEW)");
  });

  it("deja los demás campos como texto y la ausencia como «Sin dato»", () => {
    expect(fieldValue("name", "Plan Sintético")).toBe("Plan Sintético");
    expect(fieldValue("amount", 10000)).toBe("10000");
    expect(fieldValue("status", null)).toBe("Sin dato");
    expect(fieldValue("status", "")).toBe("Sin dato");
    expect(fieldValue("client", { social_id: "1" })).toBe('{"social_id":"1"}');
  });
});
