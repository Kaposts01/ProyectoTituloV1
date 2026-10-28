import { useEffect } from "react";
import type { ChannelHealthMap, HealthChannel } from "../hooks/useChannelHealth";
import type { ProviderSection, ProviderSource } from "../routes";
import { providerGroups, resourcePermission } from "../navigation";

export type SidebarProps = {
  activeSection: ProviderSection | null;
  channel: string | null;
  tchView: string | null;
  openProvider: string | null;
  theme: "light" | "dark";
  onDashboard: () => void;
  generalView: "summary" | "clients" | "subscriptions" | "report";
  onGeneralClients: () => void;
  onGeneralSubscriptions: () => void;
  onAutoReport: () => void;
  onChannel: (source: ProviderSource) => void;
  onSection: (section: ProviderSection) => void;
  onToggle: (provider: string) => void;
  onTheme: () => void;
  onTch: (view: "summary" | "clientes" | "suscripciones" | "transacciones") => void;
  permissions: string[];
  onAdmin: (view: "usuarios" | "sincronizacion") => void;
  adminOpen: boolean;
  adminTab: string | null;
  onLogout: () => void;
  onProfile: () => void;
  open: boolean;
  onClose: () => void;
  recoveryOpen: boolean;
  onRecovery: () => void;
  billingOpen?: boolean;
  onBilling?: () => void;
  profileOpen?: boolean;
  health?: ChannelHealthMap;
};

const LEVEL_LABEL = { ok: "Sincronizado", warn: "Sincronización atrasada", error: "Error de sincronización", unknown: "Sin datos de sincronización" } as const;

function HealthDot({ channel, health }: { channel: HealthChannel; health?: ChannelHealthMap }) {
  const entry = health?.[channel];
  if (!entry) return null;
  const age = entry.age_hours;
  const text = age === null || age === undefined ? LEVEL_LABEL[entry.level] : `${LEVEL_LABEL[entry.level]}: hace ${Math.round(age)} h`;
  return <span className={`health-dot mono ${entry.level}`} role="img" aria-label={text} title={text} data-level={entry.level} />;
}

