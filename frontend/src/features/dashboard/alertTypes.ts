/**
 * Tipos INTERNOS de las alertas operativas, en inglés. Las claves en español del backend (`sev`, `tipo`, `canal`,
 * `detalle`, `periodo`, `ultimo_cobro`…) solo existen en `alertAdapter.ts` (D33). Los VALORES de severidad
 * («alta», «media», «baja») son códigos del backend y se traducen con `label("severity")`.
 */
export type AlertSeverity = "alta" | "media" | "baja";

export type Alert = {
  id?: string;
  severity: AlertSeverity;
  kind: string;
  channel: string;
  detail: string;
  /** Mes de la alerta (`AAAA-MM`), si el backend lo entrega. */
  period?: string;
};

export type AlertDetailItem = {
  externalId: string | null;
  rut: string | null;
  status: string | null;
  amount: number;
  subscriptionDate: string | null;
  /** `undefined` = el backend no entrega la columna (la tabla no la muestra); `null` = columna sin dato. */
  lastCharge?: string | null;
  lastChargeStatus?: string | null;
  attempts?: number;
};
