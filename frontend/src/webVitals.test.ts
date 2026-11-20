import { afterEach, describe, expect, it, vi } from "vitest";
import { formatMetric, registerWebVitals, type WebVitalsModule } from "./webVitals";

afterEach(() => vi.unstubAllEnvs());

function fakeModule() {
  const mod = { onLCP: vi.fn(), onINP: vi.fn(), onCLS: vi.fn() };
  return { mod, load: vi.fn(async () => mod as unknown as WebVitalsModule) };
}

describe("registerWebVitals", () => {
  it("no se activa ni carga el módulo fuera de sandbox", async () => {
    for (const mode of ["production", "development", "test"]) {
      vi.stubEnv("MODE", mode);
      const { mod, load } = fakeModule();
      expect(await registerWebVitals(load, vi.fn())).toBe(false);
      expect(load).not.toHaveBeenCalled();
      expect(mod.onLCP).not.toHaveBeenCalled();
    }
  });

  it("en sandbox registra LCP, INP y CLS con reportAllChanges", async () => {
    vi.stubEnv("MODE", "sandbox");
    const { mod, load } = fakeModule();
    expect(await registerWebVitals(load, vi.fn())).toBe(true);
    for (const fn of [mod.onLCP, mod.onINP, mod.onCLS]) {
      expect(fn).toHaveBeenCalledWith(expect.any(Function), { reportAllChanges: true });
    }
  });

  it("escribe con el prefijo [web-vitals], valor redondeado, rating y selector", async () => {
    vi.stubEnv("MODE", "sandbox");
    const { mod, load } = fakeModule();
    const log = vi.fn();
    await registerWebVitals(load, log);
    const report = mod.onLCP.mock.calls[0][0];
    report({ name: "LCP", value: 1234.56, rating: "good", attribution: { target: "main > h1.title" } });
    expect(log).toHaveBeenCalledWith("[web-vitals] LCP 1235 ms good main > h1.title");
  });
});

describe("formatMetric", () => {
  it("CLS con tres decimales y selector del mayor desplazamiento", () => {
    expect(formatMetric({ name: "CLS", value: 0.12345, rating: "needs-improvement", attribution: { largestShiftTarget: "div.env-banner" } }))
      .toBe("[web-vitals] CLS 0.123 needs-improvement div.env-banner");
  });
  it("INP usa el elemento de la interacción y tolera que falte", () => {
    expect(formatMetric({ name: "INP", value: 310.4, rating: "poor", attribution: { interactionTarget: "input.search" } })).toContain("input.search");
    expect(formatMetric({ name: "INP", value: 50, rating: "good" })).toMatch(/ -$/);
  });
});
