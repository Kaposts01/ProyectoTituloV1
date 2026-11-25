import { pageLabels } from "../../pageLabels";
import { useState } from "react";
import { ChannelRecoveryPanel } from "./ChannelRecoveryPanel";
import { RecoveryPanel } from "./RecoveryPanel";
import { RecoveryPilot } from "./RecoveryPilot";
import { canOpenPilot } from "./pilotContract";
import { visibleRecoveryTabs, type RecoveryTabId } from "./recoveryChannels";

type Props = { can: (permission: string) => boolean; owner?: string };

/** /general/recuperador (UX-12): una pestaña por canal, solo las que el usuario tiene permiso de ver. */
export function GeneralRecoveryPage({ can, owner }: Props) {
  const tabs = visibleRecoveryTabs(can);
  const [active, setActive] = useState<RecoveryTabId | null>(tabs[0]?.id ?? null);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0] ?? null;
  const [pilotMode, setPilotMode] = useState(false);
  const pilotAllowed = import.meta.env.VITE_ML_RECOVERY_PILOT_ENABLED === "true" && canOpenPilot(can, owner);
  const showPilot = current?.id === "tch" && pilotAllowed && pilotMode;

  return (
    <main className="app-shell recovery-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Operación</p>
          <h1>{pageLabels.recovery}</h1>
        </div>
      </div>
      {current === null ? (
        <p className="muted-copy">No tienes permiso para ver ninguna pestaña del recuperador. Pide acceso a un administrador.</p>
      ) : <>
        <div className="recovery-tabs" role="tablist" aria-label="Canal">
          {tabs.map((tab) => (
            <button key={tab.id} role="tab" aria-selected={current.id === tab.id} className={current.id === tab.id ? "active" : ""} onClick={() => { setActive(tab.id); setPilotMode(false); }}>
              {tab.label}
            </button>
          ))}
        </div>
        {current.id === "tch" && pilotAllowed && <div className="ml-pilot-entry"><button type="button" aria-pressed={showPilot} onClick={() => setPilotMode((value) => !value)}>{showPilot ? "Volver a gestión TCH" : "Ver piloto con datos de prueba"}</button></div>}
        {showPilot ? <RecoveryPilot key={owner} /> : current.id === "virtualpos"
          ? <RecoveryPanel key="virtualpos" channel="virtualpos" can={can} embedded />
          : <ChannelRecoveryPanel key={current.id} channel={current.id} />}
      </>}
    </main>
  );
}
