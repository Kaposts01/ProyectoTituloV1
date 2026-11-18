import { useId, type KeyboardEvent, type ReactNode } from "react";
import { NavIcon, type IconName } from "./sidebarIcons";

type Props = {
  section: string;
  label: string;
  icon?: IconName;
  badge?: string;
  open: boolean;
  active: boolean;
  searching: boolean;
  onToggle: () => void;
  children: ReactNode;
  detail?: boolean;
};

/** Native disclosure buttons retain normal Tab navigation; hidden panels cannot receive focus. */
export function SidebarSection({ section, label, icon, badge, open, active, searching, onToggle, children, detail = false }: Props) {
  const id = useId();
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (searching) return;
    const button = event.currentTarget.firstElementChild as HTMLButtonElement;
    if (event.target === button && event.key === "ArrowRight" && !open) {
      event.preventDefault(); event.stopPropagation(); onToggle();
    } else if (event.key === "ArrowLeft" && open) {
      event.preventDefault(); event.stopPropagation(); button.focus(); onToggle();
    }
  };
  return (
    <div className={`sidebar-disclosure${badge ? " sidebar-channel-disclosure" : ""}`} onKeyDown={onKeyDown}>
      <button
        type="button" className={`sidebar-section-toggle${detail ? " sidebar-detail-toggle" : ""}${active ? " has-active" : ""}`}
        data-section={section} data-tip={label}
        aria-expanded={open} aria-controls={id} disabled={searching} onClick={onToggle}
      >
        {icon ? <NavIcon name={icon} /> : <span className="sidebar-channel-mark" aria-hidden="true">{badge}</span>}
        <span className="sidebar-label sidebar-section-title">{label}</span>
        <NavIcon name="chevron" className="sidebar-section-chevron" />
      </button>
      <div id={id} hidden={!open} className={`sidebar-disclosure-body${detail ? " sidebar-detail-body" : ""}`}>
        {children}
      </div>
    </div>
  );
}
