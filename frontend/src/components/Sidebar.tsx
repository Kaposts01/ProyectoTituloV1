import { useEffect, useId, useLayoutEffect, useRef, useState, type FocusEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { ChannelHealthMap } from "../hooks/useChannelHealth";
import { label } from "../i18n/label";
import type { ProviderSection, ProviderSource } from "../routes";
import { detailChannels, filterMenu, visibleMenu, type DetailAction, type MenuAction, type TchView } from "../navigation";
import { SidebarHealth } from "./SidebarHealth";
import { MENU_ICONS } from "./sidebarIconMap";
import { NavIcon } from "./sidebarIcons";

export type SidebarProps = {
  activeSection: ProviderSection | null;
  channel: string | null;
  tchView: string | null;
  /** «Detalle por canal» (transitorio) desplegado. */
  detailOpen: boolean;
  onToggleDetail: () => void;
  theme: "light" | "dark";
  onDashboard: () => void;
  generalView: "summary" | "clients" | "subscriptions" | "charges" | "report";
  onGeneralClients: () => void;
  onGeneralSubscriptions: () => void;
  /** Cobros unificados (UX-09). */
  onGeneralCharges?: () => void;
  onAutoReport: () => void;
  onChannel: (source: ProviderSource) => void;
  onSection: (section: ProviderSection) => void;
  onTheme: () => void;
  onTch: (view: TchView) => void;
  permissions: string[];
  onAdmin: (view: "users" | "sync") => void;
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
  cancellationsOpen?: boolean;
  onCancellations?: () => void;
  profileOpen?: boolean;
  health?: ChannelHealthMap;
};

/** Preferencia «Mantener menú abierto» (por navegador; no es dato de negocio). */
export const SIDEBAR_PINNED_KEY = "crm-sidebar-pinned";
/** Intención de hover: abrir tras una pausa corta evita desplegar el menú al cruzarlo con el puntero. */
export const HOVER_OPEN_MS = 150;
export const HOVER_CLOSE_MS = 200;
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const t = (key: string) => label("sidebar", key);

function readPinned(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_PINNED_KEY) === "1";
  } catch {
    return false;
  }
}
function writePinned(value: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, value ? "1" : "0");
  } catch {
    /* almacenamiento bloqueado (modo privado): la preferencia vive solo en esta pestaña */
  }
}
function prefersReducedMotion(): boolean {
  try {
    return typeof window.matchMedia === "function" && window.matchMedia(REDUCED_MOTION).matches;
  } catch {
    return false;
  }
}

