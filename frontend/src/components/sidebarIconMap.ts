import type { IconName } from "./sidebarIcons";

/** Ícono de cada entrada del menú, por `id` de `menuGroups` (navigation.ts). Un test exige que ninguna quede sin ícono. */
export const MENU_ICONS: Record<string, IconName> = {
  summary: "summary",
  clients: "members",
  subscriptions: "subscriptions",
  charges: "charges",
  recovery: "recovery",
  billing: "billing",
  cancellations: "cancellations",
  sync: "sync",
  admin: "admin",
  report: "report",
};
