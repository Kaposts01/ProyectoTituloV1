import type { FormEvent } from "react";
import { useState } from "react";
import { setCsrfToken } from "../../api";
import type { AuthSession } from "../shared/types";

export function LoginScreen({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      const payload = (await response.json()) as AuthSession | { detail?: string };
      if (!response.ok || !("user" in payload))
        throw new Error("detail" in payload ? payload.detail : "No se pudo iniciar sesión");
      setCsrfToken(payload.csrf_token);
      onLogin(payload);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "No se pudo iniciar sesión");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="panel login-panel">
        <p className="eyebrow">SYNKMETRIX</p>
        <h1>Iniciar sesión</h1>
        <form className="login-form" onSubmit={submit}>
          <label>
            Usuario
            <input name="username" required autoComplete="username" />
          </label>
          <label>
            Contraseña
            <input name="password" type="password" required autoComplete="current-password" />
          </label>
          <button className="save-button" disabled={submitting}>
            {submitting ? "Ingresando..." : "Ingresar"}
          </button>
        </form>
        {error ? <p className="error-message">{error}</p> : null}
      </section>
    </main>
  );
}
