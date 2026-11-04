import { useEffect, useState } from "react";
import { fetchEnvironment, type EnvironmentInfo } from "../features/shared/environment";

/** Franja fija visible en ambientes no productivos (incluida la pantalla de login). */
export function EnvironmentBanner() {
  const [env, setEnv] = useState<EnvironmentInfo | null>(null);

  useEffect(() => {
    let active = true;
    fetchEnvironment().then((info) => { if (active) setEnv(info); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  const visible = env !== null && env.is_production === false;

  useEffect(() => {
    document.documentElement.classList.toggle("has-env-banner", visible);
    return () => document.documentElement.classList.remove("has-env-banner");
  }, [visible]);

  if (!visible || !env) return null;
  return (
    <div className="env-banner" role="status">
      <strong>{env.label.toUpperCase()}</strong>
      <span className="env-banner-detail"> · datos y credenciales de prueba, no es producción</span>
    </div>
  );
}
