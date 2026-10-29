import { describe, expect, it } from "vitest";
import { cardTypeText, fieldLabel, renewalText, resourceTitle } from "./utils";
import { statusResourceLabels, virtualPosMetrics } from "./constants";
import { recurringFieldLabels, virtualPosClientFieldLabels } from "../virtualpos/constants";

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

describe("rótulos con tilde y «Suscripción» (paso 3)", () => {
  it("fieldLabel escribe las tildes y usa «suscripción»", () => {
    expect(fieldLabel("phone_number")).toBe("Teléfono");
    expect(fieldLabel("email")).toBe("Correo electrónico");
    expect(fieldLabel("description")).toBe("Descripción");
    expect(fieldLabel("automatic_renewal")).toBe("Renovación automática");
    expect(fieldLabel("subscription")).toBe("Suscripción");
    expect(fieldLabel("subscription_ids")).toBe("IDs suscripciones");
    expect(fieldLabel("payment_method")).toBe("Método de pago");
    expect(fieldLabel("postal_code")).toBe("Código postal");
  });

  it("cardTypeText y resourceTitle salen del catálogo; lo desconocido se marca", () => {
    expect(cardTypeText("TC")).toBe("Tarjeta de crédito");
    expect(cardTypeText("td")).toBe("Tarjeta de débito");
    expect(cardTypeText("PREPAGO")).toBe("Tarjeta prepago");
    expect(cardTypeText(null)).toBe("Sin dato");
    expect(cardTypeText("ZZ")).toBe("Desconocido (ZZ)");
    expect(resourceTitle("payment_method")).toBe("Método de pago");
    expect(resourceTitle("subscription")).toBe("Suscripción");
    expect(resourceTitle("zz")).toBe("Desconocido (zz)");
  });

  it("los mapas de recursos y de campos de VirtualPOS salen del mismo catálogo", () => {
    expect(statusResourceLabels.subscription).toBe("Suscripciones");
    expect(statusResourceLabels.payment_method).toBe("Métodos de pago");
    expect(virtualPosMetrics.filter((m) => /uscripciones/.test(m.label)).map((m) => m.label)).toEqual(["Suscripciones Activas", "Suscripciones Cobrables"]);
    expect(virtualPosClientFieldLabels.phone_number).toBe("Teléfono");
    expect(virtualPosClientFieldLabels.gender_id).toBe("Género");
    expect(recurringFieldLabels.max_active_invoices).toBe("Máximo de facturas activas");
    expect(recurringFieldLabels.creation_lead_days).toBe("Días de anticipación");
  });
});
