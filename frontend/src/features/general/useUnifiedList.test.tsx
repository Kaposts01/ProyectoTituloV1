import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getJson } from "../../api";
import { useUnifiedGet } from "./useUnifiedList";

vi.mock("../../api", async (original) => ({ ...await original<typeof import("../../api")>(), getJson: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
describe("Consultas de tablas", () => {
  it("descarta una respuesta anterior incluso si el transporte ignora la cancelación", async () => {
    let release!: (data: { value: string }) => void;
    vi.mocked(getJson).mockReturnValueOnce(new Promise((r) => { release = r; })).mockResolvedValueOnce({ value: "new" });
    const hook = renderHook(({ query }) => useUnifiedGet<{ value: string }>("/api/list", { query }), { initialProps: { query: "first" } });
    hook.rerender({ query: "second" });
    await waitFor(() => expect(hook.result.current.data?.value).toBe("new"));
    await act(async () => release({ value: "old" }));
    expect(hook.result.current.data?.value).toBe("new");
    expect(hook.result.current.loading).toBe(false);
  });
  it("puede reintentar conservando la consulta y oculta datos al deshabilitar la vista", async () => {
    vi.mocked(getJson).mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ value: "ok" });
    const hook = renderHook(({ enabled }) => useUnifiedGet<{ value: string }>("/api/list", { canal: "tch" }, enabled), { initialProps: { enabled: true } });
    await waitFor(() => expect(hook.result.current.error).toBeTruthy());
    act(() => hook.result.current.reload());
    await waitFor(() => expect(hook.result.current.data?.value).toBe("ok"));
    expect(vi.mocked(getJson).mock.calls.every(([url]) => url === "/api/list?canal=tch")).toBe(true);
    hook.rerender({ enabled: false });
    expect(hook.result.current.data).toBeNull();
  });
  it("no reutiliza resultados cuando cambia el usuario de una vista persistente", async () => {
    vi.mocked(getJson).mockResolvedValueOnce({ value: "previous-user" }).mockReturnValueOnce(new Promise(() => {}));
    const first = {}, second = {};
    const hook = renderHook(({ user }) => useUnifiedGet<{ value: string }>("/api/list", {}, true, user), { initialProps: { user: first } });
    await waitFor(() => expect(hook.result.current.data?.value).toBe("previous-user"));
    hook.rerender({ user: second });
    expect(hook.result.current.data).toBeNull();
    expect(hook.result.current.loading).toBe(true);
  });
});
