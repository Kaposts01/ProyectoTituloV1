import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { TchFileLoadsPanel } from "./TchFileLoadsPanel";
import { adaptTchFileLoads, controlBadge, controlDetail, shortDateTime, shortHash } from "./tchFileLoadsAdapter";

vi.mock("../../api", () => ({ getJson: vi.fn(), friendlyError: (_err: unknown, fallback: string) => fallback }));

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

describe("adaptTchFileLoads", () => {
  it("convierte el contrato y descarta filas sin hash", () => {
    const files = adaptTchFileLoads({
      items: [
        { sha256: SHA_A, archivo: "20261031 TCH IG OCTUBRE 2026.xlsx", periodo: "2026-10", cargado_en: "2026-11-02T10:05:00+00:00", filas: 1200, resultado: "cargado" },
        { archivo: "sin hash.xlsx" },
      ],
    });
    expect(files).toHaveLength(1);
    expect(files[0]).toMatchObject({ sha256: SHA_A, period: "2026-10", rows: 1200, result: "cargado", consolidatedAt: null });
  });

  it("TCH-PAR-11: toma los conteos totales y el control del Excel; null si no hay conciliación", () => {
    const [withStats, without] = adaptTchFileLoads({
      items: [
        {
          sha256: SHA_A,
          conciliacion: {
            filas: { total: { leidas: 120, insertadas: 80, actualizadas: 30, omitidas: 9, con_error: 1 } },
            control: { periodo: "2026-10", cuadra: false, archivo_aceptadas: 70, archivo_rechazadas: 5, control_aceptadas: 72, control_rechazadas: 5 },
          },
        },
        { sha256: SHA_B, conciliacion: null },
      ],
    });
    expect(withStats.counts).toEqual({ read: 120, inserted: 80, updated: 30, skipped: 9, errors: 1 });
    expect(withStats.control).toMatchObject({ period: "2026-10", matches: false, fileAccepted: 70, controlAccepted: 72 });
    expect(without.counts).toBeNull();
    expect(without.control).toBeNull();
  });

  it("rotula el control: cuadra, no cuadra o sin control", () => {
    const base = { period: "2026-10", fileAccepted: 2, fileRejected: 0, controlAccepted: 2, controlRejected: 0 };
    expect(controlBadge({ ...base, matches: true })).toEqual({ text: "Cuadra", tone: "green" });
    expect(controlBadge({ ...base, matches: false })).toEqual({ text: "No cuadra", tone: "orange" });
    expect(controlBadge({ ...base, matches: null })).toEqual({ text: "Sin control", tone: "gray" });
    expect(controlBadge(null).text).toBe("Sin control");
    expect(controlDetail({ ...base, matches: false })).toBe("2026-10: archivo 2/0 · control 2/0 (aceptadas/rechazadas)");
    expect(controlDetail({ ...base, matches: null })).toBeNull();
  });

  it("tolera una respuesta vacía", () => {
    expect(adaptTchFileLoads(null)).toEqual([]);
    expect(adaptTchFileLoads({ items: null })).toEqual([]);
  });

  it("formatea fecha y hash cortos", () => {
    // QA-06: hora de Chile (UTC-3 en noviembre), como Sincronización
    expect(shortDateTime("2026-11-02T10:05:59+00:00")).toBe("2026-11-02 07:05");
    expect(shortDateTime("2026-11-03T01:41:00+00:00")).toBe("2026-11-02 22:41");
    expect(shortDateTime(null)).toBe("—");
    expect(shortHash(SHA_A)).toBe("aaaaaaaaaaaa");
  });
});

