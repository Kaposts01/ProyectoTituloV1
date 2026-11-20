/** Esqueleto de página con alto reservado: evita que la vista salte (CLS) al llegar los datos. */
export function PageSkeleton({ label, variant = "table" }: { label: string; variant?: "table" | "cards" }) {
  return (
    <main className="app-shell page-skeleton" aria-busy="true" data-testid="page-skeleton">
      <p role="status" className="sr-only">{label}</p>
      <div className="summary-skeleton page-skeleton-title" aria-hidden="true" />
      {variant === "cards" ? (
        <div className="page-skeleton-cards" aria-hidden="true">
          {Array.from({ length: 4 }, (_, index) => <div key={index} className="summary-skeleton" />)}
        </div>
      ) : (
        <div className="summary-skeleton page-skeleton-filters" aria-hidden="true" />
      )}
      <div className="summary-skeleton page-skeleton-body" aria-hidden="true" />
    </main>
  );
}
