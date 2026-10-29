import { formatKpi, hasKpiValue, type KpiFormat } from "./formatKpi";

export const KPI_EMPTY_CAPTION = "Sin base para calcular";

/** Estado de una meta: «en meta», «lejos de meta» o «sin meta» (chip con dot + texto, nunca solo color). */
export type KpiChipStatus = "met" | "off" | "none";
const CHIP_TEXT: Record<KpiChipStatus, string> = { met: "en meta", off: "lejos de meta", none: "sin meta" };

/**
 * Meta de la tarjeta. `target` ausente (null/undefined) = «sin meta».
 * `direction`: `atLeast` (por defecto; ingreso, altas: se llena una barra de progreso) o `atMost`
 * (tope: churn, rechazo; se cumple si value <= target y no lleva barra, solo el texto «Meta: ≤ X»).
 */
export type KpiGoal = { target: number | null | undefined; direction?: "atLeast" | "atMost" };

/**
 * Variación contra el período anterior. `value` = diferencia ya calculada (no porcentaje);
 * null = sin dato. `goodWhen`: "up" (por defecto) o "down" (churn, rechazos: bajar es bueno).
 * `format` por defecto = el de la tarjeta; en porcentaje se expresa en «pts».
 */
export type KpiDelta = { value: number | null | undefined; goodWhen?: "up" | "down"; format?: KpiFormat; label?: string };

/** Estado de la meta para un valor; "none" sin meta o sin valor medible. */
export function goalStatus(value: number | null | undefined, goal: KpiGoal | undefined): KpiChipStatus {
  if (!goal || !hasKpiValue(goal.target) || !hasKpiValue(value)) return "none";
  return (goal.direction === "atMost" ? value <= goal.target : value >= goal.target) ? "met" : "off";
}

function formatDelta(value: number, format: KpiFormat): string {
  const sign = value > 0 ? "+" : "";
  if (format === "percent") {
    const r = Math.round(value * 10) / 10;
    return `${r > 0 ? "+" : ""}${(r === 0 ? 0 : r).toLocaleString("es-CL", { maximumFractionDigits: 1 })} pts`;
  }
  return `${sign}${formatKpi(value, format)}`;
}

const SPARK_W = 80;
const SPARK_H = 24;

