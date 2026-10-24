import { AdminUsers } from "./AdminUsers";
import { SchedulerPanel } from "./SchedulerPanel";

export function AdminPanel({ permissions, isAdmin, tab }: { permissions: string[]; isAdmin: boolean; tab: "usuarios" | "sincronizacion" }) {
  return (
    <main className="app-shell">
      {tab === "usuarios"
        ? <AdminUsers permissions={permissions} />
        : <SchedulerPanel canSync={permissions.includes("sync.run")} canViewRuns={permissions.includes("sync_runs.view")} canImportTch={isAdmin} />}
    </main>
  );
}
