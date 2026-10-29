/**
 * ADAPTADOR del recuperador (D33): único módulo que conoce las claves en español `monto` y `monto_vigente` de las
 * filas del recuperador. El resto del frontend usa `requestedAmount` y `currentAmount`.
 * Devuelve el valor tal cual llegó (`undefined` si la fila no trae la clave): la pantalla decide cómo mostrarlo.
 */
import type { RecoveryRow } from "../shared/types";
import { recoveryValue } from "../shared/utils";

/** Monto de la solicitud o del cobro (clave `monto`). */
export const requestedAmount = (item: RecoveryRow): unknown => recoveryValue(item, "monto");

/** Monto vigente, el último cobrado (clave `monto_vigente`). */
export const currentAmount = (item: RecoveryRow): unknown => recoveryValue(item, "monto_vigente");
