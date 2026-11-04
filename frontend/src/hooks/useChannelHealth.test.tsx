import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../apiCache";
import * as api from "../api";
import { fetchChannelHealth, useChannelHealth } from "./useChannelHealth";

const rows = [
  { channel: "toku", level: "warn", last_finished_at: "2026-10-25T10:00:00Z", age_hours: 30 },
  { channel: "tch", level: "unknown", last_finished_at: null, age_hours: null },
];

describe("useChannelHealth", () => {
  beforeEach(() => { invalidateCache(); vi.restoreAllMocks(); });

  it("devuelve un mapa por canal con respuesta correcta", async () => {
    vi.spyOn(api, "getJson").mockResolvedValue(rows);
    const { result } = renderHook(() => useChannelHealth());
    await waitFor(() => expect(result.current.toku?.level).toBe("warn"));
    expect(result.current.tch?.age_hours).toBeNull();
  });

  it("devuelve mapa vacío sin lanzar ante error", async () => {
    vi.spyOn(api, "getJson").mockRejectedValue(new Error("403"));
    await expect(fetchChannelHealth()).resolves.toEqual({});
    const { result } = renderHook(() => useChannelHealth());
    await waitFor(() => expect(api.getJson).toHaveBeenCalled());
    expect(result.current).toEqual({});
  });

  it("usa la caché en la segunda llamada", async () => {
    const spy = vi.spyOn(api, "getJson").mockResolvedValue(rows);
    await fetchChannelHealth();
    await fetchChannelHealth();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("/api/v1/sync-runs/health");
  });
});
