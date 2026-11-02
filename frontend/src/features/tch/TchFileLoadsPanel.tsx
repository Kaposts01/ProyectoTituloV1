import { useEffect, useState } from "react";
import { friendlyError, getJson } from "../../api";
import { label } from "../../i18n/label";
import {
  adaptTchFileLoads, resultBadgeTone, shortDateTime, shortHash, type TchFileLoad, type TchFileLoadsWire,
} from "./tchFileLoadsAdapter";

/**
 * Archivos cargados (TCH-PAR-11): por reporte Excel, la fecha de carga, el hash, el mes, las filas y el resultado.
 * Se muestra solo con el permiso `sync_runs.view` (el mismo del endpoint); no hay datos personales.
 */
export function TchFileLoadsPanel() {
  const [files, setFiles] = useState<TchFileLoad[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getJson<TchFileLoadsWire>("/api/v1/tch/archivos?limit=50").then(
      (data) => { if (mounted) setFiles(adaptTchFileLoads(data)); },
      (err: unknown) => { if (mounted) setError(friendlyError(err, "No se pudo cargar el registro de archivos TCH.")); },
    );
    return () => { mounted = false; };
  }, []);

  return (
    <section className="panel" aria-label="Archivos TCH cargados">
      <div className="panel-heading"><div><p className="eyebrow">REPORTES EXCEL</p><h3>Archivos cargados</h3></div></div>
      {error ? (
        <p className="error-message">{error}</p>
      ) : files === null ? (
        <p className="muted-copy">Cargando archivos...</p>
      ) : files.length === 0 ? (
        <p className="muted-copy">Aún no hay reportes registrados.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Fecha de carga</th><th>Archivo</th><th>Mes</th><th>Filas</th><th>Hash (sha256)</th><th>Resultado</th></tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.sha256}>
                  <td className="mono">{shortDateTime(file.loadedAt)}</td>
                  <td>{file.fileName}</td>
                  <td className="mono">{file.period ?? "—"}</td>
                  <td className="mono">{file.rows === null ? "—" : file.rows.toLocaleString("es-CL")}</td>
                  <td className="mono" title={file.sha256}>{shortHash(file.sha256)}</td>
                  <td>
                    <span className={`badge badge-${resultBadgeTone(file.result)}`} title={file.error ?? undefined}>
                      {label("tchFileResult", file.result)}
                    </span>
                    {file.result === "fallido" && file.error ? <p className="muted-copy">{file.error}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
