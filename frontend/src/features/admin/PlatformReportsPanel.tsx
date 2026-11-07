import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { ApiError, friendlyError, getJson, postForm } from "../../api";
import { label, tryLabel } from "../../i18n/label";
import { formatDateTime } from "../billing/billingLabels";
import { TOKU_REPORTS_PERMISSION, TokuReportsSection } from "./TokuReportsSection";

/** Permisos de carga por canal (backend `IMPORT_PERMISSIONS`). TCH no tiene permiso propio: exige el rol admin. */
export const VP_REPORTS_PERMISSION = "virtualpos.reports.import";
export const PAYKU_REPORTS_PERMISSION = "payku.reports.import";
export const IMPORTS_STATUS_URL = "/api/v1/imports/status";

export type ChannelKey = "virtualpos" | "payku" | "tch";

export type ReportLoad = {
  report_type: string;
  filename: string | null;
  loaded_at: string | null;
  rows_total: number | null;
  rows_new: number | null;
  rows_updated: number | null;
  rows_skipped: number | null;
  result: string | null;
  error_label: string | null;
  data_at: string | null;
  age_days: number | null;
  is_stale: boolean;
};
export type ChannelImportStatus = { channel: string; reports: ReportLoad[]; stale_types: string[] };
export type ImportsStatus = { max_age_days: number; channels: ChannelImportStatus[] };

type UploadSummary = {
  report_type: string;
  rows_total: number;
  rows_new: number;
  rows_updated: number;
  rows_skipped: number;
  warnings?: string[];
};

type ChannelConfig = {
  key: ChannelKey;
  title: string;
  description: string;
  accept: ".csv" | ".xlsx";
  uploadUrl: string;
  /** TCH importa en segundo plano (202 con `run_id`): no hay resumen de filas inmediato. */
  background?: boolean;
};

const CHANNELS: ChannelConfig[] = [
  {
    key: "virtualpos",
    title: "Reportes PAT de VirtualPOS",
    description: "Archivos .csv TransaccionesPAT o SuscriptoresPAT exportados del portal. La glosa de rechazo del reporte manda sobre la de la API.",
    accept: ".csv",
    uploadUrl: "/api/v1/imports/virtualpos-reports",
  },
  {
    key: "payku",
    title: "Reportes de Payku",
    description: "Archivos .xlsx exportados del portal de Payku: dataTransacciones, consolidado anual o datasubscripciones. Se validan los encabezados antes de cargar.",
    accept: ".xlsx",
    uploadUrl: "/api/v1/imports/payku-reports",
  },
  {
    key: "tch",
    title: "Reporte Excel de TCH",
    description: "Reporte .xlsx de TCH. La importación corre en segundo plano y su avance se ve en el panel de sincronización.",
    accept: ".xlsx",
    uploadUrl: "/api/v1/tch/import-report",
    background: true,
  },
];

function uploadError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return tryLabel("reportImportError", "permission_denied") ?? error.message;
    const known = error.code ? tryLabel("reportImportError", error.code) : undefined;
    if (known) return known;
  }
  return friendlyError(error, tryLabel("reportImportError", "import_failed") ?? "No se pudo cargar el reporte.");
}

function warningText(code: string): string {
  return tryLabel("reportImportWarning", code) ?? label("reportImportWarning", code);
}

function resultTone(result: string | null): string {
  const tones: Record<string, string> = {
    "completed": "green", "consolidado": "green", "cargado": "blue", "running": "blue", "failed": "orange", "fallido": "orange",
  };
  return tones[result ?? ""] ?? "gray";
}

