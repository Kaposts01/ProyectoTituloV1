import { describe, expect, it } from "vitest";
import { fieldLabel, renewalText } from "./utils";

describe("renewalText: booleanos en español", () => {
  it.each([["T", "Sí"], ["t", "Sí"], [true, "Sí"], ["true", "Sí"], ["True", "Sí"], ["1", "Sí"], ["F", "No"], [false, "No"], ["false", "No"], ["False", "No"], ["0", "No"]])(
    "%s se muestra como %s",
    (value, expected) => expect(renewalText(value)).toBe(expected),
  );

  it("un valor que no es booleano se muestra tal cual y la ausencia da «Sin dato»", () => {
    expect(renewalText("Anual")).toBe("Anual");
    expect(renewalText(null)).toBe("Sin dato");
    expect(renewalText("")).toBe("Sin dato");
  });
});

describe("fieldLabel: clave de campo sin rótulo conocido", () => {
  it("se ve «Campo (clave)», nunca la clave sola con guiones bajos", () => {
    expect(fieldLabel("card_brand_x")).toBe("Campo (card_brand_x)");
    expect(fieldLabel("zz")).toBe("Campo (zz)");
  });

  it("las claves conocidas conservan su rótulo", () => {
    expect(fieldLabel("status")).toBe("Estado");
    expect(fieldLabel("last_paid_date")).toBe("Último cobro");
  });
});
