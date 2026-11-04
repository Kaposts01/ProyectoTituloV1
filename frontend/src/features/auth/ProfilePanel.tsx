import type { FormEvent } from "react";
import { useState } from "react";
import { patchJson } from "../../api";
import type { AuthUser } from "../shared/types";

export function ProfilePanel({
  user,
  editing,
  onUpdated,
  onClose,
  onEdit,
  onCancelEdit,
}: {
  user: AuthUser;
  editing: boolean;
  onUpdated: (user: AuthUser) => void;
  onClose: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const newUsername = (form.get("new_username") as string).trim();
    const currentPassword = form.get("current_password") as string;
    const newPassword = (form.get("new_password") as string).trim();
    const confirmPassword = (form.get("confirm_password") as string).trim();

    if (!currentPassword) { setError("Debes ingresar tu contraseña actual."); return; }
    if (newPassword && newPassword !== confirmPassword) { setError("Las contraseñas nuevas no coinciden."); return; }
    if (!newUsername && !newPassword) { setError("No hay cambios para guardar."); return; }

    setSaving(true);
    setError(null);
    try {
      const body: Record<string, string> = { current_password: currentPassword };
      if (newUsername && newUsername !== user.username) body.new_username = newUsername;
      if (newPassword) { body.new_password = newPassword; body.confirm_password = confirmPassword; }
      const result = await patchJson<{ user: AuthUser }>("/api/v1/auth/me", body);
      onUpdated(result.user);
      setSuccess("Perfil actualizado correctamente.");
      onCancelEdit();
      event.currentTarget.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar el perfil.");
    } finally {
      setSaving(false);
    }
  }

  const memberSince = user.created_at
    ? new Date(user.created_at).toLocaleDateString("es-CL", { year: "numeric", month: "long", day: "numeric" })
    : null;

  return (
    <main className="app-shell">
      <section className="panel">
        <button className="back-button" onClick={onClose}>Volver</button>
        <p className="eyebrow">CUENTA</p>
        <h1>Mi perfil</h1>
        <div className="profile-info">
          <div className="profile-info-row">
            <span className="profile-info-label">Usuario</span>
            <span className="profile-info-value">{user.username}</span>
          </div>
          <div className="profile-info-row">
            <span className="profile-info-label">Roles</span>
            <span className="profile-info-value">
              {user.roles.length > 0 ? user.roles.map((r) => r.name).join(", ") : <em className="muted-copy">Sin roles</em>}
            </span>
          </div>
          <div className="profile-info-row">
            <span className="profile-info-label">Estado</span>
            <span className="profile-info-value">
              <span className={`badge ${user.is_active ? "badge-green" : "badge-gray"}`}>
                {user.is_active ? "Activo" : "Inactivo"}
              </span>
            </span>
          </div>
          {memberSince && (
            <div className="profile-info-row">
              <span className="profile-info-label">Miembro desde</span>
              <span className="profile-info-value">{memberSince}</span>
            </div>
          )}
        </div>
        {success && !editing && <p className="profile-success">{success}</p>}
        {!editing ? (
          <button className="edit-button" style={{ marginTop: "1rem" }} onClick={() => { setSuccess(null); setError(null); onEdit(); }}>
            Editar perfil
          </button>
        ) : (
          <form className="edit-form-grid profile-edit-form" onSubmit={handleSubmit} noValidate>
            <p className="eyebrow" style={{ gridColumn: "1 / -1", marginTop: "1.25rem" }}>EDITAR PERFIL</p>
            <label>
              Nuevo nombre de usuario
              <input name="new_username" defaultValue={user.username} minLength={3} maxLength={100} autoComplete="username" />
            </label>
            <label>
              Contraseña actual <span className="field-required" aria-hidden="true">*</span>
              <input name="current_password" type="password" required autoComplete="current-password" />
            </label>
            <label>
              Nueva contraseña
              <input name="new_password" type="password" minLength={6} maxLength={256} autoComplete="new-password" placeholder="Dejar en blanco para no cambiar" />
            </label>
            <label>
              Confirmar nueva contraseña
              <input name="confirm_password" type="password" maxLength={256} autoComplete="new-password" placeholder="Repetir nueva contraseña" />
            </label>
            {error && <p className="profile-error" style={{ gridColumn: "1 / -1" }}>{error}</p>}
            <div className="profile-form-actions" style={{ gridColumn: "1 / -1" }}>
              <button className="save-button" type="submit" disabled={saving}>{saving ? "Guardando..." : "Guardar cambios"}</button>
              <button className="cancel-btn" type="button" onClick={() => { setError(null); onCancelEdit(); }}>Cancelar</button>
            </div>
          </form>
        )}
      </section>
    </main>
  );
}
