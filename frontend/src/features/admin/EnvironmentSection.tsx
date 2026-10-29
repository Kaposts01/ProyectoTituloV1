import { useEffect, useState } from "react";
import { fetchEnvironment, fetchEnvironmentSwitch, type EnvironmentInfo, type EnvironmentSwitch } from "../shared/environment";

export function EnvironmentSection({ permissions }: { permissions: string[] }) {
  const allowed = permissions.includes("system.environment.switch");
  const [current, setCurrent] = useState<EnvironmentInfo | null>(null);
  const [target, setTarget] = useState<EnvironmentSwitch | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    Promise.all([fetchEnvironment(), fetchEnvironmentSwitch()])
      .then(([env, sw]) => { if (active) { setCurrent(env); setTarget(sw); } })
      .catch(() => undefined);
    return () => { active = false; };
  }, [allowed]);

  if (!allowed || !current || !target) return null;

  const action = target.target_env === "production" ? `Volver a ${target.target_label}` : `Cambiar a ${target.target_label}`;
  const open = () => {
    if (target.url) window.open(target.url, "_blank", "noopener,noreferrer");
    setConfirming(false);
  };

  return (
    <section className="panel environment-section" aria-labelledby="environment-title">
      <h2 id="environment-title" className="section-title">Ambiente</h2>
      <p>Ambiente actual: <strong>{current.label}</strong></p>
      {target.url ? (
        <button type="button" className="secondary-button" onClick={() => setConfirming(true)}>{action}</button>
      ) : (
        <>
          <button type="button" className="secondary-button" disabled>{action}</button>
          <p className="muted-copy">No configurado (falta SANDBOX_APP_URL / PRODUCTION_APP_URL en el servidor)</p>
        </>
      )}
      {confirming && (
        <div role="alertdialog" aria-label="Confirmar cambio de ambiente" className="environment-confirm">
          <p>Vas a abrir el ambiente {target.target_label} en otra pestaña. Es otra base de datos y otra sesión: tendrás que iniciar sesión allí.</p>
          <button type="button" className="primary-button" onClick={open}>Abrir {target.target_label}</button>
          <button type="button" className="secondary-button" onClick={() => setConfirming(false)}>Cancelar</button>
        </div>
      )}
    </section>
  );
}
