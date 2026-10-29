import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { es, IDENTIFIER_DOMAINS, type Domain } from "./es";
import { label, labelOr, normalizeKey, resetUnknownWarnings, tryLabel, unknownLabel } from "./label";
import { STATUS_KEYWORDS } from "../statusColors";

/** Palabras en inglés que NUNCA pueden aparecer en un texto traducido (palabra completa, sin distinguir mayúsculas). */
export const ENGLISH_TOKENS = /\b(active|paid|unpaid|failed|failure|success|successful|pending|true|false|completed|running|cancelled|canceled|rejected|paused|status|email|mail|queued|partial|deleted|expired|waiting|processing|card|bank|high|medium|low)\b/i;

const domains = Object.keys(es) as Domain[];

describe("normalizeKey", () => {
  it("quita tildes, pasa a minúsculas y trata «_» y «-» como espacio", () => {
    expect(normalizeKey("  ACTIVE ")).toBe("active");
    expect(normalizeKey("Nunca_Cobrado")).toBe("nunca cobrado");
    expect(normalizeKey("sync-virtualpos")).toBe("sync virtualpos");
    expect(normalizeKey("Débito")).toBe("debito");
    expect(normalizeKey(null)).toBe("");
  });
});

describe("catálogo es.ts", () => {
  it.each(domains.filter((d) => !IDENTIFIER_DOMAINS.includes(d)))("las claves del dominio «%s» ya están normalizadas", (domain) => {
    for (const key of Object.keys(es[domain])) expect(normalizeKey(key)).toBe(key);
  });

  it.each(IDENTIFIER_DOMAINS)("las claves del dominio de identificadores «%s» están en minúsculas", (domain) => {
    for (const key of Object.keys(es[domain])) expect(key).toBe(key.toLowerCase());
  });

  it.each(domains)("todo texto del dominio «%s» está en español: sin palabras inglesas conocidas ni vacío", (domain) => {
    for (const [key, text] of Object.entries(es[domain] as Record<string, string>)) {
      expect(text.trim(), `${domain}.${key} vacío`).not.toBe("");
      expect(ENGLISH_TOKENS.test(text), `${domain}.${key} = «${text}»`).toBe(false);
    }
  });

  it("cada código conocido se traduce a su texto, sea cual sea la grafía de entrada", () => {
    for (const domain of domains) {
      for (const [key, text] of Object.entries(es[domain] as Record<string, string>)) {
        expect(label(domain, key)).toBe(text);
        expect(label(domain, key.toUpperCase())).toBe(text);
      }
    }
  });

  it("estados reales de los proveedores", () => {
    expect(label("status", "ACTIVE")).toBe("Activa");
    expect(label("status", "active")).toBe("Activa");
    expect(label("status", "ACTIVA")).toBe("Activa");
    expect(label("status", "ACTIVO")).toBe("Activo");
    expect(label("status", "CANCELLED")).toBe("Cancelada");
    expect(label("status", "PAUSED")).toBe("Pausada");
    expect(label("status", "Paid")).toBe("Pagado");
    expect(label("status", "FAILED")).toBe("Fallido");
    expect(label("status", "PENDING")).toBe("Pendiente");
    expect(label("tchStatus", "VIGENTE")).toBe("Vigente");
    expect(label("secondaryStatus", "nunca_cobrado")).toBe("Nunca cobrado");
    expect(label("runStatus", "completed")).toBe("Completada");
    expect(label("phase", "sync_virtualpos")).toBe("Sincronización de VirtualPOS");
    expect(label("channel", "virtualpos1")).toBe("VirtualPOS 1");
    expect(label("boolean", true)).toBe("Sí");
    expect(label("boolean", "F")).toBe("No");
    expect(label("resource", "payment_method")).toBe("Método de pago");
    expect(label("resourcePlural", "subscription")).toBe("Suscripciones");
    expect(label("field", "phone_number")).toBe("Teléfono");
    expect(label("cardType", "TC")).toBe("Tarjeta de crédito");
  });
});

describe("valor desconocido o ausente", () => {
  let warn: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    resetUnknownWarnings();
    warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => warn.mockRestore());

  it("un valor que el catálogo no conoce se muestra como «Desconocido (X)» y conserva el valor", () => {
    expect(label("status", "ZZ_NEW")).toBe("Desconocido (ZZ_NEW)");
    expect(label("channel", "otro")).toBe("Desconocido (otro)");
    expect(unknownLabel(" X ")).toBe("Desconocido (X)");
  });

  it("emite un console.warn en desarrollo, una sola vez por dominio y valor", () => {
    label("status", "ZZ_NEW");
    label("status", "ZZ_NEW");
    label("phase", "ZZ_NEW");
    expect(warn).toHaveBeenCalledTimes(2);
    expect(String(warn.mock.calls[0][0])).toContain("ZZ_NEW");
  });

  it("tryLabel devuelve undefined (sin avisar) y los valores ausentes dan «Sin dato»", () => {
    expect(tryLabel("status", "ZZ_NEW")).toBeUndefined();
    expect(tryLabel("status", null)).toBeUndefined();
    expect(warn).not.toHaveBeenCalled();
    expect(label("status", null)).toBe("Sin dato");
    expect(label("status", undefined)).toBe("Sin dato");
    expect(label("status", "")).toBe("Sin dato");
    expect(labelOr("status", null, "—")).toBe("—");
    expect(labelOr("status", "paid", "—")).toBe("Pagado");
  });
});

describe("cobertura frente a statusColors", () => {
  it("cada raíz que statusColors reconoce tiene al menos una entrada traducida en el catálogo de estados", () => {
    const keys = [...Object.keys(es.status), ...Object.keys(es.tchStatus), ...Object.keys(es.runStatus), ...Object.keys(es.secondaryStatus)];
    for (const [, stems] of STATUS_KEYWORDS) {
      for (const stem of stems) expect(keys.some((k) => k.includes(stem)), `sin entrada para la raíz «${stem}»`).toBe(true);
    }
  });
});
