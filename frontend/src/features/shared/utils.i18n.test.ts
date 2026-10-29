import { describe, expect, it } from "vitest";
import { renewalText } from "./utils";

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
