export type KpiFormat = "clp" | "count" | "percent";

/** true si hay un número real (0 incluido); false para null/undefined/NaN/±Infinity. */
export function hasKpiValue(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function formatKpi(value: number | null | undefined, format: KpiFormat): string {
  if (!hasKpiValue(value)) return "—";
  if (format === "percent") {
    const rounded = Math.round(value * 10) / 10;
    return `${(rounded === 0 ? 0 : rounded).toLocaleString("es-CL", { maximumFractionDigits: 1 })}%`;
  }
  const rounded = Math.round(value);
  const abs = Math.abs(rounded).toLocaleString("es-CL");
  if (format === "clp") return `${rounded < 0 ? "-" : ""}$${abs}`;
  return `${rounded < 0 ? "-" : ""}${abs}`;
}

/** Estado de una meta: «en meta», «lejos de meta» o «sin meta» (chip con dot + texto, nunca solo color). */
export type KpiChipStatus = "met" | "off" | "none";

/**
 * Meta de la tarjeta. `target` ausente (null/undefined) = «sin meta».
 * `direction`: `atLeast` (por defecto; ingreso, altas: se llena una barra de progreso) o `atMost`
 * (tope: churn, rechazo; se cumple si value <= target y no lleva barra, solo el texto «Meta: ≤ X»).
 */
export type KpiGoal = { target: number | null | undefined; direction?: "atLeast" | "atMost" };

/** Estado de la meta para un valor; "none" sin meta o sin valor medible. */
export function goalStatus(value: number | null | undefined, goal: KpiGoal | undefined): KpiChipStatus {
  if (!goal || !hasKpiValue(goal.target) || !hasKpiValue(value)) return "none";
  return (goal.direction === "atMost" ? value <= goal.target : value >= goal.target) ? "met" : "off";
}
