import { refreshCsrfToken } from "./utils";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 403 sin `code` estructurado: lo emite el middleware (CSRF), no el servicio (que siempre envía `code`). */
function isUnstructured403(error: unknown): boolean {
  if (!isRecord(error) || error.status !== 403) return false;
  const detail = error.detail;
  return !(isRecord(detail) && typeof detail.code === "string");
}

function looksLikeCsrf(error: unknown): boolean {
  return isRecord(error) && typeof error.detail === "string" && /csrf/i.test(error.detail);
}

/**
 * Ejecuta una mutación. Si otra pestaña refrescó la sesión, el token CSRF local queda obsoleto y el servidor responde
 * 403 sin `code`: se refresca el token y se reintenta UNA vez (el rechazo ocurre antes del handler, sin efectos).
 * Los errores con código estructurado (`not_approver`, `writes_disabled`…) nunca se reintentan.
 */
export async function withCsrfRetry<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (first) {
    if (!isUnstructured403(first)) throw first;
    await refreshCsrfToken();
    try {
      return await call();
    } catch (second) {
      if (isUnstructured403(second) && looksLikeCsrf(second)) {
        throw Object.assign(new Error("stale_session"), { status: 403, detail: { code: "stale_session" } });
      }
      throw second;
    }
  }
}
