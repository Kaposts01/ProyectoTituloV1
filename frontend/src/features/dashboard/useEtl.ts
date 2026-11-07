import { useState } from "react";
import { getJson, postJson, friendlyError } from "../../api";
import type { EtlRun } from "../shared/types";

/**
 * Sync completo (ETL) del dashboard general. Se llama desde AppCore para que la corrida en curso
 * y su último estado sobrevivan a la navegación, igual que antes de la extracción.
 */
/** Proveedores que lee el Sync completo: los habilitados en este ambiente (TCH entra por Excel, no por API). */
export function fullSyncProviders(isChannelEnabled: (channel: string) => boolean): string[] {
  return (["virtualpos", "toku", "payku"] as const).filter((provider) => isChannelEnabled(provider === "virtualpos" ? "virtualpos1" : provider));
}

export function useEtl(isChannelEnabled: (channel: string) => boolean) {
  const [etlRunning, setEtlRunning] = useState(false);
  const [lastEtlRun, setLastEtlRun] = useState<EtlRun | null>(null);
  const [etlError, setEtlError] = useState<string | null>(null);
  function _pollEtlRun(run_id: string) {
    const poll = setInterval(() => {
      getJson<EtlRun>(`/api/v1/etl/runs/${run_id}`)
        .then((run) => {
          setLastEtlRun(run);
          if (run.status !== "running") {
            clearInterval(poll);
            setEtlRunning(false);
          }
        })
        .catch((err: unknown) => {
          clearInterval(poll);
          setEtlRunning(false);
          setEtlError(friendlyError(err, "Error al consultar el estado del ETL."));
        });
    }, 3000);
  }
  function runFullSync() {
    if (etlRunning) return;
    setEtlRunning(true);
    setEtlError(null);
    postJson<{ run_id: string }>("/api/v1/etl/full-sync", { providers: fullSyncProviders(isChannelEnabled) })
      .then(({ run_id }) => _pollEtlRun(run_id))
      .catch((err: unknown) => {
        setEtlRunning(false);
        setEtlError(friendlyError(err, "Error al iniciar el Sync completo."));
      });
  }
  return { etlRunning, lastEtlRun, etlError, runFullSync, providers: fullSyncProviders(isChannelEnabled) };
}
