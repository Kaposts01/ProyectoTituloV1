/**
 * ADAPTADOR de alertas (D33): único módulo que conoce las claves en español de las alertas del backend
 * (`sev`, `tipo`, `canal`, `detalle`, `periodo`) y de su detalle (`ultimo_cobro`, `ultimo_estado`, `intentos`,
 * y `suscription_date`, mal escrito en el contrato del proveedor). Convierte a los tipos de `alertTypes.ts`.
 */
import { normalizeSeverity } from "./alertGroups";
import type { Alert, AlertDetailItem } from "./alertTypes";

export type AlertWire = { id?: string; sev?: string | null; tipo?: string | null; canal?: string | null; detalle?: string | null; periodo?: string | null };
export type AlertDetailItemWire = {
  external_id?: string | null;
  rut?: string | null;
  status?: string | null;
  amount?: number | null;
  suscription_date?: string | null;
  ultimo_cobro?: string | null;
  ultimo_estado?: string | null;
  intentos?: number;
};

export function adaptAlert(wire: AlertWire): Alert {
  const alert: Alert = {
    severity: normalizeSeverity(wire.sev),
    kind: String(wire.tipo ?? ""),
    channel: String(wire.canal ?? ""),
    detail: String(wire.detalle ?? ""),
  };
  if (wire.id) alert.id = wire.id;
  if (wire.periodo) alert.period = wire.periodo;
  return alert;
}

export const adaptAlerts = (wire: AlertWire[] | null | undefined): Alert[] => (Array.isArray(wire) ? wire.map(adaptAlert) : []);

export function adaptAlertDetailItem(wire: AlertDetailItemWire): AlertDetailItem {
  const item: AlertDetailItem = {
    externalId: wire.external_id ?? null,
    rut: wire.rut ?? null,
    status: wire.status ?? null,
    amount: wire.amount ?? 0,
    subscriptionDate: wire.suscription_date ?? null,
  };
  // Las columnas opcionales conservan «ausente» (undefined): la tabla solo las muestra si el backend las entrega.
  if (wire.ultimo_cobro !== undefined) item.lastCharge = wire.ultimo_cobro;
  if (wire.ultimo_estado !== undefined) item.lastChargeStatus = wire.ultimo_estado;
  if (wire.intentos !== undefined) item.attempts = wire.intentos;
  return item;
}

export const adaptAlertDetailItems = (wire: AlertDetailItemWire[] | null | undefined): AlertDetailItem[] =>
  Array.isArray(wire) ? wire.map(adaptAlertDetailItem) : [];