function ReportImportCard({ config, status, maxAge, onUploaded }: {
  config: ChannelConfig;
  status: ChannelImportStatus | undefined;
  maxAge: number;
  onUploaded: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [summary, setSummary] = useState<UploadSummary | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = `platform-reports-${config.key}`;

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    setSummary(null);
    setAccepted(false);
    try {
      const form = new FormData();
      form.append("report", file);
      const response = await postForm<UploadSummary | { run_id: string }>(config.uploadUrl, form);
      if (config.background) setAccepted(true);
      else setSummary(response as UploadSummary);
      onUploaded();
    } catch (err) {
      setError(uploadError(err));
    } finally {
      setUploading(false);
    }
  }

  const reports = status?.reports ?? [];
  const stale = status?.stale_types ?? [];
  return (
    <section className="panel platform-reports-card" aria-labelledby={titleId} data-channel={config.key}>
      <h3 id={titleId} className="section-title">{config.title}</h3>
      <p className="muted-copy">{config.description}</p>
      {stale.length > 0 && (
        <p role="alert" className="export-warning">
          Hay archivos con dato de más de {maxAge} días: {stale.map((t) => label("platformReportType", t)).join(", ")}.
          Exporta y carga un reporte nuevo.
        </p>
      )}
      {reports.length > 0 && (
        <div className="table-wrap">
          <table className="platform-reports-table">
            <thead>
              <tr><th>Archivo</th><th>Última carga</th><th>Nombre</th><th>Filas</th><th>Resultado</th><th>Antigüedad del dato</th></tr>
            </thead>
            <tbody>
              {reports.map((row) => (
                <tr key={row.report_type} data-stale={row.is_stale ? "true" : undefined}>
                  <td>{label("platformReportType", row.report_type)}</td>
                  <td className="mono">{formatDateTime(row.loaded_at)}</td>
                  <td className="mono">{row.filename ?? "—"}</td>
                  <td className="mono">{row.rows_total?.toLocaleString("es-CL") ?? "—"}</td>
                  <td>
                    {row.result
                      ? <span className={`badge badge-${resultTone(row.result)}`}>{label("reportImportResult", row.result)}</span>
                      : <span className="muted-copy">Sin cargas</span>}
                  </td>
                  <td>
                    <span className="mono">{row.age_days ?? "—"}</span>{row.age_days !== null ? " días" : ""}
                    {row.is_stale ? <strong> (más de {maxAge} días)</strong> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <input ref={inputRef} type="file" accept={config.accept} hidden aria-label={`Archivo: ${config.title}`} onChange={upload} />
      <button type="button" className="primary-button" disabled={uploading} onClick={() => inputRef.current?.click()}>
        {uploading ? "Cargando…" : `Cargar archivo ${config.accept}`}
      </button>
      {error && <p role="alert" className="export-warning">{error}</p>}
      {accepted && (
        <p role="status">Importación iniciada. El avance se ve en el panel de sincronización de esta página.</p>
      )}
      {summary && (
        <div className="platform-reports-summary" role="status">
          <p>
            Archivo de {label("platformReportType", summary.report_type)} cargado: <span className="mono">{summary.rows_new}</span> nuevas,{" "}
            <span className="mono">{summary.rows_updated}</span> actualizadas, <span className="mono">{summary.rows_skipped}</span> omitidas
            (de <span className="mono">{summary.rows_total.toLocaleString("es-CL")}</span> filas).
          </p>
          {(summary.warnings ?? []).length > 0 && (
            <ul>{(summary.warnings ?? []).map((w) => <li key={w} className="export-warning">{warningText(w)}</li>)}</ul>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Panel unificado «Importar reportes de plataformas» (L7-IMPORT, d151): reúne la carga manual de los archivos que
 * exporta cada canal. Cada canal aparece solo con su permiso: Toku (`toku.reports.import`, reutiliza
 * TokuReportsSection), VirtualPOS (`virtualpos.reports.import`), Payku (`payku.reports.import`) y TCH (rol admin, la
 * misma importación del panel de sincronización). Muestra la última carga por tipo de archivo y avisa del dato con más
 * de 7 días. Nunca muestra filas de los archivos: solo tipo, fechas, nombre del archivo y contadores.
 */
export function PlatformReportsPanel({ permissions, isAdmin }: { permissions: string[]; isAdmin: boolean }) {
  const allowed: Record<ChannelKey, boolean> = {
    virtualpos: permissions.includes(VP_REPORTS_PERMISSION),
    payku: permissions.includes(PAYKU_REPORTS_PERMISSION),
    tch: isAdmin,
  };
  const canToku = permissions.includes(TOKU_REPORTS_PERMISSION);
  const visible = CHANNELS.filter((c) => allowed[c.key]);
  const anyChannel = canToku || visible.length > 0;
  const [status, setStatus] = useState<ImportsStatus | null>(null);
  const [statusError, setStatusError] = useState(false);

  const refresh = useCallback(() => {
    getJson<ImportsStatus>(IMPORTS_STATUS_URL)
      .then((data) => { setStatus(data); setStatusError(false); })
      .catch(() => setStatusError(true));
  }, []);

  const needsStatus = visible.length > 0;
  useEffect(() => { if (needsStatus) refresh(); }, [needsStatus, refresh]);

  if (!anyChannel) return null;
  const maxAge = status?.max_age_days ?? 7;
  return (
    <section className="platform-reports" aria-labelledby="platform-reports-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CARGA MANUAL</p>
          <h2 id="platform-reports-title">Importar reportes de plataformas</h2>
        </div>
      </div>
      <p className="muted-copy">
        Carga aquí los archivos que exporta cada plataforma. Cada carga muestra la última vez que se subió cada tipo de
        archivo y avisa cuando el dato tiene más de {maxAge} días.
      </p>
      {statusError && <p role="alert" className="export-warning">No se pudo leer el estado de las cargas. Reintenta más tarde.</p>}
      {canToku && <TokuReportsSection permissions={permissions} nested />}
      {visible.map((config) => (
        <ReportImportCard
          key={config.key}
          config={config}
          status={status?.channels.find((c) => c.channel === config.key)}
          maxAge={maxAge}
          onUploaded={refresh}
        />
      ))}
    </section>
  );
}
