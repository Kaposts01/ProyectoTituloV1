/**
 * Lote L8-QA: pruebas de los hallazgos del informe de QA del sandbox (2026-11-05) que no tienen un archivo de prueba
 * propio. Datos sintéticos.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, getJson: vi.fn() };
});
import { getJson } from "../api";
import { TOKU_REPORTS_PERMISSION, TokuReportsSection } from "../features/admin/TokuReportsSection";
import { failedChannelsLabel } from "../features/admin/schedulerLabels";
import { providerList } from "../features/dashboard/EtlPanel";
import { fullSyncProviders } from "../features/dashboard/useEtl";
import { statusFacetLabels } from "../features/general/UnifiedControls";
import { Rut } from "../features/shared/RutCell";
import { formatRut, rutText } from "../features/shared/rut";
import { chileDayOfMonth } from "../features/summary/summaryFormat";

afterEach(() => { cleanup(); vi.mocked(getJson).mockReset(); });

const read = (rel: string) => readFileSync(resolve(process.cwd(), "src", rel), "utf8").replace(/\r\n/g, "\n").replace(/\/\*[\s\S]*?\*\//g, "");

describe("QA-08: formato único del RUT (12.345.678-9)", () => {
  it.each([
    ["197292059", "19.729.205-9", true],
    ["19780113-1", "19.780.113-1", true],
    ["42.000.150-9", "42.000.150-9", true],
    ["12345670k", "12.345.670-K", true],
    ["11111111-2", "11.111.111-2", false],
  ])("%s se muestra %s (válido: %s)", (raw, text, valid) => {
    expect(formatRut(raw)).toEqual({ text, valid });
  });

  it("lo que no tiene forma de RUT queda tal cual y marcado; sin dato es el respaldo", () => {
    expect(formatRut("2222F3K92")).toEqual({ text: "2222F3K92", valid: false });
    expect(formatRut(null)).toBeNull();
    expect(rutText("", "Sin dato")).toBe("Sin dato");
  });

  it("el componente va en mono y marca el inválido con texto, no solo con color", () => {
    const { container } = render(<><Rut value="111111111" /><Rut value="2222F3K92" /><Rut value={null} /></>);
    expect(screen.getByText("11.111.111-1")).toHaveClass("mono", "rut");
    expect(container.querySelector(".rut-invalid")?.textContent).toBe("2222F3K92 no válido");
    expect(container.textContent).toContain("—");
  });
});

describe("QA-09: etiquetas del filtro Estado", () => {
  it("una etiqueta repetida lleva el canal; una única queda igual", () => {
    const labels = statusFacetLabels([
      { status: "PAID", count: 3, channels: ["toku"] },
      { status: "pagado", count: 2, channels: ["virtualpos"] },
      { status: "RECHAZADA", count: 1, channels: ["tch"] },
    ]);
    expect(labels.get("PAID")).toBe("Pagado · Toku");
    expect(labels.get("pagado")).toBe("Pagado · VirtualPOS");
    expect(labels.get("RECHAZADA")).toBe("Rechazada");
  });

  it("sin canal (backend antiguo) o con el mismo canal, usa el texto crudo para distinguirlas", () => {
    const old = statusFacetLabels([{ status: "PAID", count: 1 }, { status: "paid", count: 1 }]);
    expect(new Set(old.values()).size).toBe(2);
    const same = statusFacetLabels([{ status: "PAID", count: 1, channels: ["toku"] }, { status: "paid", count: 1, channels: ["toku"] }]);
    expect([...same.values()]).toEqual(["Pagado · Toku (PAID)", "Pagado · Toku (paid)"]);
  });
});

describe("QA-02: la confirmación del Sync completo nombra los canales", () => {
  it("lista los canales habilitados en español", () => {
    expect(providerList(fullSyncProviders(() => true))).toBe("VirtualPOS, Toku y Payku");
    expect(providerList(fullSyncProviders((channel) => channel !== "payku"))).toBe("VirtualPOS y Toku");
    expect(providerList(["toku"])).toBe("Toku");
  });
});

describe("QA-07: día del mes en hora de Chile", () => {
  it("usa America/Santiago, no UTC", () => {
    // 2026-11-05 01:30 UTC es todavía el 4 de noviembre en Chile (UTC-3)
    expect(chileDayOfMonth(Date.UTC(2026, 10, 5, 1, 30))).toBe(4);
    expect(chileDayOfMonth(Date.UTC(2026, 10, 5, 15, 0))).toBe(5);
  });
});

describe("QA-15: canales que fallaron en una corrida del Historial", () => {
  it("se nombran; sin fallos no hay texto", () => {
    expect(failedChannelsLabel(["toku"])).toBe("Falló: Toku");
    expect(failedChannelsLabel(["toku", "payku"])).toBe("Falló: Toku, Payku");
    expect(failedChannelsLabel(null)).toBeNull();
    expect(failedChannelsLabel([])).toBeNull();
  });
});

describe("Desbordes en móvil", () => {
  const app = read("App.css");
  const billing = read("features/billing/billing.css");

  it("QA-03: la grilla de reportes no se ensancha con su tabla más ancha", () => {
    expect(app).toMatch(/\.platform-reports \{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
    expect(app).toMatch(/\.platform-reports > \* \{ min-width: 0; \}/);
  });

  it("QA-03: la tabla de reportes de Toku va dentro de .table-wrap (scroll propio)", async () => {
    vi.mocked(getJson).mockResolvedValue({
      max_age_days: 7, stale_types: [],
      reports: [{ report_type: "pagos", generated_at: "2026-10-30T09:00:00+00:00", loaded_at: "2026-10-31T10:00:00+00:00", rows_total: 12345, age_days: 3, is_stale: false }],
    });
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    const cell = await screen.findByText("12.345");
    expect(cell.closest("table")?.parentElement).toHaveClass("table-wrap");
  });

  it("QA-03/QA-11: las tablas de Administración y Sincronización están envueltas en un contenedor con scroll", () => {
    for (const file of ["UsersSubPanel", "RolesSubPanel", "TokuReportsSection", "WebhookHealthPanel", "RunResourceStats"]) {
      const source = readFileSync(resolve(process.cwd(), "src/features/admin", `${file}.tsx`), "utf8");
      const tables = source.match(/<table\b/g)?.length ?? 0;
      const wrapped = source.match(/<div className="table-wrap">\s*<table\b/g)?.length ?? 0;
      expect(wrapped, file).toBe(tables);
    }
    const scheduler = readFileSync(resolve(process.cwd(), "src/features/admin/SchedulerPanel.tsx"), "utf8");
    expect(scheduler).toMatch(/<div className="table-scroll">\s*<table className="scheduler-jobs-table runs-table">/);
    expect(app).toMatch(/\.table-wrap \{ width: 100%; overflow-x: auto; \}/);
  });

  it("QA-12: en móvil la fila de alerta (también la sub-fila) usa una pista que puede encoger", () => {
    const mobile = app;
    expect(mobile).toMatch(/\.dashboard-alert-subrow \.dashboard-alert-row \{ grid-template-columns: 4\.5rem minmax\(0, 1fr\) auto;/);
    expect(mobile).toMatch(/\.dashboard-alert-row > \* \{ min-width: 0; overflow-wrap: anywhere; \}/);
    expect(mobile).toMatch(/\.dashboard-alert-tipo \{ grid-column: 2; white-space: normal; \}/);
  });

  it("QA-13: .bx-sr usa el patrón sr-only completo y .bx-tabs queda posicionado", () => {
    expect(billing).toMatch(/\.bx-sr \{[^}]*margin: -1px;[^}]*clip-path: inset\(50%\)/);
    expect(billing).toMatch(/\.bx-tabs \{ position: relative;/);
  });
});
