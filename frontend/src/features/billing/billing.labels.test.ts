import { describe, expect, it } from "vitest";

import { EVENT_LABELS, eventLabel, platformLabel, statusLabel, typeLabel } from "./billingLabels";

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

  it("un tipo desconocido se muestra como «Desconocido (X)», conservando el valor para soporte", () => {
    expect(eventLabel("tipo_nuevo")).toBe("Desconocido (tipo_nuevo)");
  });

  it("estado, tipo de solicitud y plataforma desconocidos tampoco se muestran crudos", () => {
    expect(statusLabel("zz_nuevo")).toBe("Desconocido (zz_nuevo)");
    expect(typeLabel("zz_nuevo")).toBe("Desconocido (zz_nuevo)");
    expect(platformLabel("virtualpos3")).toBe("Desconocido (virtualpos3)");
  });

  it("los conocidos siguen igual", () => {
    expect(statusLabel("pendiente")).toBe("Pendiente");
    expect(typeLabel("change_amount")).toBe("Cambio de monto");
    expect(platformLabel("virtualpos1")).toBe("VirtualPOS 1");
  });
});
