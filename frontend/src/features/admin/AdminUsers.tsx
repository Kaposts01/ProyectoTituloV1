import { useEffect, useState } from "react";
import { getJson } from "../../api";
import type { AdminRole } from "../shared/types";
import { UsersSubPanel } from "./UsersSubPanel";
import { RolesSubPanel } from "./RolesSubPanel";

export function AdminUsers({ permissions }: { permissions: string[] }) {
  const canManageUsers = permissions.includes("users.manage");
  const canManageRoles = permissions.includes("roles.manage");
  const [subTab, setSubTab] = useState<"users" | "roles">("users");
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [allPermissions, setAllPermissions] = useState<Array<{ code: string; description: string }>>([]);

  useEffect(() => {
    getJson<AdminRole[]>("/api/v1/admin/roles")
      .then(setRoles)
      .catch((e: unknown) => console.error("Error loading roles:", e));
    if (canManageRoles) {
      getJson<Array<{ code: string; description: string }>>("/api/v1/admin/permissions")
        .then(setAllPermissions)
        .catch((e: unknown) => console.error("Error loading permissions:", e));
    }
  }, [canManageRoles]);

  return (
    <section className="panel">
      <p className="eyebrow">ADMINISTRACIÓN</p>
      <h1>{subTab === "users" ? "Usuarios" : "Roles y permisos"}</h1>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        <button className={`channel-btn${subTab === "users" ? " active" : ""}`} onClick={() => setSubTab("users")}>Usuarios</button>
        {canManageRoles ? (
          <button className={`channel-btn${subTab === "roles" ? " active" : ""}`} onClick={() => setSubTab("roles")}>Roles</button>
        ) : null}
      </div>
      {subTab === "users"
        ? <UsersSubPanel canManage={canManageUsers} roles={roles} />
        : <RolesSubPanel canManage={canManageRoles} allPermissions={allPermissions} />}
    </section>
  );
}
