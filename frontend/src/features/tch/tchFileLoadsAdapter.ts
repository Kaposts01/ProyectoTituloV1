/**
 * Registro de reportes Excel TCH cargados (TCH-PAR-11): contrato de `GET /api/v1/tch/archivos` y su adaptador.
 * Solo metadatos del archivo (fecha, hash, mes, filas, resultado); el backend no envía datos personales.
 */

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
};

const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);

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

/** Primeros 12 caracteres del sha256 (el completo va en el `title`). */
export const shortHash = (sha256: string): string => sha256.slice(0, 12);
