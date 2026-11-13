import { describe, expect, it } from "vitest";
import { ageText, channelText, entryState } from "./healthLabels";

describe("13B: textos del estado de sincronización por canal", () => {
  it("distingue al día, atrasada (con horas o días), falló y en curso", () => {
    expect(channelText({ level: "ok", state: "ok", age_hours: 2 })).toBe("Al día · hace 2 h");
    expect(channelText({ level: "warn", state: "stale", age_hours: 30 })).toBe("Atrasada · hace 30 h");
    expect(channelText({ level: "warn", state: "stale", age_hours: 96 })).toBe("Atrasada · hace 4 d");
    expect(channelText({ level: "error", state: "failed", age_hours: 1.2 })).toBe("Falló · hace 1 h");
    expect(channelText({ level: "ok", state: "running", age_hours: 5 })).toBe("En curso");
    expect(channelText({ level: "unknown", state: "unknown", age_hours: null })).toBe("Sin datos de sincronización");
  });

  it("4 días sin corridas es «Atrasada», nunca un error", () => {
    expect(channelText({ level: "warn", state: "stale", age_hours: 100.5 })).toBe("Atrasada · hace 4 d");
  });

  it("sin `state` (backend anterior) se deduce del nivel", () => {
    expect(entryState({ level: "warn" })).toBe("stale");
    expect(entryState({ level: "error" })).toBe("failed");
    expect(entryState({ level: "ok" })).toBe("ok");
    expect(entryState({ level: "unknown" })).toBe("unknown");
  });

  it("antigüedad en horas hasta 47 h y en días desde 48 h", () => {
    expect(ageText(0.4)).toBe("hace menos de 1 h");
    expect(ageText(47)).toBe("hace 47 h");
    expect(ageText(48)).toBe("hace 2 d");
    expect(ageText(null)).toBeNull();
  });
});
