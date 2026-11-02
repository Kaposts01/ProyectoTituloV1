export type RecoveryChannelId = "virtualpos";

export type RecoveryChannelConfig = {
  id: RecoveryChannelId;
  label: string;
  title: string;
  viewPermission: string;
  exportPermission: string;
  retryPermission: string;
  cardChangePermission: string;
  accounts: { value: string; label: string }[];
};

/** Configuración del recuperador de VirtualPOS (la pestaña con acciones: reintentos, enlaces y CSV). */
export const RECOVERY_CHANNELS: Record<RecoveryChannelId, RecoveryChannelConfig> = {
  virtualpos: {
    id: "virtualpos",
    label: "VirtualPOS",
    title: "Recuperador de Socios",
    viewPermission: "virtualpos.recovery.view",
    exportPermission: "virtualpos.recovery.export",
    retryPermission: "virtualpos.charges.retry",
    cardChangePermission: "virtualpos.cards.change",
    accounts: [{ value: "virtualpos1", label: "virtualpos1" }, { value: "virtualpos2", label: "virtualpos2" }],
  },
};

/* ── Recuperador general (/general/recuperador, UX-12) ───────────────────────────────
   Una pestaña por canal; cada una tiene su permiso y su API lo exige. Payku (REC-05) aún no existe. */

export const PERM_GENERAL_RECOVERY = "general.recovery.view";
export const PERM_RECOVERY_TOKU = "general.recovery.toku.view";
export const PERM_RECOVERY_TCH = "general.recovery.tch.view";

export type RecoveryTabId = "virtualpos" | "toku" | "tch";

export const RECOVERY_TABS: { id: RecoveryTabId; label: string; permission: string }[] = [
  { id: "virtualpos", label: "VirtualPOS", permission: RECOVERY_CHANNELS.virtualpos.viewPermission },
  { id: "toku", label: "Toku", permission: PERM_RECOVERY_TOKU },
  { id: "tch", label: "TCH", permission: PERM_RECOVERY_TCH },
];

/** Pestañas de canal que el usuario puede ver. */
export function visibleRecoveryTabs(can: (permission: string) => boolean): typeof RECOVERY_TABS {
  return RECOVERY_TABS.filter((tab) => can(tab.permission));
}

/**
 * Acceso a /general/recuperador (menú y ruta): el permiso general o el de alguna pestaña. El permiso de pestaña
 * basta para no dejar sin recuperador a quien ya lo usaba mientras la migración 0052 no esté aplicada.
 */
export function canOpenRecovery(can: (permission: string) => boolean): boolean {
  return can(PERM_GENERAL_RECOVERY) || visibleRecoveryTabs(can).length > 0;
}

/** Cuentas del filtro 'Cuenta' limitadas a las habilitadas en el ambiente (los values son nombres de canal). */
export function enabledAccounts(
  accounts: RecoveryChannelConfig["accounts"],
  enabledChannels: string[],
): RecoveryChannelConfig["accounts"] {
  return accounts.filter((account) => enabledChannels.includes(account.value));
}
