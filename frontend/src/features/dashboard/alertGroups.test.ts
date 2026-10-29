import { describe, expect, it } from "vitest";
import { groupAlerts, parseDetailValue, normalizeSev } from "./alertGroups";
import type { DashboardAlert } from "../shared/types";

const a = (over: Partial<DashboardAlert>): DashboardAlert => ({ sev: "media", tipo: "Rechazos", canal: "Toku", detalle: "10 cargos", ...over });

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

describe("normalizeSev", () => {
  it("acepta alta/media/baja sin importar mayúsculas y cae a baja", () => {
    expect(normalizeSev("ALTA")).toBe("alta");
    expect(normalizeSev("media")).toBe("media");
    expect(normalizeSev(undefined)).toBe("baja");
    expect(normalizeSev("raro")).toBe("baja");
  });
});

describe("groupAlerts", () => {
  it("agrupa por (tipo, canal) y toma la severidad máxima", () => {
    const groups = groupAlerts([
      a({ sev: "baja", periodo: "2026-01" }),
      a({ sev: "alta", periodo: "2026-02" }),
      a({ sev: "media", periodo: "2026-03" }),
      a({ canal: "Payku" }),
      a({ tipo: "Otro" }),
    ]);
    expect(groups).toHaveLength(3);
    const toku = groups.find((g) => g.tipo === "Rechazos" && g.canal === "Toku")!;
    expect(toku.alerts).toHaveLength(3);
    expect(toku.sev).toBe("alta");
  });

  it("ordena por severidad y luego por valor numérico del detalle descendente", () => {
    const groups = groupAlerts([
      a({ tipo: "A", sev: "media", detalle: "5 cargos" }),
      a({ tipo: "B", sev: "alta", detalle: "2 cargos" }),
      a({ tipo: "C", sev: "media", detalle: "40 cargos" }),
      a({ tipo: "D", sev: "media", detalle: "sin número" }),
      a({ tipo: "E", sev: "baja", detalle: "999 cargos" }),
    ]);
    expect(groups.map((g) => g.tipo)).toEqual(["B", "C", "A", "D", "E"]);
  });

  it("el valor del grupo es el máximo entre sus alertas y el detalle mostrado es el del peor", () => {
    const [g] = groupAlerts([a({ detalle: "3 cargos", periodo: "2026-01" }), a({ detalle: "30 cargos", periodo: "2026-02" })]);
    expect(g.value).toBe(30);
    expect(g.detalle).toBe("30 cargos");
  });

  it("dentro del grupo ordena periodos del más reciente al más antiguo; sin periodo conserva el orden", () => {
    const [g] = groupAlerts([a({ periodo: "2026-01" }), a({ periodo: "2026-03" }), a({ periodo: "2026-02" })]);
    expect(g.alerts.map((x) => x.periodo)).toEqual(["2026-03", "2026-02", "2026-01"]);
    const [old] = groupAlerts([a({ detalle: "1 x" }), a({ detalle: "2 x" })]);
    expect(old.alerts.map((x) => x.detalle)).toEqual(["1 x", "2 x"]);
  });

  it("es determinista ante empates y tolera lista vacía o sev inválida", () => {
    expect(groupAlerts([])).toEqual([]);
    const groups = groupAlerts([a({ tipo: "Z", detalle: "1" }), a({ tipo: "B", detalle: "1" })]);
    expect(groups.map((g) => g.tipo)).toEqual(["B", "Z"]);
    expect(groupAlerts([{ tipo: "X", canal: "TCH", detalle: "1" } as unknown as DashboardAlert])[0].sev).toBe("baja");
  });
});
