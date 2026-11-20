/**
 * Medición de Core Web Vitals reales (PERF-03b). Solo en la build de sandbox: escribe en la consola
 * con el prefijo `[web-vitals]` el nombre, el valor, el rating y el selector del elemento responsable.
 * No envía nada a ningún servidor ni registra texto ni datos de la pantalla.
 */
type Metric = {
  name: string;
  value: number;
  rating: string;
  attribution?: { target?: string; interactionTarget?: string; largestShiftTarget?: string };
};
type Register = (callback: (metric: Metric) => void, options?: { reportAllChanges?: boolean }) => void;
export type WebVitalsModule = { onLCP: Register; onINP: Register; onCLS: Register };

export function formatMetric(metric: Metric): string {
  const a = metric.attribution ?? {};
  const target = a.target ?? a.interactionTarget ?? a.largestShiftTarget ?? "-";
  const value = metric.name === "CLS" ? metric.value.toFixed(3) : String(Math.round(metric.value));
  return `[web-vitals] ${metric.name} ${value}${metric.name === "CLS" ? "" : " ms"} ${metric.rating} ${target}`;
}

export async function registerWebVitals(
  load: () => Promise<WebVitalsModule> = () => import("web-vitals/attribution") as unknown as Promise<WebVitalsModule>,
  log: (line: string) => void = (line) => console.info(line),
): Promise<boolean> {
  // import.meta.env.MODE se reemplaza al compilar: en producción esta rama y el import() desaparecen del bundle.
  if (import.meta.env.MODE !== "sandbox") return false;
  const { onLCP, onINP, onCLS } = await load();
  const report = (metric: Metric) => log(formatMetric(metric));
  onLCP(report, { reportAllChanges: true });
  onINP(report, { reportAllChanges: true });
  onCLS(report, { reportAllChanges: true });
  return true;
}