export function Sidebar({
  activeSection, channel, tchView, detailOpen, onToggleDetail, theme, onDashboard,
  generalView, onGeneralClients, onGeneralSubscriptions, onGeneralCharges, onAutoReport,
  onChannel, onSection, onTheme, onTch,
  permissions, onAdmin, adminOpen, adminTab,
  onLogout, onProfile, open, onClose, recoveryOpen, onRecovery, billingOpen = false, onBilling, cancellationsOpen = false, onCancellations, profileOpen = false, health,
}: SidebarProps) {
  const can = (permission: string) => permissions.includes(permission);
  const [query, setQuery] = useState("");
  const detailId = useId();
  // id fijo (hay un solo menú): un useId() extra correría los ids generados del resto de la app
  const panelId = "app-sidebar-panel";

  /* ── Rail compacto: fijado (recordado), hover con intención y «asomo» por teclado ── */
  const [pinned, setPinned] = useState(readPinned);
  const [hovered, setHovered] = useState(false);
  const [peek, setPeek] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);
  const [tip, setTip] = useState<{ text: string; top: number; left: number } | null>(null);
  const hoverTimer = useRef<number | undefined>(undefined);
  const asideRef = useRef<HTMLElement>(null);
  const expanded = pinned || hovered || peek || open;

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(REDUCED_MOTION);
    const onChange = () => setReducedMotion(media.matches);
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, []);
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);

  const togglePinned = () => {
    setPinned((value) => {
      writePinned(!value);
      return !value;
    });
  };
  const onPointerEnter = () => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => { setHovered(true); setTip(null); }, HOVER_OPEN_MS);
  };
  const onPointerLeave = () => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setHovered(false), HOVER_CLOSE_MS);
  };
  // Tooltip con el nombre en modo compacto: al recibir foco un ítem (teclado). Con el puntero el menú se despliega.
  const onFocusCapture = (event: FocusEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (target.matches("input[type='search']") && !expanded) { setPeek(true); return; }
    const anchor = target.closest<HTMLElement>("[data-tip]");
    if (!anchor || expanded) { setTip(null); return; }
    const rect = anchor.getBoundingClientRect();
    const aside = asideRef.current?.getBoundingClientRect();
    setTip({ text: anchor.dataset.tip ?? "", top: rect.top + rect.height / 2, left: (aside?.right ?? rect.right) + 8 });
  };
  const onBlurCapture = (event: FocusEvent<HTMLElement>) => {
    const next = event.relatedTarget as Node | null;
    if (!next || !asideRef.current?.contains(next)) { setPeek(false); setTip(null); }
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && peek && !open) { setPeek(false); setTip(null); }
  };
  // Lo que necesita espacio (salud, detalle por canal) despliega el rail mientras el foco siga dentro.
  const needRoom = () => { if (!expanded) { setPeek(true); setTip(null); } };

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
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

  const centralActive = !activeSection && !channel && !tchView && !adminOpen && !recoveryOpen && !billingOpen && !cancellationsOpen && !profileOpen && generalView === "summary";
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
      else if (action.view === "charges") onGeneralCharges?.();
      else onAutoReport();
    } else if (action.kind === "recovery") onRecovery();
    else if (action.kind === "billing") onBilling?.();
    else if (action.kind === "cancellations") onCancellations?.();
    else onAdmin(action.view);
  };
  const menuActive = (action: MenuAction): boolean => {
    if (action.kind === "central") return action.view === "summary" ? centralActive : generalView === action.view;
    if (action.kind === "recovery") return recoveryOpen;
    if (action.kind === "billing") return billingOpen;
    if (action.kind === "cancellations") return cancellationsOpen;
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
    return tchView === action.view || tchView === `${action.view === "clients" ? "client" : action.view === "subscriptions" ? "subscription" : "transaction"}-detail`;
  };
  const detailHasActive = channels.some((entry) => entry.items.some((item) => detailActive(item.action)));
  const itemClass = (active: boolean) => (active ? "sidebar-item active" : "sidebar-item");

  return (
    <>
    {open ? <div className="sidebar-overlay" aria-hidden="true" onClick={onClose} /> : null}
    <aside
      id="app-sidebar"
      ref={asideRef}
      className={`sidebar${open ? " open" : ""}${pinned ? " is-pinned" : ""}`}
      data-state={expanded ? "expanded" : "compact"}
      data-motion={reducedMotion ? "reduced" : "full"}
      onKeyDown={onKeyDown}
    >
      <div
        id={panelId}
        className="sidebar-panel"
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
        onFocusCapture={onFocusCapture}
        onBlurCapture={onBlurCapture}
      >
        <div className="sidebar-toprow">
          <button className="sidebar-brand" onClick={go(onDashboard)} data-tip={t("ir al resumen")}>
            <span aria-hidden="true">Sx</span>
            <strong className="sidebar-label">SynkmetriX</strong>
          </button>
          <button className="sidebar-close" onClick={onClose} aria-label={t("cerrar menu")}>
            <NavIcon name="close" />
          </button>
        </div>
        <div className="sidebar-health-slot" onClickCapture={needRoom}>
          <SidebarHealth health={health} />
        </div>
        <div className="sidebar-search">
          <NavIcon name="search" className="sidebar-search-icon" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("buscar")}
            aria-label={t("buscar en el menu")}
            autoComplete="off"
          />
        </div>
        <nav className="sidebar-nav" aria-label={t("navegacion")}>
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
                    data-tip={item.label}
                    data-item={item.id}
                    onClick={go(() => runMenu(item.action))}
                  >
                    <NavIcon name={MENU_ICONS[item.id] ?? "summary"} />
                    <span className="sidebar-label">{item.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
          {channels.length > 0 ? (
            <div className="sidebar-group sidebar-detail" role="group" aria-label={t("detalle por canal")}>
              <button
                type="button"
                className={`sidebar-detail-toggle${detailHasActive ? " has-active" : ""}`}
                aria-expanded={detailVisible}
                aria-controls={detailId}
                data-tip={t("detalle por canal")}
                onClick={() => { needRoom(); onToggleDetail(); }}
                disabled={searching}
              >
                <NavIcon name="channels" />
                <span className="sidebar-label sidebar-detail-text">
                  <span>{t("detalle por canal")}</span>
                  <span className="sidebar-transient">{t("transitorio")}</span>
                </span>
                <NavIcon name="chevron" className="sidebar-detail-chevron" />
              </button>
              {detailVisible ? (
                <div id={detailId} className="sidebar-detail-body">
                  <p className="sidebar-note">{t("aviso transitorio")}</p>
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
          {groups.length === 0 && channels.length === 0 ? <p className="sidebar-note" role="status">{t("sin resultados")} «{query.trim()}».</p> : null}
        </nav>
        <div className="sidebar-footer">
          <button
            type="button"
            className="sidebar-item sidebar-pin"
            aria-pressed={pinned}
            aria-controls={panelId}
            data-tip={t("mantener abierto")}
            onClick={togglePinned}
          >
            <NavIcon name="pin" />
            <span className="sidebar-label">{t("mantener abierto")}</span>
          </button>
          <button className="sidebar-item" onClick={onTheme} aria-label={t("cambiar tema")} data-tip={theme === "dark" ? t("modo claro") : t("modo oscuro")}>
            <NavIcon name={theme === "dark" ? "sun" : "moon"} />
            <span className="sidebar-label">{theme === "dark" ? t("modo claro") : t("modo oscuro")}</span>
          </button>
          <button className="sidebar-item" onClick={go(onProfile)} data-tip={t("mi perfil")}>
            <NavIcon name="profile" />
            <span className="sidebar-label">{t("mi perfil")}</span>
          </button>
          <button className="sidebar-item" onClick={go(onLogout)} data-tip={t("cerrar sesion")}>
            <NavIcon name="logout" />
            <span className="sidebar-label">{t("cerrar sesion")}</span>
          </button>
        </div>
      </div>
      {tip && !expanded ? (
        <div className="sidebar-tooltip" aria-hidden="true" style={{ top: tip.top, left: tip.left }}>{tip.text}</div>
      ) : null}
    </aside>
    </>
  );
}
