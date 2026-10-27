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

/** Channel registry. Toku, Payku and TCH are added here when /general/recuperador exists. */
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

/** Cuentas del filtro 'Cuenta' limitadas a las habilitadas en el ambiente (los values son nombres de canal). */
export function enabledAccounts(
  accounts: RecoveryChannelConfig["accounts"],
  enabledChannels: string[],
): RecoveryChannelConfig["accounts"] {
  return accounts.filter((account) => enabledChannels.includes(account.value));
}
