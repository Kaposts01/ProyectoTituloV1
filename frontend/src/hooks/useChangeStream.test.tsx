import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCached, setCached } from "../apiCache";
import { ChangeToasts, describeChange } from "../components/ChangeToasts";
import { CHANGE_STREAM_URL, parseChange, SeenIds, useChangeStream, type StreamChange } from "./useChangeStream";

type Listener = (event: MessageEvent) => void;

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = FakeEventSource.CONNECTING;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, Listener[]>();
  url: string;
  init?: EventSourceInit;

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.init = init;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type: string, data: unknown, lastEventId = "") {
    const event = { data: JSON.stringify(data), lastEventId } as MessageEvent;
    for (const fn of this.listeners.get(type) ?? []) fn(event);
  }

  fail() {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.();
  }
}

const change = (over: Partial<StreamChange> = {}) => ({
  entity: "subscription", source: "toku", external_id: "sub_1", subscription_external_id: "sub_1",
  kind: "status_changed", field: "status", from: "ACTIVE", to: "CANCELLED", at: "2026-11-02T12:00:00+00:00", ...over,
});

const tick = () => act(() => { vi.advanceTimersByTime(0); });

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useChangeStream", () => {
  it("abre el stream con credenciales, avisa cambios, invalida la caché y descarta repetidos", () => {
    const onChange = vi.fn();
    const { result } = renderHook(() => useChangeStream({ enabled: true, onChange }));
    tick();
    const es = FakeEventSource.instances[0];
    expect(es.url).toBe(CHANGE_STREAM_URL);
    expect(es.init?.withCredentials).toBe(true);
    act(() => es.emit("ready", { poll_seconds: 5 }, "100."));
    expect(result.current).toBe("live");
    setCached("algo", 1);
    act(() => es.emit("change", change(), "200.a"));
    act(() => es.emit("change", change(), "200.a"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({ id: "200.a", to: "CANCELLED" });
    expect(getCached("algo", 60000)).toBeNull();
  });

  it("no abre nada si está apagado", () => {
    const { result } = renderHook(() => useChangeStream({ enabled: false }));
    tick();
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current).toBe("off");
  });

  it("si el stream queda cerrado pasa a polling y reconecta con el último cursor", () => {
    const onRefresh = vi.fn();
    const { result } = renderHook(() => useChangeStream({ enabled: true, onRefresh, fallbackMs: 1000 }));
    tick();
    const first = FakeEventSource.instances[0];
    act(() => first.emit("change", change(), "300.b"));
    act(() => first.fail());
    expect(result.current).toBe("polling");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onRefresh).toHaveBeenCalledTimes(1);
    const second = FakeEventSource.instances[1];
    expect(second.url).toBe(`${CHANGE_STREAM_URL}?last_event_id=300.b`);
    act(() => second.emit("ready", {}, "301."));
    expect(result.current).toBe("live");
  });

  it("sin EventSource usa solo polling", () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("EventSource", undefined);
    const { result } = renderHook(() => useChangeStream({ enabled: true }));
    tick();
    expect(result.current).toBe("polling");
  });

  it("reset del servidor pide recargar", () => {
    const onRefresh = vi.fn();
    renderHook(() => useChangeStream({ enabled: true, onRefresh }));
    tick();
    act(() => FakeEventSource.instances[0].emit("reset", { reason: "cursor_expired" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("parseChange rechaza datos inválidos y SeenIds tiene tope", () => {
    expect(parseChange("x", "no json")).toBeNull();
    expect(parseChange("x", "{}")).toBeNull();
    const seen = new SeenIds(2);
    expect([seen.add("a"), seen.add("b"), seen.add("a"), seen.add("c"), seen.add("a")]).toEqual([true, true, false, true, true]);
  });
});

describe("ChangeToasts", () => {
  it("muestra el cambio en español, con el id en monoespaciado, y se cierra", () => {
    render(<ChangeToasts />);
    tick();
    act(() => FakeEventSource.instances[0].emit("change", change(), "400.c"));
    expect(screen.getByText("Cambió el estado: Suscripción de Toku")).toBeTruthy();
    expect(screen.getByText("Activa → Cancelada")).toBeTruthy();
    expect(screen.getByText("sub_1").className).toContain("mono");
    act(() => screen.getByRole("button", { name: "Cerrar aviso" }).click());
    expect(screen.queryByText("Activa → Cancelada")).toBeNull();
  });

  it("agrupa ráfagas y no muestra altas ni glosas", () => {
    render(<ChangeToasts />);
    tick();
    const es = FakeEventSource.instances[0];
    act(() => es.emit("change", change({ kind: "created" }), "500.0"));
    expect(screen.queryAllByRole("status")).toHaveLength(0);
    act(() => { for (let i = 1; i <= 7; i += 1) es.emit("change", change({ external_id: `s${i}` }), `500.${i}`); });
    expect(screen.getByText("Hay cambios nuevos")).toBeTruthy();
    expect(screen.queryAllByRole("status").length).toBeLessThanOrEqual(3);
  });

  it("describe cambios de monto y omite los demás tipos", () => {
    expect(describeChange({ id: "1", ...change({ kind: "amount_changed", field: "amount", from: "5000", to: "6000" }) })?.detail).toBe("5000 → 6000");
    expect(describeChange({ id: "2", ...change({ kind: "reason_changed" }) })).toBeNull();
  });
});