describe("TchFileLoadsPanel", () => {
  // Con llaves: si beforeEach devuelve una funcion (mockReset devuelve el mock), vitest la ejecuta como limpieza.
  beforeEach(() => { vi.mocked(getJson).mockReset(); });
  afterEach(cleanup);

  it("muestra por archivo la fecha, el hash, el mes, las filas y el resultado", async () => {
    vi.mocked(getJson).mockResolvedValue({
      items: [
        { sha256: SHA_A, archivo: "20261031 TCH IG OCTUBRE 2026.xlsx", periodo: "2026-10", cargado_en: "2026-11-02T10:05:00+00:00", filas: 1200, resultado: "consolidado" },
        { sha256: SHA_B, archivo: "malo.xlsx", periodo: null, cargado_en: "2026-11-01T09:00:00+00:00", filas: null, resultado: "fallido", error: "La carga fallo (ValueError); ver el detalle en la corrida ETL." },
      ],
    });
    render(<TchFileLoadsPanel />);

    expect(await screen.findByText("20261031 TCH IG OCTUBRE 2026.xlsx")).toBeTruthy();
    expect(getJson).toHaveBeenCalledWith("/api/v1/tch/archivos?limit=50");
    expect(screen.getByText("2026-11-02 07:05")).toBeTruthy(); // QA-06: hora de Chile
    expect(screen.getByTitle(SHA_A).textContent).toBe("aaaaaaaaaaaa");
    expect(screen.getByText("2026-10")).toBeTruthy();
    expect(screen.getByText((1200).toLocaleString("es-CL"))).toBeTruthy(); // sin conciliación: filas cargadas como leídas
    expect(screen.getByText("Consolidado")).toBeTruthy();
    expect(screen.getByText("Fallido")).toBeTruthy();
    expect(screen.getByText(/ver el detalle en la corrida ETL/)).toBeTruthy();
  });

  it("TCH-PAR-11: muestra por archivo leídas, insertadas, actualizadas, omitidas, con error y si cuadra con su control", async () => {
    vi.mocked(getJson).mockResolvedValue({
      items: [
        {
          sha256: SHA_A, archivo: "octubre.xlsx", periodo: "2026-10", cargado_en: "2026-11-02T10:05:00+00:00", filas: 110, resultado: "cargado",
          conciliacion: {
            filas: { total: { leidas: 1234, insertadas: 1001, actualizadas: 102, omitidas: 13, con_error: 4 } },
            control: { periodo: "2026-10", cuadra: true, archivo_aceptadas: 9, archivo_rechazadas: 1, control_aceptadas: 9, control_rechazadas: 1 },
          },
        },
        {
          sha256: SHA_B, archivo: "septiembre.xlsx", periodo: "2026-09", cargado_en: "2026-10-02T10:05:00+00:00", filas: 50, resultado: "consolidado",
          conciliacion: {
            filas: { total: { leidas: 60, insertadas: 50, actualizadas: 0, omitidas: 10, con_error: 0 } },
            control: { periodo: "2026-09", cuadra: false, archivo_aceptadas: 7, archivo_rechazadas: 2, control_aceptadas: 8, control_rechazadas: 2 },
          },
        },
      ],
    });
    render(<TchFileLoadsPanel />);

    const row = (await screen.findByText("octubre.xlsx")).closest("tr")!;
    const cells = [...row.querySelectorAll("td")].map((td) => td.textContent);
    expect(cells[3]).toBe("Cargado"); // QA-14: el resultado va antes de los conteos, no cortado al final
    expect(cells.slice(4, 10)).toEqual([(1234).toLocaleString("es-CL"), (1001).toLocaleString("es-CL"), "102", "13", "4", "Cuadra"]);
    const columns = [...document.querySelectorAll("th")].map((th) => th.textContent);
    expect(columns).toEqual(expect.arrayContaining(["Leídas", "Insertadas", "Actualizadas", "Omitidas", "Con error", "Control del Excel"]));
    const other = screen.getByText("septiembre.xlsx").closest("tr")!;
    expect(other.textContent).toContain("No cuadra");
    expect(other.textContent).toContain("2026-09: archivo 7/2 · control 8/2 (aceptadas/rechazadas)");
  });

  it("QA-14: los archivos sin conciliación guardada se explican en vez de quedar solo en «—»", async () => {
    vi.mocked(getJson).mockResolvedValue({
      items: [
        { sha256: SHA_A, archivo: "viejo-1.xlsx", periodo: "2026-08", cargado_en: "2026-09-02T10:05:00+00:00", filas: null, resultado: "consolidado" },
        { sha256: SHA_B, archivo: "viejo-2.xlsx", periodo: "2026-09", cargado_en: "2026-10-02T10:05:00+00:00", filas: null, resultado: "consolidado" },
      ],
    });
    render(<TchFileLoadsPanel />);
    await screen.findByText("viejo-1.xlsx");
    expect(screen.getByRole("note").textContent).toMatch(/2 archivos se cargaron antes de que el CRM guardara\s+la conciliación/);
    expect(screen.getByLabelText(/desplazable/)).toBeTruthy();
  });

  it("avisa cuando no hay reportes registrados", async () => {
    vi.mocked(getJson).mockResolvedValue({ items: [] });
    render(<TchFileLoadsPanel />);
    expect(await screen.findByText("Aún no hay reportes registrados.")).toBeTruthy();
  });

  it("muestra un error amable si la API falla", async () => {
    vi.mocked(getJson).mockImplementation(() => Promise.reject(new Error("sin conexión")));
    render(<TchFileLoadsPanel />);
    expect(await screen.findByText("No se pudo cargar el registro de archivos TCH.")).toBeTruthy();
  });
});
