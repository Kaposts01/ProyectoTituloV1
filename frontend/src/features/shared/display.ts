import { label } from "../../i18n/label";
import type { Domain } from "../../i18n/es";
import { text } from "./utils";

/** Campos cuyo valor es un estado del proveedor. */
const STATUS_FIELDS = new Set(["status", "charge_status", "payment_status"]);
/** Campos booleanos; pueden llegar como true/false de JSON o como texto («true», «T», «0»). */
const BOOLEAN_FIELDS = new Set(["is_active", "automatic_renewal", "show_in_terminal", "is_paid", "renewal", "three_d_secure"]);

/** Dominio del catálogo que traduce el valor de un campo, o undefined si el valor es libre (nombres, ids, fechas, montos). */
function domainOf(field: string): Domain | undefined {
  if (STATUS_FIELDS.has(field)) return "status";
  if (field === "secondary_status") return "secondaryStatus";
  if (BOOLEAN_FIELDS.has(field)) return "boolean";
  if (field === "frequency_type") return "frequency";
  if (field === "currency") return "currency";
  if (field === "card_type") return "cardType";
  if (field === "card_brand") return "cardBrand";
  if (field === "payment_type_code") return "paymentType";
  if (field === "gateway") return "gateway";
  return undefined;
}

/**
 * Valor de un campo de un registro del proveedor para mostrarlo en una ficha:
 *  - un booleano de JSON se ve «Sí» / «No»;
 *  - los campos con catálogo (estados, booleanos, frecuencia, moneda, tarjeta…) se traducen y un valor
 *    desconocido se ve «Desconocido (valor)»;
 *  - el resto (nombres, ids, fechas, montos) se muestra como `text()`. Ausente da «Sin dato».
 */
export function fieldValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return text(value);
  if (typeof value === "boolean") return label("boolean", value);
  if (typeof value === "object") return text(value);
  const domain = domainOf(field);
  return domain === undefined ? text(value) : label(domain, value);
}