/** Mini serie decorativa. Menos de 2 puntos válidos: no se dibuja. La tendencia siempre va también en texto (delta). */
function Sparkline({ values, label }: { values: number[]; label?: string }) {
  const pts = values.filter((v) => Number.isFinite(v));
  if (pts.length < 2) return null;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const points = pts
    .map((v, i) => `${((i / (pts.length - 1)) * SPARK_W).toFixed(1)},${(SPARK_H - 2 - ((v - min) / span) * (SPARK_H - 4)).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="kpi-spark" viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} width={SPARK_W} height={SPARK_H} preserveAspectRatio="none"
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/**
 * Tarjeta de KPI (v2). `null`/`undefined`/NaN se muestran como «—» con texto accesible «sin datos»
 * (el 0 es un valor real y se muestra como 0). Con valor ausente, `emptyCaption` reemplaza al
 * `caption` y no se muestran delta, barra ni chip derivado (no se inventa un avance).
 *
 * Props:
 * - `variant`: "normal" (superficie) o "featured" (rellena con --kpi-hero-bg; usar 1-2 por pantalla).
 * - `delta`: variación vs mes anterior con flecha ▲▼▬, color semántico y texto («sube/baja/sin cambio»).
 * - `goal`: meta; con `atLeast` dibuja barra de progreso con «X % de la meta» (la barra topa en 100 %,
 *   el texto dice el avance real); con `atMost` muestra «Meta: ≤ X».
 * - `chip`: fuerza el chip «en meta / lejos de meta / sin meta»; si falta se deriva de `goal`.
 * - `sparkline` / `sparklineLabel`: serie opcional; decorativa (aria-hidden) salvo que haya etiqueta.
 */
export function KpiCard({ label, value, format, caption, emptyCaption, variant = "normal", delta, goal, chip, sparkline, sparklineLabel }: {
  label: string;
  value: number | null | undefined;
  format: KpiFormat;
  caption?: string;
  emptyCaption?: string;
  variant?: "normal" | "featured";
  delta?: KpiDelta;
  goal?: KpiGoal;
  chip?: KpiChipStatus;
  sparkline?: number[];
  sparklineLabel?: string;
}) {
  const empty = !hasKpiValue(value);
  const sub = empty ? emptyCaption : caption;
  const chipStatus: KpiChipStatus | null = chip ?? (goal ? (empty && hasKpiValue(goal.target) ? null : goalStatus(value, goal)) : null);

  const hasTarget = goal !== undefined && hasKpiValue(goal.target);
  const atMost = goal?.direction === "atMost";
  const showBar = !empty && hasTarget && !atMost && (goal!.target as number) > 0;
  const pct = showBar ? Math.round(((value as number) / (goal!.target as number)) * 100) : 0;
  const goalText = hasTarget
    ? showBar
      ? `${pct} % de la meta (${formatKpi(goal!.target, format)})`
      : `Meta: ${atMost ? "≤ " : "≥ "}${formatKpi(goal!.target, format)}`
    : null;

  let deltaEl = null;
  if (delta && !empty) {
    const suffix = delta.label ?? "vs mes anterior";
    if (!hasKpiValue(delta.value)) {
      deltaEl = <span className="kpi-delta flat" data-testid="kpi-delta">Sin dato {suffix}</span>;
    } else {
      const dir = delta.value > 0 ? "up" : delta.value < 0 ? "down" : "flat";
      const good = dir === "flat" ? "flat" : (dir === delta.goodWhen) || (dir === "up" && delta.goodWhen === undefined) ? "good" : "bad";
      const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "▬";
      const word = dir === "up" ? "sube" : dir === "down" ? "baja" : "sin cambio";
      deltaEl = (
        <span className={`kpi-delta ${good}`} data-testid="kpi-delta">
          <span aria-hidden="true">{arrow}</span>{" "}
          <span className="sr-only">{word}: </span>
          <span className="mono">{dir === "flat" ? formatDelta(0, delta.format ?? format) : formatDelta(delta.value, delta.format ?? format)}</span> {suffix}
        </span>
      );
    }
  }

  return (
    <article className={`metric-card kpi-card${variant === "featured" ? " kpi-card--featured" : ""}`} data-variant={variant}>
      <div className="kpi-head">
        <p className="metric-label">{label}</p>
        {chipStatus ? (
          <span className={`kpi-chip ${chipStatus}`}>
            <span className="kpi-chip-dot" aria-hidden="true" />
            {CHIP_TEXT[chipStatus]}
          </span>
        ) : null}
      </div>
      <div className="kpi-main">
        <strong className="metric-value kpi-value mono" {...(empty ? { role: "img", "aria-label": "sin datos" } : {})}>{formatKpi(value, format)}</strong>
        {sparkline ? <Sparkline values={sparkline} label={sparklineLabel} /> : null}
      </div>
      {showBar ? (
        <div className="kpi-progress" role="progressbar" aria-label={`Avance de ${label} hacia la meta`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.max(0, pct))}>
          <span className="kpi-progress-fill" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
        </div>
      ) : null}
      {goalText && !empty ? <span className="kpi-goal">{goalText}</span> : null}
      {deltaEl}
      {sub ? <span className="metric-amount">{sub}</span> : null}
    </article>
  );
}

/**
 * Tarjeta de churn (D20): valor + chip de meta + meta de tope + sparkline del histórico, en lugar de un
 * velocímetro. `previous` es el churn del mes anterior (el delta se calcula acá; bajar es bueno).
 */
export function ChurnKpiCard({ churnRate, target, history, previous, windowLabel, label = "Churn", variant }: {
  churnRate: number | null | undefined;
  target: number | null | undefined;
  history?: number[];
  previous?: number | null;
  windowLabel?: string;
  label?: string;
  variant?: "normal" | "featured";
}) {
  const hasDelta = hasKpiValue(churnRate) && hasKpiValue(previous);
  return (
    <KpiCard
      label={label}
      value={churnRate}
      format="percent"
      variant={variant}
      goal={{ target, direction: "atMost" }}
      delta={hasDelta ? { value: (churnRate as number) - (previous as number), goodWhen: "down" } : undefined}
      sparkline={history}
      caption={windowLabel}
      emptyCaption={KPI_EMPTY_CAPTION}
    />
  );
}
