/**
 * Respuestas SINTÉTICAS de `GET /api/v1/dashboard/general` para las pruebas (claves en español, tal como las envía el
 * backend; ver docs/data/dashboard-general.md). Sin datos personales. Solo las pruebas importan este módulo.
 */

export type RawKpi = Record<string, unknown>;

/** KPI con meta ausente, como responde hoy el backend (`meta: null`, `estado_meta: "sin_meta"`). */
export function rawKpi(value: number | null, previous: number | null, unit: "count" | "clp" | "pct", extra: RawKpi = {}): RawKpi {
  const delta = value !== null && previous !== null ? Math.round((value - previous) * 10) / 10 : null;
  const deltaPct = delta !== null && previous !== null && previous !== 0 ? Math.round((delta / Math.abs(previous)) * 1000) / 10 : null;
  return {
    valor: value,
    valor_mes_anterior: previous,
    delta_vs_mes_anterior: delta,
    delta_vs_mes_anterior_pct: deltaPct,
    meta: null,
    estado_meta: "sin_meta",
    unidad: unit,
    ...extra,
  };
}

const MONTHS_12 = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"];

export type RawSummary = Record<string, unknown> & { kpis: Record<string, unknown>; series: Record<string, unknown> };

/** Respuesta completa del mes 2026-10 con los cuatro canales. */
export function rawSummary(overrides: Partial<RawSummary> = {}): RawSummary {
  const channels = ["virtualpos", "toku", "payku", "tch"];
  const base: RawSummary = {
    month: "2026-10",
    timezone: "America/Santiago",
    generated_at: "2026-10-15T12:00:00-03:00",
    is_current_month: true,
    channels,
    kpis: {
      socios_totales: rawKpi(8, 9, "count", { socios_totales_nota: "suma por canal, no deduplicada", socios_totales_unidad: "suscripciones" }),
      activaciones: rawKpi(3, 1, "count"),
      bajas: rawKpi(4, 1, "count"),
      crecimiento_neto: rawKpi(-1, 0, "count"),
      churn: rawKpi(44.4, 11.1, "pct", {
        churn_definicion: "Propuesta pendiente de confirmación: bajas del mes ÷ socios al inicio del mes (cierre del mes anterior), en porcentaje y con la misma definición en todos los canales.",
        churn_window_label: "mes calendario (hora de Chile): bajas del mes ÷ socios al cierre del mes anterior",
      }),
      ingreso_total: rawKpi(92000, 75000, "clp"),
      ingreso_por_canal: {
        virtualpos: rawKpi(15000, 20000, "clp"),
        toku: rawKpi(20000, 15000, "clp"),
        payku: rawKpi(7000, null, "clp"),
        tch: rawKpi(50000, 40000, "clp"),
      },
      acumulado_anio: rawKpi(168000, 76000, "clp"),
      cobrabilidad: rawKpi(66.7, 78.6, "pct"),
      no_cobrado: rawKpi(30000, 11000, "clp"),
      por_cobrar: rawKpi(10000, 0, "clp"),
      mrr: rawKpi(90000, null, "clp", { por_canal: { virtualpos: 25000, toku: 8000, payku: 7000, tch: 50000 } }),
      arpu: rawKpi(12857, null, "clp"),
    },
    series: {
      months: MONTHS_12,
      ingreso_por_canal: MONTHS_12.map((month, i) => ({
        month,
        total: 40000 + i * 4000,
        canales: { virtualpos: 10000 + i * 500, toku: 10000 + i * 1000, payku: i < 3 ? null : 5000, tch: 20000 + i * 1500 },
      })),
      activaciones: MONTHS_12.map((month, i) => ({ month, valor: 1 + (i % 3) })),
      bajas: MONTHS_12.map((month, i) => ({ month, valor: i % 2 })),
      socios_totales: MONTHS_12.map((month, i) => ({ month, valor: 5 + i })),
    },
    calidad_datos: { altas_sin_fecha: 0, bajas_sin_fecha: 0 },
  };
  return { ...base, ...overrides };
}

/** Mes sin ningún dato: todo `null` (no ceros), como lo describe el contrato. */
export function rawEmptyMonth(month = "2027-01"): RawSummary {
  const nullKpi = (unit: "count" | "clp" | "pct", extra: RawKpi = {}) => rawKpi(null, null, unit, extra);
  const months = MONTHS_12;
  return rawSummary({
    month,
    is_current_month: false,
    kpis: {
      socios_totales: nullKpi("count", { socios_totales_nota: "suma por canal, no deduplicada", socios_totales_unidad: "suscripciones" }),
      activaciones: nullKpi("count"),
      bajas: nullKpi("count"),
      crecimiento_neto: nullKpi("count"),
      churn: nullKpi("pct", { churn_definicion: "Propuesta pendiente de confirmación", churn_window_label: "mes calendario" }),
      ingreso_total: nullKpi("clp"),
      ingreso_por_canal: { virtualpos: nullKpi("clp"), toku: nullKpi("clp"), payku: nullKpi("clp"), tch: nullKpi("clp") },
      acumulado_anio: nullKpi("clp"),
      cobrabilidad: nullKpi("pct"),
      no_cobrado: nullKpi("clp"),
      por_cobrar: nullKpi("clp"),
      mrr: nullKpi("clp", { por_canal: { virtualpos: null, toku: null, payku: null, tch: null } }),
      arpu: nullKpi("clp"),
    },
    series: {
      months,
      ingreso_por_canal: months.map((m) => ({ month: m, total: null, canales: { virtualpos: null, toku: null, payku: null, tch: null } })),
      activaciones: months.map((m) => ({ month: m, valor: null })),
      bajas: months.map((m) => ({ month: m, valor: null })),
      socios_totales: months.map((m) => ({ month: m, valor: null })),
    },
  });
}

/** Respuesta de un usuario que solo puede ver un canal: el resto NO aparece en ninguna parte. */
export function rawSingleChannel(channel: "toku" = "toku"): RawSummary {
  const full = rawSummary();
  const kpis = { ...full.kpis, ingreso_por_canal: { [channel]: (full.kpis.ingreso_por_canal as Record<string, unknown>)[channel] }, mrr: rawKpi(8000, null, "clp", { por_canal: { [channel]: 8000 } }) };
  const series = {
    ...full.series,
    ingreso_por_canal: (full.series.ingreso_por_canal as Array<{ month: string; total: number | null; canales: Record<string, number | null> }>).map((p) => ({ month: p.month, total: p.canales[channel], canales: { [channel]: p.canales[channel] } })),
  };
  return rawSummary({ channels: [channel], kpis, series });
}
