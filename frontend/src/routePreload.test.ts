import { describe, expect, it } from "vitest";
import { loaderForPath } from "./routePreload";

describe("loaderForPath", () => {
  it("elige el chunk según la ruta, con la raíz como Resumen", () => {
    const summary = loaderForPath("/central/resumen");
    expect(summary).toBeTypeOf("function");
    expect(loaderForPath("/")).toBe(summary);
    expect(loaderForPath("/central/resumen?mes=2026-10")).toBe(summary);
    expect(loaderForPath("/central/cobros")).not.toBe(summary);
    expect(loaderForPath("/virtualpos/resumen")).toBeTypeOf("function");
    expect(loaderForPath("/admin/sincronizaciones")).toBeTypeOf("function");
  });

  it("no precarga nada para rutas desconocidas o sin chunk propio", () => {
    expect(loaderForPath("/ruta/que/no/existe")).toBeNull();
    expect(loaderForPath("/mi-perfil")).toBeNull();
  });
});
