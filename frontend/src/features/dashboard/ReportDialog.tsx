import type { FormEvent } from "react";
import { useState } from "react";

export function ReportDialog({ scope, onClose }: { scope: string; onClose: () => void }) {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const names: Record<string, string> = { general: "operación consolidada", virtualpos: "VirtualPOS", toku: "Toku", payku: "Payku", tch: "TCH" };
  function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dateFrom || !dateTo) return setError("Selecciona ambas fechas.");
    if (dateFrom >= dateTo) return setError("La fecha inicial debe ser menor que la fecha final.");
    const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
    window.open(`/api/v1/reports/${scope}?${query}`, "_blank", "noopener,noreferrer");
    onClose();
  }
  return (
    <div className="edit-dialog-backdrop" role="presentation">
      <form className="edit-dialog" aria-modal="true" aria-label="Generar reporte" onSubmit={generate}>
        <div className="edit-dialog-heading"><div><p className="eyebrow">REPORTE OPERATIVO</p><h3>{names[scope] ?? scope}</h3></div></div>
        <p className="edit-dialog-note">Los indicadores muestran el estado actual. Los gráficos se calcularán solo para el período seleccionado.</p>
        <div className="edit-form-grid">
          <label>Fecha inicial<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} required /></label>
          <label>Fecha final<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} required /></label>
        </div>
        {error ? <p className="error-message form-error">{error}</p> : null}
        <div className="edit-dialog-actions">
          <button type="submit" className="save-button">Generar reporte</button>
          <button type="button" className="cancel-button" onClick={onClose}>Cancelar</button>
        </div>
      </form>
    </div>
  );
}
