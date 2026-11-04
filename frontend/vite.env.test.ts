import { describe, expect, it } from "vitest";
import { resolveDevServerSettings } from "./vite.env.ts";

describe("resolveDevServerSettings", () => {
  it("usa los valores por defecto de produccion", () => {
    expect(resolveDevServerSettings({})).toEqual({ port: 5173, proxyTarget: "http://127.0.0.1:8000" });
  });
  it("aplica la configuracion de sandbox", () => {
    expect(resolveDevServerSettings({ VITE_API_PROXY_TARGET: "http://127.0.0.1:8001", VITE_DEV_PORT: "5174" }))
      .toEqual({ port: 5174, proxyTarget: "http://127.0.0.1:8001" });
  });
  it("ignora puertos invalidos", () => {
    expect(resolveDevServerSettings({ VITE_DEV_PORT: "abc" }).port).toBe(5173);
    expect(resolveDevServerSettings({ VITE_DEV_PORT: "99999" }).port).toBe(5173);
  });
});
