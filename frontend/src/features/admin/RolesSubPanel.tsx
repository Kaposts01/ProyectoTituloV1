import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { getJson, postJson, putJson, deleteJson } from "../../api";
import { groupPermissions, refreshCsrfToken } from "../shared/utils";
import type { AdminRole } from "../shared/types";
import { PermCheckboxes } from "./PermCheckboxes";

export function RolesSubPanel({ canManage, allPermissions }: { canManage: boolean; allPermissions: Array<{ code: string; description: string }> }) {
  const groups = useMemo(() => groupPermissions(allPermissions), [allPermissions]);
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<AdminRole | null>(null);
  const [creating, setCreating] = useState(false);

  function reload() {
    getJson<AdminRole[]>("/api/v1/admin/roles")
      .then((r) => { setRoles(r); setLoading(false); })
      .catch(() => { setMessage("No se pudieron cargar los roles."); setLoading(false); });
  }
  useEffect(() => { reload(); }, []);

  async function createRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await postJson("/api/v1/admin/roles", {
        name: form.get("name"),
        description: (form.get("description") as string).trim() || null,
        permission_codes: form.getAll("permission_codes"),
      });
      event.currentTarget.reset();
      setCreating(false);
      setMessage("Rol creado.");
      reload();
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo crear el rol."); }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editTarget) return;
    const form = new FormData(event.currentTarget);
    try {
      await putJson(`/api/v1/admin/roles/${editTarget.id}`, {
        name: form.get("name"),
        description: (form.get("description") as string).trim() || null,
        permission_codes: form.getAll("permission_codes"),
      });
      setEditTarget(null);
      setMessage("Rol actualizado.");
      reload();
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo actualizar el rol."); }
  }

  async function handleDelete(role: AdminRole) {
    if (!window.confirm(`¿Eliminar el rol "${role.name}"? No se puede deshacer.`)) return;
    try {
      await refreshCsrfToken();
      await deleteJson(`/api/v1/admin/roles/${role.id}`);
      setMessage(`Rol "${role.name}" eliminado.`);
      reload();
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo eliminar el rol."); }
  }

  return (
    <div>
      {message ? <p className="resource-copy">{message}</p> : null}
      {canManage ? (
        <div style={{ marginBottom: "1rem" }}>
          <button className="save-button" onClick={() => { setCreating((c) => !c); setMessage(null); }}>
            {creating ? "Cancelar" : "Nuevo rol"}
          </button>
        </div>
      ) : null}
      {creating && canManage ? (
        <form className="edit-form-grid" onSubmit={createRole} style={{ marginBottom: "1.5rem" }}>
          <label>Nombre (slug)<input name="name" required minLength={3} pattern="^[a-z0-9_-]+" placeholder="ej: coordinador" /></label>
          <label>Descripción<input name="description" /></label>
          <div className="edit-form-wide">
            <p style={{ margin: "0 0 0.5rem", fontWeight: 600, fontSize: "0.9rem" }}>Permisos</p>
            <PermCheckboxes key="create" groups={groups} />
          </div>
          <button className="save-button">Crear rol</button>
        </form>
      ) : null}
      {loading ? <p className="muted-copy">Cargando…</p> : (
        <table className="staging-table">
          <thead>
            <tr>
              <th>Nombre</th><th>Descripción</th><th>Permisos</th>
              {canManage ? <th>Acciones</th> : null}
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.id}>
                <td><code>{r.name}</code></td>
                <td>{r.description ?? <em className="muted-copy">Sin descripción</em>}</td>
                <td>{r.permission_codes.length}</td>
                {canManage ? (
                  <td>
                    <button className="channel-btn" onClick={() => { setEditTarget(r); setMessage(null); }}>Editar</button>
                    {r.name !== "admin" ? (
                      <>{" "}<button className="channel-btn" onClick={() => handleDelete(r)}>Eliminar</button></>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editTarget ? (
        <div className="edit-dialog-backdrop" role="presentation" onClick={() => setEditTarget(null)}>
          <div className="edit-dialog edit-dialog-wide" onClick={(e) => e.stopPropagation()}>
            <div className="edit-dialog-heading"><div><p className="eyebrow">EDITAR ROL</p><h3>{editTarget.name}</h3></div></div>
            <form className="edit-form-grid" onSubmit={saveEdit}>
              <label>
                Nombre
                {editTarget.name === "admin"
                  ? <input name="name" defaultValue={editTarget.name} readOnly />
                  : <input name="name" required minLength={3} pattern="^[a-z0-9_-]+" defaultValue={editTarget.name} />}
              </label>
              <label>Descripción<input name="description" defaultValue={editTarget.description ?? ""} /></label>
              <div className="edit-form-wide">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 600, fontSize: "0.9rem" }}>Permisos</p>
                <PermCheckboxes key={editTarget.id} groups={groups} checkedCodes={editTarget.permission_codes} />
              </div>
              <div className="edit-dialog-actions edit-form-wide">
                <button className="save-button" type="submit">Guardar</button>
                <button className="cancel-button" type="button" onClick={() => setEditTarget(null)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