export function Sidebar({
  activeSection, channel, tchView, openProvider, theme, onDashboard,
  generalView, onGeneralClients, onGeneralSubscriptions, onAutoReport,
  onChannel, onSection, onToggle, onTheme, onTch,
  permissions, onAdmin, adminOpen, adminTab,
  onLogout, onProfile, open, onClose, recoveryOpen, onRecovery, billingOpen = false, onBilling, profileOpen = false, health,
}: SidebarProps) {
  const can = (permission: string) => permissions.includes(permission);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const centralActive = !activeSection && !channel && !tchView && !adminOpen && !recoveryOpen && !billingOpen && !profileOpen && generalView === "summary";
  const go = (fn: () => void) => () => { fn(); onClose(); };
  const visibleGroups = providerGroups.map((group) => ({
    ...group,
    sections: group.sections.filter((section) => can(resourcePermission(section.source, section.resource))),
  })).filter((group) => group.sections.length > 0);
  return (
    <aside id="app-sidebar" className={`sidebar${open ? " open" : ""}`}>
      <div className="sidebar-toprow">
        <button className="sidebar-brand" onClick={go(onDashboard)}>
          <span>Sx</span>
          <strong>SynkmetriX</strong>
        </button>
        <button className="sidebar-close" onClick={onClose} aria-label="Cerrar menú">✕</button>
      </div>
      <nav className="sidebar-nav" aria-label="Navegacion principal">
        {can("dashboard.view") ? <button
          className={centralActive ? "sidebar-item active" : "sidebar-item"}
          onClick={go(onDashboard)}
        >
          Dashboard
        </button> : null}
        {can("dashboard.view") ? <>
          <button className={generalView === "clients" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(onGeneralClients)}>Clientes</button>
          <button className={generalView === "subscriptions" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(onGeneralSubscriptions)}>Suscripciones</button>
          <button className={generalView === "report" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(onAutoReport)}>Reporte automático</button>
        </> : null}
        {visibleGroups.map((group) => (
          <section className="sidebar-group" key={group.name}>
            <div className="channel-heading">
              <button
                className={channel === group.sections[0].source ? "channel-dashboard active" : "channel-dashboard"}
                onClick={go(() => onChannel(group.sections[0].source))}
              >
                {group.name}
              </button>
              <HealthDot channel={group.sections[0].source as HealthChannel} health={health} />
              <button
                className="sidebar-expand"
                aria-label={`Expandir ${group.name}`}
                aria-expanded={openProvider === group.name}
                onClick={() => onToggle(group.name)}
              >
                {openProvider === group.name ? "-" : "+"}
              </button>
            </div>
            {openProvider === group.name
              ? <>
                  {group.sections.map((section) => (
                    <button
                      className={
                        activeSection?.source === section.source &&
                        activeSection.resource === section.resource
                          ? "sidebar-item nested active"
                          : "sidebar-item nested"
                      }
                      key={section.resource}
                      onClick={go(() => onSection(section))}
                    >
                      {section.label}
                    </button>
                  ))}
                  {group.name === "VirtualPOS" && can("virtualpos.recovery.view") ? (
                    <button
                      className={recoveryOpen ? "sidebar-item nested active" : "sidebar-item nested"}
                      onClick={go(onRecovery)}
                    >
                      Recuperador de Socios
                    </button>
                  ) : null}
                  {group.name === "VirtualPOS" && onBilling && can("virtualpos.billing_changes.view") ? (
                    <button
                      className={billingOpen ? "sidebar-item nested active" : "sidebar-item nested"}
                      aria-current={billingOpen ? "page" : undefined}
                      onClick={go(onBilling)}
                    >
                      Cambios de cobro
                    </button>
                  ) : null}
                </>
              : null}
          </section>
        ))}
        {can("tch.dashboard.view") ? (
          <section className="sidebar-group">
            <div className="channel-heading">
              <button
                className={tchView ? "channel-dashboard active" : "channel-dashboard"}
                onClick={go(() => onTch("summary"))}
              >
                TCH
              </button>
              <HealthDot channel="tch" health={health} />
              <button
                className="sidebar-expand"
                aria-label="Expandir TCH"
                aria-expanded={openProvider === "TCH"}
                onClick={() => onToggle("TCH")}
              >
                {openProvider === "TCH" ? "-" : "+"}
              </button>
            </div>
            {openProvider === "TCH" ? (
              <>
                {can("tch.clientes.view") ? <button className={tchView === "clientes" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("clientes"))}>Clientes</button> : null}
                {can("tch.suscripciones.view") ? <button className={tchView === "suscripciones" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("suscripciones"))}>Suscripciones</button> : null}
                {can("tch.transacciones.view") ? <button className={tchView === "transacciones" ? "sidebar-item nested active" : "sidebar-item nested"} onClick={go(() => onTch("transacciones"))}>Transacciones</button> : null}
              </>
            ) : null}
          </section>
        ) : null}
        {can("users.manage") || can("roles.manage") || can("sync_runs.view") || can("sync.run") ? (
          <section className="sidebar-group">
            <div className="channel-heading">
              <button
                className={adminOpen ? "channel-dashboard active" : "channel-dashboard"}
                onClick={go(() => onAdmin(can("users.manage") || can("roles.manage") ? "usuarios" : "sincronizacion"))}
              >
                Administración
              </button>
              <button
                className="sidebar-expand"
                aria-label="Expandir Administración"
                aria-expanded={openProvider === "Administración"}
                onClick={() => onToggle("Administración")}
              >
                {openProvider === "Administración" ? "-" : "+"}
              </button>
            </div>
            {openProvider === "Administración" ? (
              <>
                {can("users.manage") || can("roles.manage") ? (
                  <button
                    className={adminOpen && adminTab === "usuarios" ? "sidebar-item nested active" : "sidebar-item nested"}
                    onClick={go(() => onAdmin("usuarios"))}
                  >
                    Usuarios
                  </button>
                ) : null}
                {can("sync_runs.view") || can("sync.run") ? (
                  <button
                    className={adminOpen && adminTab === "sincronizacion" ? "sidebar-item nested active" : "sidebar-item nested"}
                    onClick={go(() => onAdmin("sincronizacion"))}
                  >
                    Sincronización
                  </button>
                ) : null}
              </>
            ) : null}
          </section>
        ) : null}
      </nav>
      <div className="sidebar-footer">
        <button className="theme-btn" onClick={onTheme} aria-label="Cambiar tema">
          <span className="theme-btn-icon">{theme === "dark" ? "☀" : "◐"}</span>
          {theme === "dark" ? "Modo claro" : "Modo oscuro"}
        </button>
        <button className="theme-btn" onClick={go(onProfile)}>Mi perfil</button>
        <button className="theme-btn" onClick={go(onLogout)}>Cerrar sesión</button>
      </div>
    </aside>
  );
}
