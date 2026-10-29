import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { ChannelHealthMap } from "../hooks/useChannelHealth";
import type { ProviderSection, ProviderSource } from "../routes";
import { detailChannels, filterMenu, visibleMenu, type DetailAction, type MenuAction, type TchView } from "../navigation";
import { SidebarHealth } from "./SidebarHealth";

export type SidebarProps = {
  activeSection: ProviderSection | null;
  channel: string | null;
  tchView: string | null;
  /** «Detalle por canal» (transitorio) desplegado. */
  detailOpen: boolean;
  onToggleDetail: () => void;
  theme: "light" | "dark";
  onDashboard: () => void;
  generalView: "summary" | "clients" | "subscriptions" | "report";
  onGeneralClients: () => void;
  onGeneralSubscriptions: () => void;
  onAutoReport: () => void;
  onChannel: (source: ProviderSource) => void;
  onSection: (section: ProviderSection) => void;
  onTheme: () => void;
  onTch: (view: TchView) => void;
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

export function Sidebar({
  activeSection, channel, tchView, detailOpen, onToggleDetail, theme, onDashboard,
  generalView, onGeneralClients, onGeneralSubscriptions, onAutoReport,
  onChannel, onSection, onTheme, onTch,
  permissions, onAdmin, adminOpen, adminTab,
  onLogout, onProfile, open, onClose, recoveryOpen, onRecovery, billingOpen = false, onBilling, profileOpen = false, health,
}: SidebarProps) {
  const can = (permission: string) => permissions.includes(permission);
  const [query, setQuery] = useState("");
  const detailId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const asideRef = useRef<HTMLElement>(null);
  const openerRef = useRef<Element | null>(null);
  // Drawer modal: el contenido de fondo queda inert + aria-hidden (mismo patron que Dialog en billing/ui.tsx),
  // el foco entra al menu y, al cerrar, vuelve al elemento que lo abrio (la hamburguesa).
  useLayoutEffect(() => {
    if (!open) return;
    const aside = asideRef.current;
    openerRef.current = document.activeElement;
    const siblings = aside?.parentElement
      ? (Array.from(aside.parentElement.children).filter(
          (el) => el !== aside && !el.classList.contains("sidebar-overlay") && el instanceof HTMLElement,
        ) as HTMLElement[])
      : [];
    const saved = siblings.map((el) => ({ el, inert: el.hasAttribute("inert"), ariaHidden: el.getAttribute("aria-hidden") }));
    for (const { el } of saved) {
      el.setAttribute("inert", "");
      el.setAttribute("aria-hidden", "true");
    }
    aside?.querySelector<HTMLElement>(".sidebar-close, button")?.focus();
    return () => {
      for (const { el, inert, ariaHidden } of saved) {
        if (!inert) el.removeAttribute("inert");
        if (ariaHidden === null) el.removeAttribute("aria-hidden");
        else el.setAttribute("aria-hidden", ariaHidden);
      }
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const opener = openerRef.current;
    return () => { if (opener instanceof HTMLElement && opener.isConnected) opener.focus(); };
  }, [open]);

  const centralActive = !activeSection && !channel && !tchView && !adminOpen && !recoveryOpen && !billingOpen && !profileOpen && generalView === "summary";
  const go = (fn: () => void) => () => { fn(); onClose(); };
  const searching = query.trim() !== "";
  const { groups, channels } = filterMenu(visibleMenu(can), detailChannels(can), query);
  // Con búsqueda activa el detalle se muestra abierto para poder encontrar ahí las coincidencias.
  const detailVisible = channels.length > 0 && (detailOpen || searching);

  const runMenu = (action: MenuAction) => {
    if (action.kind === "central") {
      if (action.view === "summary") onDashboard();
      else if (action.view === "clients") onGeneralClients();
      else if (action.view === "subscriptions") onGeneralSubscriptions();
      else onAutoReport();
    } else if (action.kind === "recovery") onRecovery();
    else if (action.kind === "billing") onBilling?.();
    else onAdmin(action.view);
  };
  const menuActive = (action: MenuAction): boolean => {
    if (action.kind === "central") return action.view === "summary" ? centralActive : generalView === action.view;
    if (action.kind === "recovery") return recoveryOpen;
    if (action.kind === "billing") return billingOpen;
    return adminOpen && adminTab === action.view;
  };
  const runDetail = (action: DetailAction) => {
    if (action.kind === "channel") onChannel(action.source);
    else if (action.kind === "section") onSection(action.section);
    else onTch(action.view);
  };
  const detailActive = (action: DetailAction): boolean => {
    if (action.kind === "channel") return channel === action.source;
    if (action.kind === "section") return activeSection?.source === action.section.source && activeSection.resource === action.section.resource;
    // las fichas de TCH (cliente, suscripción, transacción) marcan su lista
    return tchView === action.view || tchView === `${action.view === "clientes" ? "cliente" : action.view === "suscripciones" ? "suscripcion" : "transaccion"}-detalle`;
  };
  const itemClass = (active: boolean) => (active ? "sidebar-item active" : "sidebar-item");

  return (
    <>
    {open ? <div className="sidebar-overlay" aria-hidden="true" onClick={onClose} /> : null}
    <aside id="app-sidebar" ref={asideRef} className={`sidebar${open ? " open" : ""}`}>
      <div className="sidebar-toprow">
        <button className="sidebar-brand" onClick={go(onDashboard)}>
          <span>Sx</span>
          <strong>SynkmetriX</strong>
        </button>
        <button className="sidebar-close" onClick={onClose} aria-label="Cerrar menú">✕</button>
      </div>
      <SidebarHealth health={health} />
      <div className="sidebar-search">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar"
          aria-label="Buscar en el menú"
          autoComplete="off"
        />
      </div>
      <nav className="sidebar-nav" aria-label="Navegacion principal">
        {groups.map((group) => (
          <div className="sidebar-group" role={group.label ? "group" : undefined} key={group.id} aria-label={group.label ?? undefined}>
            {group.label ? <div className="sidebar-section-label">{group.label}</div> : null}
            {group.items.map((item) => {
              const active = menuActive(item.action);
              return (
                <button
                  key={item.id}
                  className={itemClass(active)}
                  aria-current={active ? "page" : undefined}
                  onClick={go(() => runMenu(item.action))}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        ))}
        {channels.length > 0 ? (
          <div className="sidebar-group sidebar-detail" role="group" aria-label="Detalle por canal">
            <button
              type="button"
              className="channel-dashboard sidebar-detail-toggle"
              aria-expanded={detailVisible}
              aria-controls={detailId}
              onClick={onToggleDetail}
              disabled={searching}
            >
              <span>Detalle por canal</span>
              <span className="sidebar-transient">Transitorio</span>
              <span className="sidebar-detail-glyph" aria-hidden="true">{detailVisible ? "−" : "+"}</span>
            </button>
            {detailVisible ? (
              <div id={detailId}>
                <p className="sidebar-note">Se retira cuando existan las vistas unificadas de Cobros, Socios y Suscripciones.</p>
                {channels.map((entry) => (
                  <div className="sidebar-subgroup" role="group" aria-label={entry.name} key={entry.id}>
                    <div className="sidebar-subheading">{entry.name}</div>
                    {entry.items.map((item) => {
                      const active = detailActive(item.action);
                      return (
                        <button
                          key={item.id}
                          className={itemClass(active)}
                          aria-current={active ? "page" : undefined}
                          onClick={go(() => runDetail(item.action))}
                        >
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {groups.length === 0 && channels.length === 0 ? <p className="sidebar-note" role="status">Sin resultados para «{query.trim()}».</p> : null}
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
    </>
  );
}
