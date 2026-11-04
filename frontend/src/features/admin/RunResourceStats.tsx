import { useEffect, useState } from "react";
import { getJson } from "../../api";

/** SYNC-D-17: estadisticas por recurso de una fila de `GET /api/v1/sync-runs`. */
export type ResourceStat = {
  mode?: string;
  seconds?: number;
  pages?: number;
  records?: number;
  inserted?: number;
  updated?: number;
  unchanged?: number;
};
export type ChannelSyncRun = {
  id: string;
  source: string;
  status: string;
  duration_seconds: number | null;
  resource_stats: Record<string, ResourceStat> | null;
};

const SOURCE_LABEL: Record<string, string> = {
  virtualpos1: "VP1",
  virtualpos2: "VP2",
  toku: "Toku",
  payku: "Payku",
};
const RESOURCE_LABEL: Record<string, string> = {
  client: "Clientes",
  customer: "Clientes",
  payment: "Pagos",
  subscription: "Suscripciones",
  charge: "Cobros",
  plan: "Planes",
  invoice: "Facturas",
  transaction: "Transacciones",
  payment_method: "Medios de pago",
};
const MODE_LABEL: Record<string, string> = { full: "Completa", window: "Ventana" };

const num = (value: number | undefined) => (value == null ? "—" : value.toLocaleString("es-CL"));
const secs = (value: number | null | undefined) => (value == null ? "—" : `${value.toLocaleString("es-CL", { maximumFractionDigits: 1 })} s`);

/** Detalle de una corrida global: por canal y recurso, modo de lectura, filas nuevas/actualizadas/sin cambio y duración. */
export function RunResourceStats({ etlRunId }: { etlRunId: string }) {
  const [runs, setRuns] = useState<ChannelSyncRun[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getJson<ChannelSyncRun[]>(`/api/v1/sync-runs?etl_run_id=${encodeURIComponent(etlRunId)}`)
      .then((data) => { if (alive) setRuns(data); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [etlRunId]);

  if (error) return <p className="muted-copy">No se pudo cargar el detalle por recurso.</p>;
  if (runs === null) return <p className="muted-copy">Cargando detalle…</p>;
  const rows = runs.flatMap((run) =>
    Object.entries(run.resource_stats ?? {}).map(([resource, stat]) => ({ run, resource, stat })),
  );
  if (rows.length === 0) return <p className="muted-copy">Sin detalle por recurso para esta ejecución.</p>;

  return (
    <table className="scheduler-jobs-table run-resource-stats">
      <thead>
        <tr><th>Canal</th><th>Recurso</th><th>Lectura</th><th>Nuevos</th><th>Actualizados</th><th>Sin cambio</th><th>Duración</th></tr>
      </thead>
      <tbody>
        {rows.map(({ run, resource, stat }) => (
          <tr key={`${run.id}-${resource}`}>
            <td>{SOURCE_LABEL[run.source] ?? run.source}</td>
            <td>{RESOURCE_LABEL[resource] ?? resource}</td>
            <td>{MODE_LABEL[stat.mode ?? ""] ?? stat.mode ?? "—"}</td>
            <td className="runs-rec-val mono-num">{num(stat.inserted)}</td>
            <td className="runs-rec-val mono-num">{num(stat.updated)}</td>
            <td className="runs-rec-val mono-num">{num(stat.unchanged)}</td>
            <td className="runs-rec-val mono-num">{secs(stat.seconds)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
