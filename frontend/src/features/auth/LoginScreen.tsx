import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { setCsrfToken } from "../../api";
import { translateApiDetail } from "../../i18n/apiErrors";
import { fetchEnvironment } from "../shared/environment";
import type { AuthSession } from "../shared/types";

const GOOGLE_ERROR_MESSAGE = "No fue posible iniciar sesión con Google.";

export function LoginScreen({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [googleError] = useState(() => new URLSearchParams(window.location.search).get("login_error") === "google");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("login_error") !== "google") return;
    params.delete("login_error");
    const query = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : "") + window.location.hash);
  }, []);

  useEffect(() => {
    let alive = true;
    fetchEnvironment()
      .then((env) => { if (alive) setGoogleEnabled(env.google_login_enabled === true); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

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
        throw new Error(("detail" in payload && typeof payload.detail === "string" && (translateApiDetail(payload.detail) ?? payload.detail)) || "No se pudo iniciar sesión");
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
        {googleError ? <p className="error-message" role="alert">{GOOGLE_ERROR_MESSAGE}</p> : null}
        {googleEnabled ? (
          <a className="secondary-button login-google" href="/api/v1/auth/google/start">
            Entrar con Google
          </a>
        ) : null}
      </section>
    </main>
  );
}
