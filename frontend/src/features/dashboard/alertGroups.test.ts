import { describe, expect, it } from "vitest";
import { groupAlerts, parseDetailValue, normalizeSeverity } from "./alertGroups";
import type { Alert } from "./alertTypes";

const a = (over: Partial<Alert>): Alert => ({ severity: "media", kind: "Rechazos", channel: "Toku", detail: "10 cargos", ...over });

describe("parseDetailValue", () => {
  it("toma el primer número y entiende formato es-CL", () => {
    expect(parseDetailValue("12 cargos rechazados")).toBe(12);
    expect(parseDetailValue("Tasa 35,5% en 2026-05")).toBe(35.5);
    expect(parseDetailValue("$1.234.567 sin cobrar")).toBe(1234567);
    expect(parseDetailValue("-3 respecto del mes anterior")).toBe(-3);
  });
  it("devuelve null si no hay número", () => {
    expect(parseDetailValue("sin detalle")).toBeNull();
    expect(parseDetailValue("")).toBeNull();
    expect(parseDetailValue(undefined)).toBeNull();
  });
});

describe("normalizeSeverity", () => {
  it("acepta alta/media/baja sin importar mayúsculas y cae a baja", () => {
    expect(normalizeSeverity("ALTA")).toBe("alta");
    expect(normalizeSeverity("media")).toBe("media");
    expect(normalizeSeverity(undefined)).toBe("baja");
    expect(normalizeSeverity("raro")).toBe("baja");
  });
});

describe("groupAlerts", () => {
  it("agrupa por (tipo, canal) y toma la severidad máxima", () => {
    const groups = groupAlerts([
      a({ severity: "baja", period: "2026-01" }),
      a({ severity: "alta", period: "2026-02" }),
      a({ severity: "media", period: "2026-03" }),
      a({ channel: "Payku" }),
      a({ kind: "Otro" }),
    ]);
    expect(groups).toHaveLength(3);
    const toku = groups.find((g) => g.kind === "Rechazos" && g.channel === "Toku")!;
    expect(toku.alerts).toHaveLength(3);
    expect(toku.severity).toBe("alta");
  });

  it("ordena por severidad y luego por valor numérico del detalle descendente", () => {
    const groups = groupAlerts([
      a({ kind: "A", severity: "media", detail: "5 cargos" }),
      a({ kind: "B", severity: "alta", detail: "2 cargos" }),
      a({ kind: "C", severity: "media", detail: "40 cargos" }),
      a({ kind: "D", severity: "media", detail: "sin número" }),
      a({ kind: "E", severity: "baja", detail: "999 cargos" }),
    ]);
    expect(groups.map((g) => g.kind)).toEqual(["B", "C", "A", "D", "E"]);
  });

  it("el valor del grupo es el máximo entre sus alertas y el detalle mostrado es el del peor", () => {
    const [g] = groupAlerts([a({ detail: "3 cargos", period: "2026-01" }), a({ detail: "30 cargos", period: "2026-02" })]);
    expect(g.value).toBe(30);
    expect(g.detail).toBe("30 cargos");
  });

  it("dentro del grupo ordena periodos del más reciente al más antiguo; sin periodo conserva el orden", () => {
    const [g] = groupAlerts([a({ period: "2026-01" }), a({ period: "2026-03" }), a({ period: "2026-02" })]);
    expect(g.alerts.map((x) => x.period)).toEqual(["2026-03", "2026-02", "2026-01"]);
    const [old] = groupAlerts([a({ detail: "1 x" }), a({ detail: "2 x" })]);
    expect(old.alerts.map((x) => x.detail)).toEqual(["1 x", "2 x"]);
  });

  it("es determinista ante empates y tolera lista vacía o sev inválida", () => {
    expect(groupAlerts([])).toEqual([]);
    const groups = groupAlerts([a({ kind: "Z", detail: "1" }), a({ kind: "B", detail: "1" })]);
    expect(groups.map((g) => g.kind)).toEqual(["B", "Z"]);
    expect(groupAlerts([{ kind: "X", channel: "TCH", detail: "1" } as unknown as Alert])[0].severity).toBe("baja");
  });
});
