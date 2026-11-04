/**
 * Registro de reportes Excel TCH cargados (TCH-PAR-11): contrato de `GET /api/v1/tch/archivos` y su adaptador.
 * Solo metadatos del archivo (fecha, hash, mes, filas, resultado) y su conciliación (conteos y control del propio
 * Excel); el backend no envía datos personales.
 */

/** Conteos de filas de un tipo (suscripciones, cuotas o total). */
export type RowCountsWire = {
  leidas?: number | null; insertadas?: number | null; actualizadas?: number | null; omitidas?: number | null; con_error?: number | null;
};

/** Conciliación por archivo (TCH-PAR-11): filas por tipo y control del mes del reporte contra el propio Excel. */
export type TchFileReconciliationWire = {
  filas?: { suscripciones?: RowCountsWire | null; cuotas?: RowCountsWire | null; total?: RowCountsWire | null } | null;
  control?: {
    periodo?: string | null;
    fuente?: string | null;
    cuadra?: boolean | null;
    archivo_aceptadas?: number | null;
    archivo_rechazadas?: number | null;
    control_aceptadas?: number | null;
    control_rechazadas?: number | null;
  } | null;
};

export type TchFileLoadWire = {
  sha256?: string | null;
  archivo?: string | null;
  periodo?: string | null;
  cargado_en?: string | null;
  consolidado_en?: string | null;
  filas?: number | null;
  tamano_bytes?: number | null;
  resultado?: string | null;
  error?: string | null;
  etl_run_id?: string | null;
  conciliacion?: TchFileReconciliationWire | null;
};

export type TchFileLoadsWire = { items?: TchFileLoadWire[] | null; limit?: number };

export type TchFileLoad = {
  sha256: string;
  fileName: string;
  period: string | null;
  loadedAt: string | null;
  consolidatedAt: string | null;
  rows: number | null;
  sizeBytes: number | null;
  result: string | null;
  error: string | null;
  etlRunId: string | null;
  /** null si el archivo se cargó antes de TCH-PAR-11 o falló (no hay conciliación guardada). */
  counts: RowCounts | null;
  control: ControlCheck | null;
};

export type RowCounts = { read: number; inserted: number; updated: number; skipped: number; errors: number };

/** «matches»: null = el Excel no trae control para el mes del reporte. */
export type ControlCheck = {
  period: string | null;
  matches: boolean | null;
  fileAccepted: number | null;
  fileRejected: number | null;
  controlAccepted: number | null;
  controlRejected: number | null;
};

const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);

function adaptCounts(wire: RowCountsWire | null | undefined): RowCounts | null {
  if (!wire || typeof wire !== "object") return null;
  return {
    read: num(wire.leidas) ?? 0,
    inserted: num(wire.insertadas) ?? 0,
    updated: num(wire.actualizadas) ?? 0,
    skipped: num(wire.omitidas) ?? 0,
    errors: num(wire.con_error) ?? 0,
  };
}

function adaptControl(wire: TchFileReconciliationWire["control"]): ControlCheck | null {
  if (!wire || typeof wire !== "object") return null;
  return {
    period: str(wire.periodo),
    matches: typeof wire.cuadra === "boolean" ? wire.cuadra : null,
    fileAccepted: num(wire.archivo_aceptadas),
    fileRejected: num(wire.archivo_rechazadas),
    controlAccepted: num(wire.control_aceptadas),
    controlRejected: num(wire.control_rechazadas),
  };
}

export function adaptTchFileLoads(wire: TchFileLoadsWire | null | undefined): TchFileLoad[] {
  return (wire?.items ?? [])
    .filter((item): item is TchFileLoadWire => Boolean(item && typeof item.sha256 === "string"))
    .map((item) => ({
      sha256: item.sha256 as string,
      fileName: str(item.archivo) ?? "—",
      period: str(item.periodo),
      loadedAt: str(item.cargado_en),
      consolidatedAt: str(item.consolidado_en),
      rows: num(item.filas),
      sizeBytes: num(item.tamano_bytes),
      result: str(item.resultado),
      error: str(item.error),
      etlRunId: str(item.etl_run_id),
      counts: adaptCounts(item.conciliacion?.filas?.total),
      control: adaptControl(item.conciliacion?.control),
    }));
}

/** «2026-11-02T10:05:00+00:00» -> «2026-11-02 10:05» (hora del servidor, sin conversión). */
export function shortDateTime(iso: string | null): string {
  if (!iso) return "—";
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso);
  return match ? `${match[1]} ${match[2]}` : iso.slice(0, 16);
}

/** Tono de la insignia del resultado (las claves son los valores del backend). */
export function resultBadgeTone(result: string | null): string {
  const tones: Record<string, string> = { "consolidado": "green", "cargado": "blue", "fallido": "orange" };
  return tones[result ?? ""] ?? "gray";
}

/** Rótulo y tono de la comparación con el control del propio Excel. */
export function controlBadge(control: ControlCheck | null): { text: string; tone: string } {
  if (!control || control.matches === null) return { text: "Sin control", tone: "gray" };
  return control.matches ? { text: "Cuadra", tone: "green" } : { text: "No cuadra", tone: "orange" };
}

/** «archivo 2/0 · control 2/0» (aceptadas/rechazadas del mes del reporte) para el detalle del control. */
export function controlDetail(control: ControlCheck | null): string | null {
  if (!control || control.matches === null) return null;
  const pair = (a: number | null, r: number | null) => `${a ?? "—"}/${r ?? "—"}`;
  return `${control.period ?? "—"}: archivo ${pair(control.fileAccepted, control.fileRejected)} · control ${pair(control.controlAccepted, control.controlRejected)} (aceptadas/rechazadas)`;
}

/** Primeros 12 caracteres del sha256 (el completo va en el `title`). */
export const shortHash = (sha256: string): string => sha256.slice(0, 12);
