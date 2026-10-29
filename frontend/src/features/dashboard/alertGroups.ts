import type { DashboardAlert } from "../shared/types";

export type AlertSev = "alta" | "media" | "baja";

export type AlertGroup = {
  key: string;
  tipo: string;
  canal: string;
  /** Severidad máxima de las alertas del grupo. */
  sev: AlertSev;
  /** Valor numérico más alto parseable de los detalles del grupo (null si ninguno lo es). */
  value: number | null;
  /** Detalle de la alerta con mayor valor (la «peor»); es el texto que resume al grupo. */
  detalle: string;
  alerts: DashboardAlert[];
};

const SEV_RANK: Record<AlertSev, number> = { alta: 3, media: 2, baja: 1 };

/** Severidad desconocida o ausente cae a «baja» para que toda fila tenga texto de severidad. */
export function normalizeSev(sev: unknown): AlertSev {
  const s = String(sev ?? "").trim().toLowerCase();
  return s === "alta" || s === "media" || s === "baja" ? s : "baja";
}

const NUMBER_RE = /-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?/;

/** Primer número del texto, leyendo formato es-CL («1.234,5»). null si no hay ninguno. */
export function parseDetailValue(detalle: string | null | undefined): number | null {
  const match = NUMBER_RE.exec(String(detalle ?? ""));
  if (!match) return null;
  const n = Number(match[0].replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/**
 * Agrupa por (tipo, canal). Criterio de orden de los grupos:
 *  1. severidad máxima del grupo (alta > media > baja);
 *  2. valor numérico más alto parseable de los detalles (mayor primero; sin número al final);
 *  3. tipo y canal alfabéticos (desempate determinista).
 * Dentro de un grupo, si todas las alertas traen `periodo` (YYYY-MM) van del más reciente al más
 * antiguo; si no, se conserva el orden original.
 */
export function groupAlerts(alerts: DashboardAlert[]): AlertGroup[] {
  const byKey = new Map<string, AlertGroup>();
  for (const alert of alerts) {
    const tipo = String(alert.tipo ?? "");
    const canal = String(alert.canal ?? "");
    const key = `${tipo}\u0000${canal}`;
    const sev = normalizeSev(alert.sev);
    const value = parseDetailValue(alert.detalle);
    const group = byKey.get(key);
    if (!group) {
      byKey.set(key, { key, tipo, canal, sev, value, detalle: String(alert.detalle ?? ""), alerts: [alert] });
      continue;
    }
    group.alerts.push(alert);
    if (SEV_RANK[sev] > SEV_RANK[group.sev]) group.sev = sev;
    if (value !== null && (group.value === null || value > group.value)) {
      group.value = value;
      group.detalle = String(alert.detalle ?? "");
    }
  }
  const groups = [...byKey.values()];
  for (const g of groups) {
    if (g.alerts.length > 1 && g.alerts.every((a) => a.periodo)) {
      g.alerts = [...g.alerts].sort((x, y) => String(y.periodo).localeCompare(String(x.periodo)));
    }
  }
  return groups.sort((a, b) => {
    if (SEV_RANK[b.sev] !== SEV_RANK[a.sev]) return SEV_RANK[b.sev] - SEV_RANK[a.sev];
    if (a.value !== b.value) {
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      return b.value - a.value;
    }
    return a.tipo.localeCompare(b.tipo, "es") || a.canal.localeCompare(b.canal, "es");
  });
}
