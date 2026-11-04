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

describe("fieldValue: booleanos y valores enumerados (paso 6)", () => {
  it("un booleano de JSON se ve Sí o No en cualquier campo", () => {
    expect(fieldValue("is_active", true)).toBe("Sí");
    expect(fieldValue("show_in_terminal", false)).toBe("No");
    expect(fieldValue("anything", true)).toBe("Sí");
  });

  it("los campos booleanos que llegan como texto (true, T, 0) también", () => {
    expect(fieldValue("automatic_renewal", "true")).toBe("Sí");
    expect(fieldValue("renewal", "T")).toBe("Sí");
    expect(fieldValue("is_paid", "False")).toBe("No");
    expect(fieldValue("is_active", "0")).toBe("No");
  });

  it("frecuencia, moneda, tipo y marca de tarjeta", () => {
    expect(fieldValue("frequency_type", "monthly")).toBe("Mensual");
    expect(fieldValue("currency", "CLP")).toBe("CLP");
    expect(fieldValue("card_type", "TC")).toBe("Tarjeta de crédito");
    expect(fieldValue("card_type", "credit")).toBe("Tarjeta de crédito");
    expect(fieldValue("card_brand", "VISA")).toBe("Visa");
  });

  it("un valor desconocido de esos campos se ve «Desconocido (X)»", () => {
    expect(fieldValue("frequency_type", "fortnightly")).toBe("Desconocido (fortnightly)");
    expect(fieldValue("card_brand", "zzbrand")).toBe("Desconocido (zzbrand)");
    expect(fieldValue("is_active", "quizas")).toBe("Desconocido (quizas)");
  });

  it("el código de tipo de pago y la pasarela no tienen traducción conocida todavía", () => {
    expect(fieldValue("payment_type_code", "VN")).toBe("Desconocido (VN)");
    expect(fieldValue("gateway", "pasarela_x")).toBe("Desconocido (pasarela_x)");
  });
});
