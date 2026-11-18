import { useEffect, useLayoutEffect, useRef, type KeyboardEvent, type RefObject } from "react";
import { label } from "../i18n/label";
import { NavIcon } from "./sidebarIcons";

const t = (key: string) => label("sidebar", key);

type Props = {
  name: string;
  initials: string;
  pinned: boolean;
  theme: "light" | "dark";
  triggerRef: RefObject<HTMLButtonElement | null>;
  onClose: (restoreFocus?: boolean) => void;
  onPin: () => void;
  onTheme: () => void;
  onProfile: () => void;
  onLogout: () => void;
};

/** The popup is a sibling of the clipped sidebar panel, so it also fits above the compact rail. */
export function SidebarAccountMenu({ name, initials, pinned, theme, triggerRef, onClose, onPin, onTheme, onProfile, onLogout }: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus(); }, []);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target)) onClose(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [onClose, triggerRef]);

  const select = (action: () => void) => () => { onClose(); action(); };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); return; }
    if (event.key === "Tab") { onClose(); return; }
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    const index = items.findIndex((item) => item === document.activeElement);
    const target = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : event.key === "ArrowDown" ? (index + 1) % items.length
      : event.key === "ArrowUp" ? (index + items.length - 1) % items.length : null;
    if (target !== null) { event.preventDefault(); event.stopPropagation(); items[target]?.focus(); }
  };
  return (
    <div id="sidebar-account-menu" className="sidebar-account-menu" role="menu" aria-label={t("opciones de cuenta")} ref={menuRef} onKeyDown={onKeyDown}>
      <div className="sidebar-account-heading" role="presentation">
        <span className="sidebar-account-avatar" aria-hidden="true">{initials}</span>
        <strong title={name}>{name}</strong>
      </div>
      <button type="button" role="menuitemcheckbox" aria-checked={pinned} className="sidebar-account-action" onClick={select(onPin)}>
        <NavIcon name="pin" /><span>{t("mantener abierto")}</span><span className="sidebar-account-check" aria-hidden="true">{pinned ? "✓" : ""}</span>
      </button>
      <button type="button" role="menuitem" className="sidebar-account-action" aria-label={t("cambiar tema")} onClick={select(onTheme)}>
        <NavIcon name={theme === "dark" ? "sun" : "moon"} /><span>{theme === "dark" ? t("modo claro") : t("modo oscuro")}</span>
      </button>
      <button type="button" role="menuitem" className="sidebar-account-action" onClick={select(onProfile)}>
        <NavIcon name="profile" /><span>{t("mi perfil")}</span>
      </button>
      <div className="sidebar-account-separator" role="separator" />
      <button type="button" role="menuitem" className="sidebar-account-action" onClick={select(onLogout)}>
        <NavIcon name="logout" /><span>{t("cerrar sesion")}</span>
      </button>
    </div>
  );
}
