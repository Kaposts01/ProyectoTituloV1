/**
 * Mapa ÚNICO estado -> color semántico. Barras de estado, gráficos apilados y leyendas deben
 * colorear un estado solo a través de `statusColor`, de modo que «pagado» sea el mismo verde en
 * todas partes. Los colores son tokens CSS (index.css, claro y oscuro), no hex fijos.
 *
 *   paid        éxito (verde)        pagado, aceptado, cobrado, activo, vigente
 *   rejected    error (rojo)         rechazado, fallido
 *   pending     advertencia (ámbar)  pendiente, registrado, reintento
 *   processing  neutro azulado       procesando, suscribiendo
 *   neutral     gris                 cancelado, expirado, anulado, eliminado, pausado, inactivo
 *   unknown     gris claro           cualquier otro / sin estado
 *
 * Los colores de CANAL (VirtualPOS, Toku…) son otra cosa y viven en chartColors.ts.
 */
export const STATUS_KINDS = ["paid", "rejected", "pending", "processing", "neutral", "unknown"] as const;
export type StatusKind = (typeof STATUS_KINDS)[number];

const KEYWORDS: [StatusKind, string[]][] = [
  // El orden importa: «inactiva» contiene «activ», «unpaid» contiene «paid», «incobrable» contiene «cobrable».
  ["rejected", ["rechaz", "reject", "fail", "fallid", "declin", "denied", "error"]],
  ["neutral", ["cancel", "expir", "anul", "void", "delet", "elimin", "abort", "paus", "suspend", "inactiv", "incobrab", "closed", "cerrad"]],
  ["pending", ["pend", "regist", "initial", "reintent", "retry", "unpaid", "impag", "waiting"]],
  ["processing", ["process", "procesand", "suscribiend", "in progress", "cambio de tarjeta"]],
  ["paid", ["pagad", "paid", "success", "exito", "acept", "accept", "cobrad", "aprobad", "approv", "activ", "vigent", "chargeable", "complet"]],
];

/** Normaliza mayúsculas, tildes, guiones/guiones bajos e idioma (es/en) a un tipo de estado. */
export function normalizeStatus(status: unknown): StatusKind {
  if (typeof status !== "string") return "unknown";
  const s = status
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!s) return "unknown";
  for (const [kind, words] of KEYWORDS) if (words.some((w) => s.includes(w))) return kind;
  return "unknown";
}

/** Token CSS del tipo de estado (cambia solo con el tema claro/oscuro). */
export const statusKindColor = (kind: StatusKind): string => `var(--status-${kind})`;

/** Color (token CSS) de un estado cualquiera. */
export const statusColor = (status: unknown): string => statusKindColor(normalizeStatus(status));
