import { useEffect, useState } from "react";
import { friendlyError, getJson } from "../../api";
import { label } from "../../i18n/label";
import {
  adaptTchFileLoads, controlBadge, controlDetail, resultBadgeTone, shortDateTime, shortHash, type TchFileLoad, type TchFileLoadsWire,
} from "./tchFileLoadsAdapter";

const count = (value: number | null | undefined): string => (value === null || value === undefined ? "—" : value.toLocaleString("es-CL"));

/**
 * Archivos cargados (TCH-PAR-11): por reporte Excel, la fecha de carga, el hash, el mes, el resultado y la
 * conciliación del archivo: filas leídas, insertadas, actualizadas, omitidas y con error (suscripciones + cuotas) y si
 * el mes del reporte cuadra con el control del propio Excel. Se muestra solo con el permiso `sync_runs.view` (el
 * mismo del endpoint); no hay datos personales.
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
              <tr>
                <th>Fecha de carga</th><th>Archivo</th><th>Mes</th><th>Leídas</th><th>Insertadas</th><th>Actualizadas</th>
                <th>Omitidas</th><th>Con error</th><th>Control del Excel</th><th>Hash (sha256)</th><th>Resultado</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const badge = controlBadge(file.control);
                const detail = controlDetail(file.control);
                return (
                <tr key={file.sha256}>
                  <td className="mono">{shortDateTime(file.loadedAt)}</td>
                  <td>{file.fileName}</td>
                  <td className="mono">{file.period ?? "—"}</td>
                  {/* Sin conciliación guardada (archivo anterior a TCH-PAR-11) se muestran las filas cargadas como leídas. */}
                  <td className="mono num">{count(file.counts ? file.counts.read : file.rows)}</td>
                  <td className="mono num">{count(file.counts?.inserted)}</td>
                  <td className="mono num">{count(file.counts?.updated)}</td>
                  <td className="mono num">{count(file.counts?.skipped)}</td>
                  <td className="mono num">{count(file.counts?.errors)}</td>
                  <td>
                    {file.result === "fallido" ? "—" : (
                      <span className={`badge badge-${badge.tone}`} title={detail ?? "El archivo no trae control para el mes del reporte"}>
                        {badge.text}
                      </span>
                    )}
                    {detail && file.control?.matches === false ? <p className="muted-copy mono">{detail}</p> : null}
                  </td>
                  <td className="mono" title={file.sha256}>{shortHash(file.sha256)}</td>
                  <td>
                    <span className={`badge badge-${resultBadgeTone(file.result)}`} title={file.error ?? undefined}>
                      {label("tchFileResult", file.result)}
                    </span>
                    {file.result === "fallido" && file.error ? <p className="muted-copy">{file.error}</p> : null}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
