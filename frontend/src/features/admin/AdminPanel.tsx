import { AdminUsers } from "./AdminUsers";
import { SchedulerPanel } from "./SchedulerPanel";
import { EnvironmentSection } from "./EnvironmentSection";

export function AdminPanel({ permissions, isAdmin, tab }: { permissions: string[]; isAdmin: boolean; tab: "users" | "sync" }) {
  return (
    <main className="app-shell">
      {tab === "users"
        ? <AdminUsers permissions={permissions} />
        : <SchedulerPanel canSync={permissions.includes("sync.run")} canViewRuns={permissions.includes("sync_runs.view")} canImportTch={isAdmin} />}
      <EnvironmentSection permissions={permissions} />
    </main>
  );
}
