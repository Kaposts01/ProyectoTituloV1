import type { ReactNode } from "react";

/**
 * Esqueleto de página con alto reservado: evita que la vista salte (CLS) al llegar los datos.
 * Con `header` (PERF-03, d264 A) se muestra esa cabecera real en lugar de la barra de título, y la página usa el
 * mismo contenedor que la vista final, para que al llegar los datos la cabecera no se mueva.
 */
export function PageSkeleton({ label, variant = "table", header }: { label: string; variant?: "table" | "cards"; header?: ReactNode }) {
  return (
    <main className={header ? "app-shell channel-dashboard-page" : "app-shell page-skeleton"} data-testid="page-skeleton">
      {/* El aviso queda fuera de la zona ocupada: un lector de pantalla puede suprimir lo que está dentro de un aria-busy (H5). */}
      <p role="status" className="sr-only">{label}</p>
      {header}
      <div className={header ? "page-skeleton-blocks page-skeleton-after-header" : "page-skeleton-blocks"} aria-busy="true" data-testid="page-skeleton-blocks">
        {header ? null : <div className="summary-skeleton page-skeleton-title" aria-hidden="true" />}
        {variant === "cards" ? (
          <div className="page-skeleton-cards" aria-hidden="true">
            {Array.from({ length: 4 }, (_, index) => <div key={index} className="summary-skeleton" />)}
          </div>
        ) : (
          <div className="summary-skeleton page-skeleton-filters" aria-hidden="true" />
        )}
        <div className="summary-skeleton page-skeleton-body" aria-hidden="true" />
      </div>
    </main>
  );
}
