import { ApiError, friendlyError } from "../../api";

/** Por encima de este número de filas se avisa antes de confirmar la descarga. */
export const EXPORT_VOLUME_WARNING_ROWS = 200_000;

/** Mensaje claro por código HTTP, sin exponer detalles internos. */
export function exportErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "Tu rol no puede exportar este recurso.";
    if (error.status === 401) return "Tu sesión expiró. Vuelve a iniciar sesión para exportar.";
    if (error.status === 409) return "La exportación no está disponible ahora mismo (conflicto en el servidor). Inténtalo de nuevo en unos minutos.";
    if (error.status === 422) return "Los filtros activos no son válidos para exportar. Ajústalos e inténtalo de nuevo.";
    if (error.status >= 500) return "El servidor falló al preparar la exportación. Inténtalo de nuevo; si persiste, avisa al equipo.";
    return error.message;
  }
  return friendlyError(error, "No se pudo exportar.");
}
