import { useDirectCancel } from "./directCancel";
import { routePath } from "../../routes";

/** Lleva a «Bajas» sin recargar la página (AppCore escucha `popstate`); con Ctrl o Cmd deja el comportamiento normal del enlace. */
function goToCancellations(event: React.MouseEvent<HTMLAnchorElement>) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  window.history.pushState({}, "", routePath({ kind: "cancellations" }));
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/**
 * Texto que reemplaza a un botón directo de baja cuando el usuario no es admin: explica que la baja se pide con
 * «Solicitar baja» y, si puede abrir la pantalla, enlaza a ella.
 */
export function DirectCancelNote({ compact = false }: { compact?: boolean }) {
  const { canOpenCancellations } = useDirectCancel();
  return (
    <span className="direct-cancel-note" data-testid="direct-cancel-note">
      {compact ? "Baja: " : "La baja directa es solo para administradores. "}
      {canOpenCancellations
        ? <>use «Solicitar baja» en <a href={routePath({ kind: "cancellations" })} onClick={goToCancellations}>Bajas</a>.</>
        : <>pida a una jefatura que use «Solicitar baja» en Bajas.</>}
    </span>
  );
}
