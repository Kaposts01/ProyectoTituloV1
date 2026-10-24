import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { getJson, postJson, putJson, patchJson } from "../../api";
import { refreshCsrfToken } from "../shared/utils";
import type { AdminRole, AuthUser } from "../shared/types";

export function UsersSubPanel({ canManage, roles }: { canManage: boolean; roles: AdminRole[] }) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<AuthUser | null>(null);
  const [pwTarget, setPwTarget] = useState<AuthUser | null>(null);
  const [creating, setCreating] = useState(false);

  function reload() {
    getJson<AuthUser[]>("/api/v1/admin/users")
      .then((u) => { setUsers(u); setLoading(false); })
      .catch(() => { setMessage("No se pudieron cargar los usuarios."); setLoading(false); });
  }
  useEffect(() => { reload(); }, []);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await postJson("/api/v1/admin/users", { username: form.get("username"), password: form.get("password"), role_ids: form.getAll("role_ids") });
      event.currentTarget.reset();
      setCreating(false);
      setMessage("Usuario creado.");
      reload();
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo crear el usuario."); }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editTarget) return;
    const form = new FormData(event.currentTarget);
    try {
      await putJson(`/api/v1/admin/users/${editTarget.id}`, { role_ids: form.getAll("role_ids"), is_active: form.get("is_active") === "true" });
      setEditTarget(null);
      setMessage("Usuario actualizado.");
      reload();
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo actualizar el usuario."); }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pwTarget) return;
    const form = new FormData(event.currentTarget);
    try {
      await refreshCsrfToken();
      await patchJson(`/api/v1/admin/users/${pwTarget.id}/password`, { new_password: form.get("new_password") });
      setPwTarget(null);
      setMessage("Contraseña actualizada.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "No se pudo cambiar la contraseña."); }
  }

  return (
    <div>
      {message ? <p className="resource-copy">{message}</p> : null}
      {canManage ? (
        <div style={{ marginBottom: "1rem" }}>
          <button className="save-button" onClick={() => { setCreating((c) => !c); setMessage(null); }}>
            {creating ? "Cancelar" : "Nuevo usuario"}
          </button>
        </div>
      ) : null}
      {creating && canManage ? (
        <form className="edit-form-grid" onSubmit={createUser} style={{ marginBottom: "1.5rem" }}>
          <label>Usuario<input name="username" required minLength={3} /></label>
          <label>Contraseña temporal<input name="password" type="password" required minLength={12} /></label>
          <fieldset className="edit-form-wide">
            <legend>Roles</legend>
            {roles.map((r) => <label key={r.id}><input type="checkbox" name="role_ids" value={r.id} /> {r.name}</label>)}
          </fieldset>
          <button className="save-button">Crear</button>
        </form>
      ) : null}
      {loading ? <p className="muted-copy">Cargando…</p> : (
        <table className="staging-table">
          <thead>
            <tr>
              <th>Usuario</th><th>Roles</th><th>Estado</th><th>Creado</th>
              {canManage ? <th>Acciones</th> : null}
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.roles.length ? u.roles.map((r) => r.name).join(", ") : <em className="muted-copy">Sin roles</em>}</td>
                <td><span className={`badge ${u.is_active ? "badge-green" : "badge-gray"}`}>{u.is_active ? "Activo" : "Inactivo"}</span></td>
                <td>{u.created_at ? new Date(u.created_at).toLocaleDateString("es-CL") : "-"}</td>
                {canManage ? (
                  <td>
                    <button className="channel-btn" onClick={() => { setEditTarget(u); setMessage(null); }}>Editar</button>{" "}
                    <button className="channel-btn" onClick={() => { setPwTarget(u); setMessage(null); }}>Contraseña</button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editTarget ? (
        <div className="edit-dialog-backdrop" role="presentation" onClick={() => setEditTarget(null)}>
          <div className="edit-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="edit-dialog-heading"><div><p className="eyebrow">EDITAR USUARIO</p><h3>{editTarget.username}</h3></div></div>
            <form className="edit-form-grid" onSubmit={saveEdit}>
              <fieldset className="edit-form-wide">
                <legend>Roles</legend>
                {roles.map((r) => (
                  <label key={r.id}>
                    <input type="checkbox" name="role_ids" value={r.id} defaultChecked={editTarget.roles.some((er) => er.id === r.id)} /> {r.name}
                  </label>
                ))}
              </fieldset>
              <label className="edit-form-wide">
                Estado
                <select name="is_active" defaultValue={String(editTarget.is_active)}>
                  <option value="true">Activo</option>
                  <option value="false">Inactivo</option>
                </select>
              </label>
              <div className="edit-dialog-actions edit-form-wide">
                <button className="save-button" type="submit">Guardar</button>
                <button className="cancel-button" type="button" onClick={() => setEditTarget(null)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
      {pwTarget ? (
        <div className="edit-dialog-backdrop" role="presentation" onClick={() => setPwTarget(null)}>
          <div className="edit-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="edit-dialog-heading"><div><p className="eyebrow">CAMBIAR CONTRASEÑA</p><h3>{pwTarget.username}</h3></div></div>
            <form className="edit-form-grid" onSubmit={changePassword}>
              <label className="edit-form-wide">
                Nueva contraseña (mínimo 12 caracteres)
                <input name="new_password" type="password" required minLength={12} />
              </label>
              <div className="edit-dialog-actions edit-form-wide">
                <button className="save-button" type="submit">Guardar</button>
                <button className="cancel-button" type="button" onClick={() => setPwTarget(null)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
