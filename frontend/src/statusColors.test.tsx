/// <reference types="node" />
import { cleanup, render } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { normalizeStatus, statusColor, statusKindColor, STATUS_KINDS } from "./statusColors";
import { chartStatusColor } from "./chartColors";
import { pivotByStatus } from "./components/chartRows";
import { StatusBars } from "./features/dashboard/StatusBars";
import { MonthlyStatusChart } from "./MonthlyStatusChart";

const barProps = vi.hoisted(() => [] as Record<string, unknown>[]);

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    Bar: (props: Record<string, unknown>) => {
      barProps.push(props);
      return <actual.Bar {...(props as object)} />;
    },
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div>{cloneElement(children, { width: 600, height: 220 })}</div>
    ),
  };
});

afterEach(cleanup);

const cases: Record<string, string[]> = {
  paid: ["pagado", "PAGADO", "Pagada", "paid", "PAID", "success", "SUCCESS", "Aceptadas", "aceptada", "COBRADO", "ACTIVE", "activa", "VIGENTE", "chargeable"],
  rejected: ["rechazado", "RECHAZADAS", "Rechazada", "rejected", "REJECTED", "failed", "FAILED", "PERMANENT_FAILED", "suscripcion_fallida", "SUSCRIPCION_FALLIDA"],
  pending: ["pendiente", "PENDING", "Pendientes", "REGISTER", "INITIALIZED", "Reintento"],
  processing: ["procesando", "PROCESSING", "Suscribiendo", "Cambio de tarjeta"],
  neutral: ["cancelado", "CANCELED", "cancelled", "Cancelada", "expirado", "EXPIRED", "anulado", "VOID", "void", "DELETE", "Eliminada", "PAUSED", "SUSPENDED", "ABORTED", "inactiva", "incobrable"],
  unknown: ["", "   ", "Sin estado", "zzz_nuevo", "otro"],
};

describe("normalizeStatus", () => {
  for (const [kind, names] of Object.entries(cases)) {
    it(`agrupa variantes de nombre en '${kind}'`, () => {
      for (const n of names) expect(normalizeStatus(n), n).toBe(kind);
    });
  }
  it("null/undefined son desconocido y no revienta con tipos raros", () => {
    expect(normalizeStatus(null)).toBe("unknown");
    expect(normalizeStatus(undefined)).toBe("unknown");
    expect(normalizeStatus(42 as unknown as string)).toBe("unknown");
  });
  it("tolera tildes, guiones y espacios", () => {
    expect(normalizeStatus("  Suscripción-Fallida ")).toBe("rejected");
    expect(normalizeStatus("Pendiente de pago")).toBe("pending");
  });
});

describe("statusColor", () => {
  it("todo estado devuelve un token CSS var(--status-*), nunca un hex fijo", () => {
    for (const names of Object.values(cases)) for (const n of names) expect(statusColor(n)).toMatch(/^var\(--status-[a-z]+\)$/);
  });
  it("pagado es el mismo color en cualquier idioma/capitalización y nunca naranja/ámbar", () => {
    const paid = statusColor("pagado");
    expect(paid).toBe("var(--status-paid)");
    for (const n of cases.paid) expect(statusColor(n)).toBe(paid);
    expect(paid).not.toBe(statusColor("pendiente"));
  });
  it("cancelado/expirado/anulado son gris neutro, distintos de rechazado", () => {
    for (const n of ["cancelado", "expirado", "anulado"]) expect(statusColor(n)).toBe("var(--status-neutral)");
    expect(statusColor("cancelado")).not.toBe(statusColor("rechazado"));
    expect(statusColor("desconocido-xyz")).toBe("var(--status-unknown)");
  });
  it("cada tipo tiene un color distinto", () => {
    const colors = STATUS_KINDS.map((k) => statusKindColor(k));
    expect(new Set(colors).size).toBe(STATUS_KINDS.length);
  });
});

describe("tema claro/oscuro", () => {
  const indexCss = readFileSync("src/index.css", "utf8");
  const darkAt = indexCss.indexOf('html[data-theme="dark"]');
  const light = indexCss.slice(0, darkAt);
  const dark = indexCss.slice(darkAt);
  it("cada token de estado está definido en :root y en el tema oscuro", () => {
    for (const kind of STATUS_KINDS) {
      expect(light, kind).toContain(`--status-${kind}:`);
      expect(dark, kind).toContain(`--status-${kind}:`);
    }
  });
});

describe("mismo estado, mismo color en barra, gráfico apilado y leyenda", () => {
  it("chartStatusColor y pivotByStatus usan el mapa único", () => {
    expect(chartStatusColor("Pagado")).toBe(statusColor("paid"));
    const { series } = pivotByStatus([
      { year: 2026, month: 1, status: "PAID", count: 1 },
      { year: 2026, month: 1, status: "cancelado", count: 1 },
      { year: 2026, month: 1, status: "FAILED", count: 1 },
    ]);
    const byKey = Object.fromEntries(series.map((s) => [s.key, s.color]));
    expect(byKey.PAID).toBe("var(--status-paid)");
    expect(byKey.cancelado).toBe("var(--status-neutral)");
    expect(byKey.FAILED).toBe("var(--status-rejected)");
  });

  it("StatusBars pinta segmento y leyenda con el color del estado", () => {
    const { container } = render(
      <StatusBars source="virtualpos" resources={{ charge: 6 }} statuses={[
        { resource: "charge", status: "PAGADO", count: 3 },
        { resource: "charge", status: "CANCELADO", count: 2 },
        { resource: "charge", status: "RECHAZADO", count: 1 },
      ]} />,
    );
    const kinds = [...container.querySelectorAll("[data-status-kind]")].map((el) => `${el.className.includes("segment") ? "seg" : "dot"}:${el.getAttribute("data-status-kind")}`);
    expect(kinds).toContain("seg:paid");
    expect(kinds).toContain("seg:neutral");
    expect(kinds).toContain("seg:rejected");
    expect(kinds).toContain("dot:paid");
    const seg = container.querySelector(".status-bar-segment[data-status-kind='paid']") as HTMLElement;
    expect(seg.style.background || seg.style.backgroundColor).toBe("var(--status-paid)");
  });

  it("MonthlyStatusChart colorea barras por estado con el mismo token que la barra de estados", () => {
    barProps.length = 0;
    render(
      <MonthlyStatusChart mode="count" year={null} data={[
        { year: 2026, month: 1, status: "PAGADO", count: 3, amount: 1 },
        { year: 2026, month: 1, status: "CANCELADO", count: 2, amount: 1 },
      ]} />,
    );
    const fills = barProps.map((p) => p.fill);
    expect(fills).toContain("var(--status-paid)");
    expect(fills).toContain("var(--status-neutral)");
    expect(fills).not.toContain("#DC2626");
  });

  it("los colores de CANAL siguen aparte (no se mezclan con estados)", () => {
    expect(chartStatusColor("VirtualPOS")).toBe("#2563EB");
    expect(chartStatusColor("Toku")).toBe("#7C3AED");
  });
});
