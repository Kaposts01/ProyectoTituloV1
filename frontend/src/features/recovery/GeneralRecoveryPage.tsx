import { useState } from "react";
import { ChannelRecoveryPanel } from "./ChannelRecoveryPanel";
import { RecoveryPanel } from "./RecoveryPanel";
import { visibleRecoveryTabs, type RecoveryTabId } from "./recoveryChannels";

type Props = { can: (permission: string) => boolean };

/** /general/recuperador (UX-12): una pestaña por canal, solo las que el usuario tiene permiso de ver. */
export function GeneralRecoveryPage({ can }: Props) {
  const tabs = visibleRecoveryTabs(can);
  const [active, setActive] = useState<RecoveryTabId | null>(tabs[0]?.id ?? null);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0] ?? null;

  return (
    <main className="app-shell recovery-page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Operación</p>
          <h1>Recuperador de Socios</h1>
        </div>
      </div>
      {current === null ? (
        <p className="muted-copy">No tienes permiso para ver ninguna pestaña del recuperador. Pide acceso a un administrador.</p>
      ) : <>
        <div className="recovery-tabs" role="tablist" aria-label="Canal">
          {tabs.map((tab) => (
            <button key={tab.id} role="tab" aria-selected={current.id === tab.id} className={current.id === tab.id ? "active" : ""} onClick={() => setActive(tab.id)}>
              {tab.label}
            </button>
          ))}
        </div>
        {current.id === "virtualpos"
          ? <RecoveryPanel key="virtualpos" channel="virtualpos" can={can} embedded />
          : <ChannelRecoveryPanel key={current.id} channel={current.id} />}
      </>}
    </main>
  );
}
