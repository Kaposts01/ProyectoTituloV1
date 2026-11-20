/** PERF-03 (d264 C): datos de la vista adelantados en paralelo con /auth/me. Respuestas sintéticas. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCached, invalidateCache } from "./apiCache";
import { discardEarlyData, FIRST_PAGE_URLS, startEarlyData, takeEarly } from "./earlyData";
import { cleanParams } from "./features/general/useUnifiedList";

const ok = (data: unknown) => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => data });
const fail = (status: number) => ({ ok: false, status, headers: { get: () => "application/json" }, json: async () => ({ detail: "no" }) });

let fetchMock: ReturnType<typeof vi.fn>;
const urls = () => fetchMock.mock.calls.map((call) => String(call[0]));
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  fetchMock = vi.fn(async () => ok({ items: [] }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  invalidateCache();
});

describe("startEarlyData: qué se pide según la ruta", () => {
  it.each([
    ["/central/suscripciones", FIRST_PAGE_URLS.subscriptions],
    ["/central/cobros", FIRST_PAGE_URLS.charges],
    ["/central/clientes", FIRST_PAGE_URLS.clients],
    ["/central/resumen", "/api/v1/dashboard/general"],
    ["/", "/api/v1/dashboard/general"],
    ["/virtualpos/resumen", "/api/v1/staging/dashboard/virtualpos"],
    ["/toku/resumen", "/api/v1/staging/dashboard/toku"],
    ["/payku/resumen", "/api/v1/staging/dashboard/payku"],
  ])("%s pide %s", async (path, expected) => {
    fetchMock.mockImplementation(async () => ok({}));
    startEarlyData(path, "");
    await flush();
    expect(urls()).toEqual([expected]);
  });

  it("no pide nada para otras rutas ni cuando la URL trae filtros u offset", async () => {
    startEarlyData("/admin/usuarios", "");
    startEarlyData("/mi-perfil", "");
    startEarlyData("/central/suscripciones", "?offset=50");
    startEarlyData("/central/clientes", "?rut=11111111-1");
    startEarlyData("/ruta/que/no/existe", "");
    await flush();
    expect(urls()).toEqual([]);
  });

  it("las URLs de primera página son exactamente las que arman los hooks", () => {
    const hook = (path: string) => `${path}?${new URLSearchParams(cleanParams({ canal: "", offset: 0, limit: 50 })).toString()}`;
    expect(FIRST_PAGE_URLS.subscriptions).toBe(hook("/api/v1/general/subscriptions"));
    expect(FIRST_PAGE_URLS.charges).toBe(hook("/api/v1/general/charges"));
  });
});

describe("takeEarly", () => {
  it("entrega la respuesta adelantada una sola vez (de un solo uso) con una sola petición", async () => {
    fetchMock.mockImplementation(async () => ok({ items: [1] }));
    startEarlyData("/central/suscripciones", "");
    const first = takeEarly<{ items: number[] }>(FIRST_PAGE_URLS.subscriptions);
    expect(first).not.toBeNull();
    expect(await first).toEqual({ items: [1] });
    await flush();
    expect(takeEarly(FIRST_PAGE_URLS.subscriptions)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("devuelve null si no se adelantó nada", () => {
    expect(takeEarly("/api/v1/general/subscriptions?offset=0&limit=50")).toBeNull();
  });
});

describe("seguridad de los datos adelantados", () => {
  it.each([401, 403])("un %s de la petición adelantada no se cachea", async (status) => {
    fetchMock.mockImplementation(async () => fail(status));
    startEarlyData("/central/clientes", "");
    await flush();
    expect(takeEarly(FIRST_PAGE_URLS.clients)).toBeNull();
    expect(getCached(`early:${FIRST_PAGE_URLS.clients}`, 60_000)).toBeNull();
  });

  it("un 401 del canal tampoco queda en la caché del dashboard", async () => {
    fetchMock.mockImplementation(async () => fail(401));
    startEarlyData("/virtualpos/resumen", "");
    await flush();
    expect(getCached("dashboard:virtualpos", 300_000)).toBeNull();
  });

  it("discardEarlyData borra lo ya guardado", async () => {
    startEarlyData("/central/cobros", "");
    await flush();
    discardEarlyData();
    expect(takeEarly(FIRST_PAGE_URLS.charges)).toBeNull();
  });

  it("si se descarta con la petición en vuelo, la respuesta tardía no queda guardada", async () => {
    let release: (value: unknown) => void = () => undefined;
    fetchMock.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    startEarlyData("/virtualpos/resumen", "");
    discardEarlyData();
    release(ok({ years: [] }));
    await flush();
    expect(getCached("dashboard:virtualpos", 300_000)).toBeNull();
  });
});

describe("earlyOr (QA PERF-03b F2)", () => {
  it("sin adelantado usa la petición normal", async () => {
    const { earlyOr } = await import("./earlyData");
    await expect(earlyOr(null, () => Promise.resolve("normal"))).resolves.toBe("normal");
  });
  it("si el adelantado falla por red o 5xx, reintenta con la petición normal", async () => {
    const { earlyOr } = await import("./earlyData");
    const { ApiError } = await import("./api");
    const fallo = Promise.reject(new ApiError("caído", 503, null));
    await expect(earlyOr(fallo, () => Promise.resolve("reintento"))).resolves.toBe("reintento");
    await expect(earlyOr(Promise.reject(new TypeError("Failed to fetch")), () => Promise.resolve("reintento"))).resolves.toBe("reintento");
  });
  it("si el adelantado falla por 401 o 403, no reintenta y propaga el error", async () => {
    const { earlyOr } = await import("./earlyData");
    const { ApiError } = await import("./api");
    for (const status of [401, 403]) {
      let llamadas = 0;
      await expect(earlyOr(Promise.reject(new ApiError("sin acceso", status, null)), () => { llamadas++; return Promise.resolve("x"); })).rejects.toBeInstanceOf(ApiError);
      expect(llamadas).toBe(0);
    }
  });
});
