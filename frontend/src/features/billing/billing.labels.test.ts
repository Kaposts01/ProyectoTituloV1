import { describe, expect, it } from "vitest";

import { EVENT_LABELS, eventLabel } from "./billingLabels";

describe("etiquetas de eventos de la línea de tiempo", () => {
  it("traduce todos los tipos de evento que emite el backend", () => {
    // Tipos que escriben billing_requests y billing_apply (CHECK ck_bcre_event_type de la migración 0038).
    const emitidos = [
      "creada", "aprobada", "autoaprobada", "rechazada", "retirada", "expirada",
      "aplicando", "aplicada", "fallida", "reintentada", "requiere_conciliacion", "no_ejecutable",
    ];
    for (const tipo of emitidos) {
      expect(EVENT_LABELS[tipo], `falta la etiqueta de «${tipo}»`).toBeTruthy();
    }
  });

  it("el evento aplicada se muestra traducido y no en crudo", () => {
    expect(eventLabel("aplicada")).toBe("Cambio aplicado");
  });

  it("un tipo desconocido cae a un texto legible sin romper", () => {
    expect(eventLabel("tipo_nuevo")).toBe("tipo nuevo");
  });
});
