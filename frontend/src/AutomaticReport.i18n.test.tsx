import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AutomaticReport } from "./AutomaticReport";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AutomaticReport: error de carga en español", () => {
  it("un error del servidor no muestra el texto HTTP en inglés", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 500, statusText: "Internal Server Error",
      headers: { get: () => "application/json" }, json: async () => ({}),
    })));
    render(<AutomaticReport />);
    expect(await screen.findByText(/No se pudo cargar el reporte/)).toBeTruthy();
    expect(screen.getByText(/Error interno del servidor/)).toBeTruthy();
    expect(screen.queryByText(/Internal Server Error/)).toBeNull();
  });

  it("sin conexión muestra el mensaje de red en español", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    render(<AutomaticReport />);
    expect(await screen.findByText(/No se pudo conectar con el servidor/)).toBeTruthy();
  });
});
