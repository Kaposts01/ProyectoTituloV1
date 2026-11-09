import { useEffect, useState } from "react";
import { fetchEnvironment, type EnvironmentInfo } from "../shared/environment";
import { EtlPanel } from "./EtlPanel";
import { GeneralClientsPanel } from "./GeneralClientsPanel";
import { GeneralSubscriptionsPanel } from "./GeneralSubscriptionsPanel";
import type { GeneralState } from "./useGeneralDashboard";
import type { useEtl } from "./useEtl";

/**
 * Chip del ambiente real (QA-02): antes decía siempre «Staging local», también en producción. Ahora muestra la
 * etiqueta que entrega el servidor y no se pinta en producción ni mientras el dato no llega.
 */
export function EnvironmentChip() {
  const [env, setEnv] = useState<EnvironmentInfo | null>(null);
  useEffect(() => {
    let active = true;
    fetchEnvironment().then((info) => { if (active) setEnv(info); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  if (!env || env.is_production) return null;
  return <div className="sync-state ready"><span />{env.label}</div>;
}

/**
 * Marco de las vistas consolidadas que aún no tienen pantalla propia (Socios): cabecera con el patrón de Cartera
 * (eyebrow «Cartera» y h1 con el nombre de la pantalla, QA-10), la tabla según `generalView` y el panel del ETL,
 * solo para quien puede lanzarlo (`etl.run`). La vista anterior del resumen (/central/resumen-clasico) se retiró en UX-15;
 * el resumen vive en features/summary.
 */
export function GeneralDashboardView({ general, etl, error, setError, can }: {
  general: GeneralState;
  etl: ReturnType<typeof useEtl>;
  error: string | null;
  setError: (message: string | null) => void;
  can?: (permission: string) => boolean;
}) {
  const { generalView } = general;
  const isSubscriptions = generalView === "subscriptions";
  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Cartera</p>
          <h1>{isSubscriptions ? "Suscripciones" : "Socios"}</h1>
        </div>
        <EnvironmentChip />
      </header>
      {error ? <p className="error-message">{error}</p> : null}
      {isSubscriptions ? (
        <GeneralSubscriptionsPanel general={general} can={can} />
      ) : (
        <GeneralClientsPanel general={general} setError={setError} can={can} />
      )}
      {can === undefined || can("etl.run") ? (
        <EtlPanel etlRunning={etl.etlRunning} lastEtlRun={etl.lastEtlRun} etlError={etl.etlError} runFullSync={etl.runFullSync} providers={etl.providers} />
      ) : null}
    </main>
  );
}
