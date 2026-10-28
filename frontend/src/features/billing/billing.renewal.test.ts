import { describe, expect, it } from "vitest";
import {
  closeReasonLabel, CLOSE_REASON_GENERIC, daysText, EMPTY_RENEWAL_FILTERS, renewalAlertPath, renewalPath, renewalPriorityLabel,
  renewalPriorityTone, renewalStatusLabel, renewalStatusTone,
} from "./billingRenewal";

describe("renovaciones: etiquetas", () => {
  it("mapea estado y prioridad con texto y tono", () => {
    expect(renewalStatusLabel("abierta")).toBe("Abierta");
    expect(renewalStatusLabel("vencida")).toBe("Vencida");
    expect(renewalStatusLabel("cerrada")).toBe("Cerrada");
    expect(renewalStatusLabel("no_aplica")).toBe("No aplica");
    expect(renewalStatusTone("vencida")).toBe("error");
    expect(renewalStatusLabel("otra")).toBe("otra");
    expect(renewalPriorityLabel("alta")).toBe("Alta");
    expect(renewalPriorityLabel("normal")).toBe("Normal");
    expect(renewalPriorityTone("alta")).toBe("warning");
  });
});

describe("renovaciones: días", () => {
  it("usa los días del servidor y maneja el borde 0", () => {
    expect(daysText(5)).toBe("vence en 5 días");
    expect(daysText(1)).toBe("vence en 1 día");
    expect(daysText(0)).toBe("vence hoy");
    expect(daysText(-1)).toBe("vencida hace 1 día");
    expect(daysText(-12)).toBe("vencida hace 12 días");
    expect(daysText(null)).toBeNull();
  });
});

describe("renovaciones: close_reason", () => {
  it("mapea los valores reales del servicio", () => {
    expect(closeReasonLabel("Renovación ejecutada: el calendario se extendió.")).toBe("Renovación ejecutada: el calendario se extendió.");
    expect(closeReasonLabel("El calendario se extendió (sin solicitud de renovación asociada).")).toContain("sin solicitud");
    expect(closeReasonLabel("La suscripción ya no está ACTIVA (estado: CANCELADA).")).toBe("La suscripción dejó de estar activa (estado: CANCELADA).");
    expect(closeReasonLabel("La suscripción ya no está ACTIVA (estado: desconocido).")).toBe("La suscripción dejó de estar activa.");
    expect(closeReasonLabel("La suscripción ya no tiene un calendario modificado activo.")).toContain("calendario modificado activo");
  });
  it("valor desconocido o vacío no rompe ni se muestra crudo", () => {
    expect(closeReasonLabel("texto raro con 12.345.678-9")).toBe(CLOSE_REASON_GENERIC);
    expect(closeReasonLabel(null)).toBe("—");
    expect(closeReasonLabel("  ")).toBe("—");
  });
});

describe("renovaciones: consulta", () => {
  it("por defecto pide abierta y vencida (status repetible)", () => {
    const u = new URL(renewalPath(EMPTY_RENEWAL_FILTERS, 0, 25), "http://x");
    expect(u.pathname).toBe("/api/v1/billing/renewal-tasks");
    expect(u.searchParams.getAll("status")).toEqual(["abierta", "vencida"]);
    expect(u.searchParams.get("limit")).toBe("25");
    expect(u.searchParams.get("offset")).toBe("0");
    expect(u.searchParams.has("priority")).toBe(false);
  });
  it("aplica filtros y estados", () => {
    const u = new URL(renewalPath({ status: "all", priority: "alta", platform: "virtualpos2", subscription: " S-1 " }, 50, 25), "http://x");
    expect(u.searchParams.getAll("status")).toEqual(["abierta", "vencida", "cerrada", "no_aplica"]);
    expect(u.searchParams.get("priority")).toBe("alta");
    expect(u.searchParams.get("platform")).toBe("virtualpos2");
    expect(u.searchParams.get("subscription_id")).toBe("S-1");
    expect(u.searchParams.get("offset")).toBe("50");
    expect(new URL(renewalPath({ ...EMPTY_RENEWAL_FILTERS, status: "cerrada" }, 0, 25), "http://x").searchParams.getAll("status")).toEqual(["cerrada"]);
  });
  it("el contador pide solo altas abiertas/vencidas", () => {
    const u = new URL(renewalAlertPath(), "http://x");
    expect(u.searchParams.getAll("status")).toEqual(["abierta", "vencida"]);
    expect(u.searchParams.get("priority")).toBe("alta");
  });
});
