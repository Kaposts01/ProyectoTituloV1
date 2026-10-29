import { describe, expect, it } from "vitest";
import { adaptSummary, hasAnyData } from "./summaryAdapter";
import { rawEmptyMonth, rawKpi, rawSingleChannel, rawSummary } from "./summaryFixtures";

describe("adaptSummary: claves en español -> tipos internos en inglés", () => {
  it("convierte los campos de primer nivel", () => {
    const s = adaptSummary(rawSummary());
    expect(s.month).toBe("2026-10");
    expect(s.timezone).toBe("America/Santiago");
    expect(s.generatedAt).toBe("2026-10-15T12:00:00-03:00");
    expect(s.isCurrentMonth).toBe(true);
    expect(s.channels).toEqual(["virtualpos", "toku", "payku", "tch"]);
    expect(s.dataQuality).toEqual({ activationsWithoutDate: 0, cancellationsWithoutDate: 0 });
  });

  it("convierte un KPI: valor, mes anterior, variaciones, meta y unidad", () => {
    const k = adaptSummary(rawSummary()).kpis.totalMembers;
    expect(k.value).toBe(8);
    expect(k.previousMonthValue).toBe(9);
    expect(k.deltaVsPreviousMonth).toBe(-1);
    expect(k.deltaVsPreviousMonthPct).toBe(-11.1);
    expect(k.goal).toBeNull();
    expect(k.goalStatus).toBe("none");
    expect(k.unit).toBe("count");
    expect(k.note).toBe("suma por canal, no deduplicada");
    expect(k.noteUnit).toBe("suscripciones");
  });

  it("mapea cada KPI del contrato a su nombre interno", () => {
    const k = adaptSummary(rawSummary()).kpis;
    expect(k.activations.value).toBe(3);
    expect(k.cancellations.value).toBe(4);
    expect(k.netGrowth.value).toBe(-1);
    expect(k.churn.value).toBe(44.4);
    expect(k.totalRevenue.value).toBe(92000);
    expect(k.yearToDate.value).toBe(168000);
    expect(k.collectability.value).toBe(66.7);
    expect(k.uncollected.value).toBe(30000);
    expect(k.receivable.value).toBe(10000);
    expect(k.mrr.value).toBe(90000);
    expect(k.arpu.value).toBe(12857);
    expect(k.churn.definition).toContain("Propuesta pendiente de confirmación");
    expect(k.churn.windowLabel).toContain("mes calendario");
    expect(k.mrr.byChannel).toEqual({ virtualpos: 25000, toku: 8000, payku: 7000, tch: 50000 });
    expect(k.revenueByChannel.tch?.value).toBe(50000);
  });

  it("null se conserva como null: nunca se inventa un 0", () => {
    const s = adaptSummary(rawSummary({ kpis: { ...rawSummary().kpis, mrr: rawKpi(null, null, "clp", { por_canal: { virtualpos: null } }), arpu: rawKpi(null, null, "clp") } }));
    expect(s.kpis.mrr.value).toBeNull();
    expect(s.kpis.mrr.byChannel).toEqual({ virtualpos: null });
    expect(s.kpis.arpu.value).toBeNull();
    expect(s.kpis.arpu.deltaVsPreviousMonth).toBeNull();
    expect(s.kpis.revenueByChannel.payku?.previousMonthValue).toBeNull();
  });

  it("un 0 real sigue siendo 0", () => {
    const s = adaptSummary(rawSummary());
    expect(s.kpis.receivable.previousMonthValue).toBe(0);
  });

  it("un KPI ausente o con valores no numéricos queda en null, no en 0", () => {
    const kpis = { ...rawSummary().kpis } as Record<string, unknown>;
    delete kpis.arpu;
    kpis.mrr = { valor: "12", unidad: "clp" };
    const s = adaptSummary(rawSummary({ kpis }));
    expect(s.kpis.arpu.value).toBeNull();
    expect(s.kpis.mrr.value).toBeNull();
    expect(s.kpis.arpu.unit).toBe("clp");
  });

  it("meta null y estado «sin_meta» dan el estado interno «none» (sin meta)", () => {
    const k = adaptSummary(rawSummary()).kpis;
    for (const kpi of [k.totalMembers, k.activations, k.churn, k.totalRevenue, k.mrr]) {
      expect(kpi.goal).toBeNull();
      expect(kpi.goalStatus).toBe("none");
    }
  });

  it("estados de meta futuros (en_meta, cerca, lejos) se mapean; uno desconocido es «none»", () => {
    const withState = (estado: string) => adaptSummary(rawSummary({ kpis: { ...rawSummary().kpis, activaciones: rawKpi(3, 1, "count", { meta: 5, estado_meta: estado }) } })).kpis.activations;
    expect(withState("en_meta")).toMatchObject({ goal: 5, goalStatus: "met" });
    expect(withState("cerca")).toMatchObject({ goal: 5, goalStatus: "near" });
    expect(withState("lejos")).toMatchObject({ goal: 5, goalStatus: "off" });
    expect(withState("otro_estado").goalStatus).toBe("none");
  });

  it("un canal sin permiso no aparece: ni en channels, ni en ingresos, ni en MRR, ni en las series", () => {
    const s = adaptSummary(rawSingleChannel("toku"));
    expect(s.channels).toEqual(["toku"]);
    expect(Object.keys(s.kpis.revenueByChannel)).toEqual(["toku"]);
    expect(Object.keys(s.kpis.mrr.byChannel)).toEqual(["toku"]);
    for (const point of s.series.revenueByChannel) expect(Object.keys(point.channels)).toEqual(["toku"]);
  });

  it("ignora canales desconocidos y los ordena en el orden fijo del contrato", () => {
    const s = adaptSummary(rawSummary({ channels: ["tch", "xyz", "virtualpos"] }));
    expect(s.channels).toEqual(["virtualpos", "tch"]);
  });

  it("convierte las series de 12 meses", () => {
    const s = adaptSummary(rawSummary()).series;
    expect(s.months).toHaveLength(12);
    expect(s.months[11]).toBe("2026-10");
    expect(s.revenueByChannel).toHaveLength(12);
    expect(s.revenueByChannel[0].channels.payku).toBeNull();
    expect(s.revenueByChannel[11].channels.payku).toBe(5000);
    expect(s.activations[0]).toEqual({ month: "2025-11", value: 1 });
    expect(s.cancellations).toHaveLength(12);
    expect(s.totalMembers[11]).toEqual({ month: "2026-10", value: 16 });
  });

  it("mes sin datos: todo null, hasAnyData es falso", () => {
    const s = adaptSummary(rawEmptyMonth());
    expect(s.kpis.totalMembers.value).toBeNull();
    expect(s.kpis.totalRevenue.value).toBeNull();
    expect(s.series.totalMembers.every((p) => p.value === null)).toBe(true);
    expect(hasAnyData(s)).toBe(false);
  });

  it("hasAnyData es verdadero si hay algún KPI con valor, aunque sea 0", () => {
    expect(hasAnyData(adaptSummary(rawSummary()))).toBe(true);
    const onlyZero = rawEmptyMonth();
    onlyZero.kpis.por_cobrar = rawKpi(0, null, "clp");
    expect(hasAnyData(adaptSummary(onlyZero))).toBe(true);
  });

  it("una respuesta que no es un objeto lanza un error en español", () => {
    expect(() => adaptSummary(null)).toThrow(/formato/);
    expect(() => adaptSummary("texto")).toThrow(/formato/);
  });

  it("calidad de datos ausente cuenta como 0 avisos", () => {
    const raw = rawSummary();
    delete raw.calidad_datos;
    expect(adaptSummary(raw).dataQuality).toEqual({ activationsWithoutDate: 0, cancellationsWithoutDate: 0 });
  });
});
