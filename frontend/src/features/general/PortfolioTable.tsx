import { useState, type ReactNode } from "react";

export type PortfolioColumn<T> = {
  id: string; label: string; cell: (row: T) => ReactNode; className?: string;
  required?: boolean; initiallyHidden?: boolean;
};

/** Preferences contain column names only; rows, search terms and identities never enter storage. */
function readHidden<T>(key: string, columns: PortfolioColumn<T>[]): string[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (Array.isArray(stored) && stored.every((item) => typeof item === "string")) {
      return columns.filter((col) => !col.required && stored.includes(col.id)).map((col) => col.id);
    }
  } catch { /* Storage may be disabled; keep the default view. */ }
  return columns.filter((col) => !col.required && col.initiallyHidden).map((col) => col.id);
}

export function PortfolioTable<T>({ view, caption, columns, rows, rowKey, loading, error, forbidden = false, onRetry, filtered, onClear }: {
  view: "members" | "subscriptions" | "charges" | "payments";
  caption: string; columns: PortfolioColumn<T>[]; rows: T[]; rowKey: (row: T, index: number) => string;
  loading: boolean; error?: string | null; forbidden?: boolean; onRetry: () => void;
  filtered: boolean; onClear: () => void;
}) {
  const storageKey = `synkmetrix:list-columns:v1:${view}`;
  const [hidden, setHidden] = useState(() => readHidden(storageKey, columns));
  const [columnsOpen, setColumnsOpen] = useState(false);
  const visible = columns.filter((col) => !hidden.includes(col.id) || col.required);
  const save = (next: string[]) => {
    setHidden(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* In-memory preferences still work. */ }
  };
  return (
    <div className="portfolio-table">
      <div className="portfolio-table-toolbar">
        <p className="muted-copy" role="status">{loading ? "Actualizando resultados…" : error ? "No se pudieron cargar los resultados." : forbidden ? "Acceso restringido." : `${rows.length.toLocaleString("es-CL")} filas en esta página`}</p>
        <details className="portfolio-columns" open={columnsOpen}>
          <summary onClick={(event) => { event.preventDefault(); setColumnsOpen((value) => !value); }}>Columnas <span className="mono">{visible.length}/{columns.length}</span></summary>
          <fieldset hidden={!columnsOpen}>
            <legend>Columnas visibles</legend>
            {columns.map((col) => <label key={col.id}>
              <input type="checkbox" aria-label={`Mostrar columna ${col.label}`} checked={visible.includes(col)} disabled={col.required}
                onChange={() => save(hidden.includes(col.id) ? hidden.filter((id) => id !== col.id) : [...hidden, col.id])} />
              <span className="sr-only">Mostrar columna </span>{col.label}{col.required ? <span className="muted-copy"> (fija)</span> : null}
            </label>)}
            <button type="button" className="text-button" onClick={() => save(columns.filter((col) => !col.required && col.initiallyHidden).map((col) => col.id))}>Restaurar columnas</button>
            <p className="muted-copy">Ocultar columnas solo cambia esta tabla.</p>
          </fieldset>
        </details>
      </div>
      {error ? <div className="portfolio-feedback error-message" role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={onRetry}>Reintentar</button></div>
        : forbidden ? <p className="portfolio-feedback">No tienes permiso para ver estos resultados.</p>
        : <div className="table-wrap portfolio-table-scroll" role="region" aria-label={`Tabla de ${caption}`} tabIndex={0} aria-busy={loading}>
          <table>
            <caption className="sr-only">{caption}. Puedes desplazarte por la tabla con el teclado.</caption>
            <thead><tr>{visible.map((col) => <th key={col.id} scope="col" className={col.className}>{col.label}</th>)}</tr></thead>
            <tbody>
              {loading ? Array.from({ length: 4 }, (_, i) => <tr key={i} aria-hidden="true"><td colSpan={visible.length}><div className="portfolio-skeleton" /></td></tr>)
                : rows.map((row, index) => <tr key={rowKey(row, index)}>{visible.map((col) => <td key={col.id} className={col.className}>{col.cell(row)}</td>)}</tr>)}
              {!loading && rows.length === 0 ? <tr><td colSpan={visible.length}><div className="portfolio-empty">
                <strong>{filtered ? "No hay resultados con estos filtros." : "Todavía no hay registros disponibles."}</strong>
                <p>{filtered ? "Prueba otro término o quita algún filtro para ampliar la búsqueda." : "Los registros aparecerán después de cargar información de los canales autorizados."}</p>
                {filtered ? <button type="button" className="secondary-button" onClick={onClear}>Quitar todos los filtros</button> : null}
              </div></td></tr> : null}
            </tbody>
          </table>
        </div>}
    </div>
  );
}
