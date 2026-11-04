import { createContext, useContext } from "react";

/**
 * Quién puede dar de baja una suscripción con los botones directos (VirtualPOS «Cancelar», Toku/Payku «Eliminar»,
 * Toku «Cancelada»): el backend exige el rol admin. El resto pide la baja en «Bajas» (/api/v1/cancellations).
 * El valor por defecto es el seguro: sin proveedor no se muestran los botones directos.
 */
export type DirectCancelAccess = {
  /** Rol admin: puede usar los botones directos. */
  isAdmin: boolean;
  /** Puede abrir la pantalla «Bajas» (permiso de lectura de bajas). */
  canOpenCancellations: boolean;
};

export const DirectCancelContext = createContext<DirectCancelAccess>({ isAdmin: false, canOpenCancellations: false });

export const useDirectCancel = (): DirectCancelAccess => useContext(DirectCancelContext);
