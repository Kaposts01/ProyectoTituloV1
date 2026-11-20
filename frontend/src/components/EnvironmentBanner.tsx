import { useEffect, useLayoutEffect, useState } from "react";
import { fetchEnvironment, type EnvironmentInfo } from "../features/shared/environment";

/** La build de sandbox (`vite --mode sandbox`) sabe de antemano que mostrará la franja. */
export function reservesEnvironmentBanner(): boolean {
  return import.meta.env.MODE === "sandbox";
}

/** Reserva el espacio de la franja antes del primer render (evita el salto de página, CLS). */
export function reserveEnvironmentBannerSpace(): void {
  if (reservesEnvironmentBanner()) document.documentElement.classList.add("has-env-banner");
}

/** Franja fija visible en ambientes no productivos (incluida la pantalla de login). */
export function EnvironmentBanner() {
  const [env, setEnv] = useState<EnvironmentInfo | null>(null);
  const reserve = reservesEnvironmentBanner();

  useEffect(() => {
    let active = true;
    fetchEnvironment().then((info) => { if (active) setEnv(info); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  // Mientras llega la respuesta, en sandbox se mantiene el espacio; en producción no se reserva nada.
  const visible = env === null ? reserve : env.is_production === false;

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("has-env-banner", visible);
    return () => document.documentElement.classList.remove("has-env-banner");
  }, [visible]);

  if (!visible) return null;
  if (!env) return <div className="env-banner" aria-hidden="true" />;
  return (
    <div className="env-banner" role="status">
      <strong>{env.label.toUpperCase()}</strong>
      <span className="env-banner-detail"> · datos y credenciales de prueba, no es producción</span>
    </div>
  );
}
