/** HTTP utilities compartidas por todos los módulos del frontend. */

export let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

function extractErrorDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail = (data as Record<string, unknown>).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item !== "object" || item === null) return String(item);
        const err = item as Record<string, unknown>;
        const loc = Array.isArray(err.loc)
          ? (err.loc as string[]).filter((l) => l !== "body").join(" → ")
          : "";
        const msg = typeof err.msg === "string" ? err.msg : "";
        return loc ? `${loc}: ${msg}` : msg;
      })
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
  if (status === 422) return "Los datos enviados no son válidos. Revisa los campos e inténtalo de nuevo.";
  if (status === 500) return "Error interno del servidor. Inténtalo de nuevo en unos momentos.";
  if (status === 503) return "El servicio no está disponible temporalmente. Inténtalo más tarde.";
  return `Error inesperado del servidor (${status}).`;
}

export function friendlyError(error: unknown, fallback = "Ocurrió un error inesperado."): string {
  if (error instanceof TypeError && error.message.toLowerCase().includes("fetch")) {
    return "No se pudo conectar con el servidor. Verifica tu conexión.";
  }
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

/** Error HTTP con el estado y el `detail` crudo (p. ej. {code, message, ...}) para quien necesite decidir por código. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function checkResponse(response: Response): Promise<void> {
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
