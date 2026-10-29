import { tryLabel } from "../../i18n/label";

export type CancellationErrorInfo = {
  status: number | null;
  code: string | null;
  /** Mensaje en español apto para mostrar: sale del catálogo por código, nunca del servidor ni del proveedor. */
  message: string;
  /** Id de la solicitud abierta que choca con la nueva (código `open_request_exists`); solo si es un UUID. */
  openRequestId?: string;
  /** Paso fallido (`apply_failed`, `reconciliation_required`): solo se conserva si es un código conocido del catálogo. */
  step?: string;
  stepCode?: string;
};

const STATUS_MESSAGES: Record<number, string> = {
  401: "Su sesión expiró. Vuelva a iniciar sesión.",
  403: "No tiene permiso para realizar esta acción.",
  404: "No se encontró el recurso solicitado.",
  409: "La operación entra en conflicto con el estado actual. Actualice y reintente.",
  422: "Los datos enviados no son válidos. Revise los campos.",
  502: "El proveedor no respondió correctamente y no se escribió nada. Reintente más tarde.",
  503: "El servicio no está disponible temporalmente. Reintente más tarde.",
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SAFE_CODE_RE = /^[A-Za-z0-9_]{1,60}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Interpreta un error de `/api/v1/cancellations`. No depende de la clase ApiError (duck typing sobre `status` y
 * `detail`). El texto mostrado sale del catálogo `cancellationError` por `detail.code`; el `message` del servidor
 * y cualquier eco de valores del proveedor se descartan.
 */
export function describeCancellationError(error: unknown, fallback: string): CancellationErrorInfo {
  const status = isRecord(error) && typeof error.status === "number" ? error.status : null;
  const detail = isRecord(error) ? error.detail : undefined;
  if (status === null) {
    const text = error instanceof Error && error.message.toLowerCase().includes("fetch")
      ? "No se pudo conectar con el servidor. Verifique su conexión."
      : fallback;
    return { status: null, code: null, message: text };
  }
  const code = isRecord(detail) && typeof detail.code === "string" ? detail.code : null;
  const info: CancellationErrorInfo = {
    status,
    code,
    message: (code && tryLabel("cancellationError", code)) || STATUS_MESSAGES[status] || fallback,
  };
  if (isRecord(detail)) {
    if (code === "open_request_exists" && typeof detail.open_request_id === "string" && UUID_RE.test(detail.open_request_id)) {
      info.openRequestId = detail.open_request_id;
    }
    if (typeof detail.step === "string" && SAFE_CODE_RE.test(detail.step) && tryLabel("cancellationStep", detail.step)) {
      info.step = detail.step;
    }
    if (typeof detail.step_code === "string" && SAFE_CODE_RE.test(detail.step_code) && tryLabel("cancellationError", detail.step_code)) {
      info.stepCode = detail.step_code;
    }
  }
  return info;
}
