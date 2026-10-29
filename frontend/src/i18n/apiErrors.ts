import { tryLabel } from "./label";

/**
 * Traducción de los mensajes de error de la API (campo `detail` y errores de validación de FastAPI/pydantic).
 * Los textos exactos viven en `es.apiDetail`; aquí están los que llevan datos variables y la validación.
 */

/** Detalles con datos variables (el backend los arma con f-strings). */
const PATTERNS: Array<[RegExp, (m: RegExpExecArray) => string]> = [
  [/^(\w+) must use YYYY-MM-DD$/, (m) => `El parámetro ${m[1]} debe tener el formato AAAA-MM-DD.`],
  [/^Unknown channel: ([^.\s]+)\./, (m) => `Canal desconocido: ${m[1]}.`],
  [/^Unknown webhook kind: (.+)$/, (m) => `Tipo de webhook desconocido: ${m[1]}.`],
  [/^Expected boolean-like value for field '([^']+)'$/, (m) => `El campo ${m[1]} debe ser verdadero o falso.`],
];

/** Traducción de un `detail` en inglés conocido, o `null` si no se conoce (se mostrará tal cual). */
export function translateApiDetail(detail: string): string | null {
  const exact = tryLabel("apiDetail", detail);
  if (exact !== undefined) return exact;
  for (const [pattern, build] of PATTERNS) {
    const match = pattern.exec(detail.trim());
    if (match) return build(match);
  }
  return null;
}

const VALIDATION_BY_TYPE: Record<string, string> = {
  missing: "es obligatorio",
  string_too_short: "es demasiado corto",
  string_too_long: "es demasiado largo",
  string_type: "debe ser texto",
  int_parsing: "debe ser un número entero",
  int_type: "debe ser un número entero",
  int_from_float: "debe ser un número entero",
  float_parsing: "debe ser un número",
  float_type: "debe ser un número",
  decimal_parsing: "debe ser un número",
  bool_parsing: "debe ser verdadero o falso",
  bool_type: "debe ser verdadero o falso",
  greater_than: "es menor que el mínimo permitido",
  greater_than_equal: "es menor que el mínimo permitido",
  less_than: "es mayor que el máximo permitido",
  less_than_equal: "es mayor que el máximo permitido",
  literal_error: "no es un valor permitido",
  enum: "no es un valor permitido",
  json_invalid: "no es un JSON válido",
  extra_forbidden: "no está permitido",
  date_parsing: "debe ser una fecha válida",
  date_type: "debe ser una fecha válida",
  datetime_parsing: "debe ser una fecha y hora válidas",
  url_parsing: "debe ser una URL válida",
  too_short: "tiene muy pocos elementos",
  too_long: "tiene demasiados elementos",
};

/** Mensaje de un error de validación de pydantic: campo en español y motivo traducido por su `type`. */
export function validationMessage(item: Record<string, unknown>): string {
  const loc = Array.isArray(item.loc)
    ? (item.loc as unknown[]).map(String).filter((part) => part !== "body").map((part) => tryLabel("field", part) ?? part).join(" → ")
    : "";
  const type = typeof item.type === "string" ? item.type : "";
  const msg = typeof item.msg === "string" ? item.msg : "";
  // `value_error` lleva el mensaje del validador propio del backend («Value error, <texto>»): se conserva sin el prefijo.
  const reason = type === "value_error" && msg ? msg.replace(/^Value error,\s*/i, "") : (VALIDATION_BY_TYPE[type] ?? "valor no válido");
  return loc ? `${loc}: ${reason}` : reason;
}
