import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { invalidateCache } from "../../apiCache";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
import { getJson } from "../../api";
import { ALL_CHANNELS, resolveEnabledChannels, useEnabledChannels } from "./environment";

const mocked = vi.mocked(getJson);
beforeEach(() => { invalidateCache(); mocked.mockReset(); });

describe("enabled channels", () => {
  it("resolve: sin dato asume todos habilitados", () => {
    expect(resolveEnabledChannels(null)).toEqual([...ALL_CHANNELS]);
    expect(resolveEnabledChannels({})).toEqual([...ALL_CHANNELS]);
    expect(resolveEnabledChannels({ enabled_channels: ["virtualpos1", "tch"] })).toEqual(["virtualpos1", "tch"]);
  });

  it("hook: todos habilitados mientras carga y luego aplica la respuesta", async () => {
    mocked.mockResolvedValue({ app_env: "sandbox", label: "Sandbox", is_production: false, enabled_channels: ["virtualpos1", "toku", "tch"] });
    const { result } = renderHook(() => useEnabledChannels());
    expect(result.current.isEnabled("payku")).toBe(true);
    await waitFor(() => expect(result.current.isEnabled("payku")).toBe(false));
    expect(result.current.isEnabled("virtualpos1")).toBe(true);
    expect(result.current.isEnabled("virtualpos2")).toBe(false);
  });

  it("hook: ante error deja todos habilitados", async () => {
    mocked.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useEnabledChannels());
    await waitFor(() => expect(mocked).toHaveBeenCalled());
    expect(result.current.enabled).toEqual([...ALL_CHANNELS]);
  });
});
