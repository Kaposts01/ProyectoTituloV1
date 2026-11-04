import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { ApiError, getJson, postForm } from "../../api";
import { label, tryLabel } from "../../i18n/label";
import { formatDateTime } from "../billing/billingLabels";

/** Permiso del backend para cargar reportes de Toku (DEC-22; solo admin por defecto). */
export const TOKU_REPORTS_PERMISSION = "toku.reports.import";
const UPLOAD_URL = "/api/v1/imports/toku-reports";
const STATUS_URL = "/api/v1/imports/toku-reports/status";

export type TokuReportFreshness = {
  report_type: string;
  generated_at: string | null;
  loaded_at: string | null;
  rows_total: number;
  age_days: number | null;
  is_stale: boolean;
  /** L7-IMPORT: nombre del archivo (sin ruta) y resultado de la carga. Opcionales para respuestas antiguas. */
  filename?: string | null;
  result?: string | null;
};
export type TokuReportsStatus = { max_age_days: number; reports: TokuReportFreshness[]; stale_types: string[] };
export type TokuReportSummary = {
  report_type: string;
  rows_total: number;
  rows_new: number;
  rows_updated: number;
  rows_skipped: number;
  rows_stale: number;
  data_age_days?: number | null;
  warnings: string[];
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return tryLabel("tokuReportError", "permission_denied") ?? error.message;
    const known = error.code ? tryLabel("tokuReportError", error.code) : undefined;
    if (known) return known;
  }
  return tryLabel("tokuReportError", "import_failed") ?? "No se pudo cargar el reporte.";
}

function warningText(code: string): string {
  return tryLabel("tokuReportWarning", code) ?? label("tokuReportWarning", code);
}

/**
 * Panel de carga de reportes de Toku (TK-19 / TK-PAR-02): sube un .xlsx al POST existente y muestra la frescura del
 * último archivo por tipo, con aviso si el dato tiene más de 7 días (DEC-21). Solo con `toku.reports.import`.
 * Nunca muestra filas del archivo: solo tipo, fechas y contadores.
 */
export function TokuReportsSection({ permissions, nested = false }: { permissions: string[]; nested?: boolean }) {
  const allowed = permissions.includes(TOKU_REPORTS_PERMISSION);
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<TokuReportsStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [summary, setSummary] = useState<TokuReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getJson<TokuReportsStatus>(STATUS_URL).then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => { if (allowed) refresh(); }, [allowed, refresh]);

  if (!allowed) return null;

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    setSummary(null);
    try {
      const form = new FormData();
      form.append("report", file);
      setSummary(await postForm<TokuReportSummary>(UPLOAD_URL, form));
      refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setUploading(false);
    }
  }

  const maxAge = status?.max_age_days ?? 7;
  const Title = nested ? "h3" : "h2";
  return (
    <section className="panel toku-reports-section" aria-labelledby="toku-reports-title">
      <Title id="toku-reports-title" className="section-title">Reportes de Toku</Title>
      <p className="muted-copy">
        Carga semanal de los reportes .xlsx exportados del Backoffice de Toku. Se avisa cuando el dato tiene más de {maxAge} días.
      </p>
      {status && status.stale_types.length > 0 && (
        <p role="alert" className="export-warning">
          Hay reportes con dato de más de {maxAge} días: {status.stale_types.map((t) => label("tokuReportType", t)).join(", ")}.
          Exporta reportes nuevos desde Toku.
        </p>
      )}
      {status && status.reports.length === 0 && <p className="muted-copy">Todavía no se ha cargado ningún reporte.</p>}
      {status && status.reports.length > 0 && (
        <table className="toku-reports-table">
          <thead>
            <tr><th>Reporte</th><th>Fecha del dato</th><th>Antigüedad</th><th>Cargado</th><th>Archivo</th><th>Filas</th><th>Resultado</th></tr>
          </thead>
          <tbody>
            {status.reports.map((row) => (
              <tr key={row.report_type} data-stale={row.is_stale ? "true" : undefined}>
                <td>{label("tokuReportType", row.report_type)}</td>
                <td className="mono">{formatDateTime(row.generated_at)}</td>
                <td>
                  <span className="mono">{row.age_days ?? "—"}</span>{row.age_days !== null ? " días" : ""}
                  {row.is_stale ? <strong> (más de {maxAge} días)</strong> : null}
                </td>
                <td className="mono">{formatDateTime(row.loaded_at)}</td>
                <td className="mono">{row.filename ?? "—"}</td>
                <td className="mono">{row.rows_total}</td>
                <td>{row.result ? label("reportImportResult", row.result) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <input ref={inputRef} type="file" accept=".xlsx" hidden aria-label="Archivo de reporte de Toku" onChange={upload} />
      <button type="button" className="primary-button" disabled={uploading} onClick={() => inputRef.current?.click()}>
        {uploading ? "Cargando…" : "Cargar reporte .xlsx"}
      </button>
      {error && <p role="alert" className="export-warning">{error}</p>}
      {summary && (
        <div className="toku-reports-summary" role="status">
          <p>
            Reporte de {label("tokuReportType", summary.report_type)} cargado: <span className="mono">{summary.rows_new}</span> nuevas,{" "}
            <span className="mono">{summary.rows_updated}</span> actualizadas, <span className="mono">{summary.rows_skipped}</span> omitidas
            {summary.rows_stale ? <> y <span className="mono">{summary.rows_stale}</span> sin aplicar</> : null}.
          </p>
          {summary.warnings.length > 0 && (
            <ul>{summary.warnings.map((w) => <li key={w} className="export-warning">{warningText(w)}</li>)}</ul>
          )}
        </div>
      )}
    </section>
  );
}
