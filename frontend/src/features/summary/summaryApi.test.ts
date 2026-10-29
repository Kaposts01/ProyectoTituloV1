import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import { buildSummaryPath, fetchSummary, SUMMARY_ENDPOINT } from "./summaryApi";
import { rawSummary } from "./summaryFixtures";

function stubFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_url: string, _init?: unknown) => ({
    ok: status < 400,
    status,
    headers: { get: (key: string) => (key.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("buildSummaryPath", () => {
  it("sin parámetros pide el endpoint tal cual (mes actual y todos los canales)", () => {
    expect(buildSummaryPath({})).toBe(SUMMARY_ENDPOINT);
  });
  it("agrega mes y canales", () => {
    expect(buildSummaryPath({ month: "2026-09", channels: ["toku", "tch"] })).toBe(`${SUMMARY_ENDPOINT}?month=2026-09&channels=toku%2Ctch`);
  });
  it("una lista de canales vacía no se envía (el servidor la rechazaría)", () => {
    expect(buildSummaryPath({ month: "2026-09", channels: [] })).toBe(`${SUMMARY_ENDPOINT}?month=2026-09`);
  });
});

describe("fetchSummary", () => {
  it("pide la ruta con las credenciales y devuelve el resumen adaptado", async () => {
    const fn = stubFetch(200, rawSummary());
    const s = await fetchSummary({ month: "2026-10" });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0]).toBe(`${SUMMARY_ENDPOINT}?month=2026-10`);
    expect(s.kpis.totalMembers.value).toBe(8);
  });

  it("422 invalid_month: mensaje en español (no el texto del backend)", async () => {
    stubFetch(422, { detail: { code: "invalid_month", message: "month must be YYYY-MM" } });
    await expect(fetchSummary({ month: "2026-13" })).rejects.toMatchObject({ message: "El mes no es válido. Usa el formato AAAA-MM, por ejemplo 2026-10." });
  });

  it("422 invalid_channel: mensaje en español", async () => {
    stubFetch(422, { detail: { code: "invalid_channel", message: "unknown channel" } });
    await expect(fetchSummary({ channels: ["xyz" as never] })).rejects.toMatchObject({ message: "Alguno de los canales pedidos no es válido." });
  });

  it("422 con otro código: mensaje genérico en español", async () => {
    stubFetch(422, { detail: { code: "otra_cosa", message: "english text" } });
    const error = await fetchSummary({}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).not.toMatch(/english/);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toMatch(/válid/);
  });

  it("403 conserva el mensaje en español del cliente HTTP", async () => {
    stubFetch(403, { detail: "Forbidden" });
    await expect(fetchSummary({})).rejects.toBeInstanceOf(ApiError);
  });

  it("una respuesta con formato inesperado falla con mensaje en español", async () => {
    stubFetch(200, null);
    await expect(fetchSummary({})).rejects.toThrow(/formato/);
  });
});
