/** HTTP utilities compartidas por todos los módulos del frontend. */
import { translateApiDetail, validationMessage } from "./i18n/apiErrors";
import { noteServerDate } from "./serverClock";

export let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

/**
 * Mensaje de un error de la API para el usuario. El `detail` en inglés que el backend ya conoce se traduce
 * (i18n/apiErrors.ts); el que no está en el catálogo se muestra tal cual (casi siempre es español redactado por el
 * backend). Un `detail` estructurado {code, message} no se muestra: se usa el texto genérico del estado HTTP.
 */
function extractErrorDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail = (data as Record<string, unknown>).detail;
  if (typeof detail === "string") return translateApiDetail(detail) ?? detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => (typeof item === "object" && item !== null ? validationMessage(item as Record<string, unknown>) : String(item)))
      .filter(Boolean)
      .join("; ");
  }
  return null;
}

function httpErrorMessage(status: number, detail: string | null): string {
  if (detail) return detail;
  if (status === 400) return "Solicitud inválida. Verifica los datos ingresados.";
  if (status === 401) return "Sesión expirada. Vuelve a iniciar sesión.";
  if (status === 403) return "No tienes permiso para realizar esta acción.";
  if (status === 404) return "El recurso solicitado no fue encontrado.";
  if (status === 409) return "La operación entra en conflicto con el estado actual. Actualiza e inténtalo de nuevo.";
  if (status === 422) return "Los datos enviados no son válidos. Revisa los campos e inténtalo de nuevo.";
  if (status === 500) return "Error interno del servidor. Inténtalo de nuevo en unos momentos.";
  if (status === 502) return "El servicio externo no respondió correctamente. Inténtalo más tarde.";
  if (status === 503) return "El servicio no está disponible temporalmente. Inténtalo más tarde.";
  return `Error inesperado del servidor (${status}).`;
}

export function friendlyError(error: unknown, fallback = "Ocurrió un error inesperado."): string {
  if (error instanceof TypeError && error.message.toLowerCase().includes("fetch")) {
    return "No se pudo conectar con el servidor. Verifica tu conexión.";
  }
  if (error instanceof SyntaxError) return "La respuesta del servidor no tiene el formato esperado.";
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

/** Error HTTP con el estado y el `detail` crudo (p. ej. {code, message, ...}) para quien necesite decidir por código. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  /** `detail.code` cuando el backend envía un detalle estructurado {code, message}; si no, null. */
  code: string | null;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    const code = detail && typeof detail === "object" ? (detail as Record<string, unknown>).code : undefined;
    this.code = typeof code === "string" ? code : null;
  }
}

/** ¿El error trae exactamente este `detail` crudo del backend? (el mensaje mostrado ya está traducido, no sirve para comparar). */
export function apiDetailIs(error: unknown, detail: string): boolean {
  return error instanceof ApiError && error.detail === detail;
}

async function checkResponse(response: Response): Promise<void> {
  noteServerDate(response.headers?.get?.("date"));
  if (response.ok) return;
  const data = await response.json().catch(() => null);
  const detail = extractErrorDetail(data);
  const rawDetail = data && typeof data === "object" ? (data as Record<string, unknown>).detail : undefined;
  throw new ApiError(httpErrorMessage(response.status, detail), response.status, rawDetail);
}

async function jsonResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      "La API activa no incluye esta ruta de recuperación. Reinicia el servidor backend y vuelve a intentarlo.",
    );
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { credentials: "include", signal });
  await checkResponse(response);
  return jsonResponse<T>(response);
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  await checkResponse(response);
  return jsonResponse<T>(response);
}

export async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    body,
  });
  await checkResponse(response);
  return jsonResponse<T>(response);
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { credentials: "include" });
  await checkResponse(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Nombre de archivo del header `Content-Disposition` (filename*= o filename=), o null si no viene. */
export function filenameFromDisposition(header: string | null | undefined): string | null {
  if (!header) return null;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, "")) || null;
    } catch {
      /* cae al filename simple */
    }
  }
  const plain = /filename\s*=\s*("([^"]*)"|[^;]+)/i.exec(header);
  const value = plain ? (plain[2] ?? plain[1]).trim() : "";
  return value || null;
}

/** GET de un archivo con las credenciales de sesión; devuelve el blob y el nombre del `Content-Disposition`. */
export async function getBlob(path: string, signal?: AbortSignal): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetch(path, { credentials: "include", signal });
  await checkResponse(response);
  const blob = await response.blob();
  return { blob, filename: filenameFromDisposition(response.headers?.get?.("content-disposition")) };
}

/** Guarda un blob en disco con el nombre dado (enlace temporal; no navega la página). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
    body: JSON.stringify(body),
  });
  await checkResponse(response);
  return jsonResponse<T>(response);
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
    body: JSON.stringify(body),
  });
  await checkResponse(response);
  return jsonResponse<T>(response);
}

export async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    credentials: "include",
    headers: { ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
  });
  await checkResponse(response);
  return response.json() as Promise<T>;
}
