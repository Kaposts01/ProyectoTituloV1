import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { TchFileLoadsPanel } from "./TchFileLoadsPanel";
import { adaptTchFileLoads, shortDateTime, shortHash } from "./tchFileLoadsAdapter";

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

  it("tolera una respuesta vacía", () => {
    expect(adaptTchFileLoads(null)).toEqual([]);
    expect(adaptTchFileLoads({ items: null })).toEqual([]);
  });

  it("formatea fecha y hash cortos", () => {
    expect(shortDateTime("2026-11-02T10:05:59+00:00")).toBe("2026-11-02 10:05");
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
    expect(screen.getByText("2026-11-02 10:05")).toBeTruthy();
    expect(screen.getByTitle(SHA_A).textContent).toBe("aaaaaaaaaaaa");
    expect(screen.getByText("2026-10")).toBeTruthy();
    expect(screen.getByText((1200).toLocaleString("es-CL"))).toBeTruthy();
    expect(screen.getByText("Consolidado")).toBeTruthy();
    expect(screen.getByText("Fallido")).toBeTruthy();
    expect(screen.getByText(/ver el detalle en la corrida ETL/)).toBeTruthy();
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
