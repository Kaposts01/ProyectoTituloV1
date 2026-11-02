import { tryLabel } from "../../i18n/label";

/** Rótulo del canal de una fila (`virtualpos1` -> «VirtualPOS 1»). */
export function channelText(channel: string | null | undefined): string {
  return tryLabel("channel", channel) ?? (channel || "—");
}

/**
 * Estado tal como lo informa el proveedor: traducido si el catálogo lo conoce (estados generales o de TCH); si no,
 * el texto crudo marcado con `data-raw-text` (excepción documentada del guardián de i18n).
 */
export function StatusText({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined || String(value).trim() === "") return <>—</>;
  const known = tryLabel("status", value) ?? tryLabel("tchStatus", value);
  return known ? <>{known}</> : <span className="mono" data-raw-text>{String(value).trim()}</span>;
}

export function money(amount: string | number | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = Number(amount);
  if (!Number.isFinite(value)) return String(amount);
  return `${currency ?? ""} $${value.toLocaleString("es-CL")}`.trim();
}

export const day = (value: string | null | undefined): string => (value ? String(value).slice(0, 10) : "—");

/** Ruta de la ficha por canal (pantallas transitorias del «Detalle por canal»); null si no existe ficha. */
export function detailPath(entity: "subscription" | "charge" | "payment", channel: string, id: string | null | undefined): string | null {
  if (!id) return null;
  const enc = encodeURIComponent(id);
  if (channel.startsWith("virtualpos")) {
    return { subscription: `/virtualpos/suscripciones/${enc}`, charge: `/virtualpos/cargos/${enc}`, payment: `/virtualpos/transacciones/${enc}` }[entity];
  }
  if (channel === "toku") return { subscription: `/toku/suscripciones/${enc}`, charge: `/toku/deudas/${enc}`, payment: `/toku/transacciones/${enc}` }[entity];
  if (channel === "payku") return entity === "subscription" ? `/payku/suscripciones/${enc}` : entity === "payment" ? `/payku/transacciones/${enc}` : null;
  if (channel === "tch") return entity === "subscription" && /^\d+$/.test(id) ? `/tch/suscripciones/${id}` : null;
  return null;
}
