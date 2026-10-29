import { label } from "../../i18n/label";
import type { Domain } from "../../i18n/es";
import { text } from "./utils";

/** Campos cuyo valor es un estado del proveedor y se traduce con el catálogo. */
const STATUS_FIELDS = new Set(["status", "charge_status", "payment_status"]);

/** Dominio del catálogo que traduce el valor de un campo, o undefined si el valor es libre (nombres, ids, fechas, montos). */
function domainOf(field: string): Domain | undefined {
  if (STATUS_FIELDS.has(field)) return "status";
  if (field === "secondary_status") return "secondaryStatus";
  return undefined;
}

/**
 * Valor de un campo de un registro del proveedor para mostrarlo en una ficha: los campos con catálogo
 * (estados) se traducen; el resto se muestra como `text()`. Ausente da «Sin dato».
 */
export function fieldValue(field: string, value: unknown): string {
  const domain = domainOf(field);
  if (domain === undefined || value === null || value === undefined || value === "" || typeof value === "object") return text(value);
  return label(domain, value);
}
