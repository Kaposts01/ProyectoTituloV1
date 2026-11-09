/**
 * Formato único del RUT en la interfaz (QA-08): `12.345.678-9`, con puntos de miles en es-CL y guion antes del
 * dígito verificador, venga como venga del canal (`123456789`, `12345678-9`, `12.345.678-9`). Lo que no tiene
 * forma de RUT se muestra tal cual y marcado como no válido; un RUT bien formado con dígito verificador
 * incorrecto se formatea igual, pero también queda marcado.
 */
export interface FormattedRut {
  text: string;
  valid: boolean;
}

function checkDigit(body: string): string {
  const total = [...body].reverse().reduce((sum, digit, index) => sum + Number(digit) * (2 + (index % 6)), 0);
  const remainder = 11 - (total % 11);
  return remainder === 11 ? "0" : remainder === 10 ? "K" : String(remainder);
}

export function formatRut(value: unknown): FormattedRut | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (raw === "" || raw === "—") return null;
  const compact = raw.toUpperCase().replace(/[.\-\s]/g, "");
  if (!/^\d{1,9}[0-9K]$/.test(compact)) return { text: raw, valid: false };
  const body = compact.slice(0, -1).replace(/^0+/, "") || "0";
  const dv = compact.slice(-1);
  return { text: `${Number(body).toLocaleString("es-CL")}-${dv}`, valid: checkDigit(body) === dv };
}

/** Solo el texto formateado; `fallback` si no hay RUT. Para celdas, etiquetas y textos que no llevan la marca. */
export function rutText(value: unknown, fallback = "—"): string {
  return formatRut(value)?.text ?? fallback;
}
