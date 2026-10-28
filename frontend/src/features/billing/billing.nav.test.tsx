import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar, type SidebarProps } from "../../components/Sidebar";
import { parseRoute, routePath } from "../../routes";

afterEach(cleanup);

function setup(permissions: string[], over: Partial<SidebarProps> = {}) {
  const fn = vi.fn();
  const onBilling = vi.fn();
  const onClose = vi.fn();
  render(
    <Sidebar
      activeSection={null} channel={null} tchView={null} openProvider="VirtualPOS" theme="light" onDashboard={fn}
      generalView="summary" onGeneralClients={fn} onGeneralSubscriptions={fn} onAutoReport={fn} onChannel={fn} onSection={fn}
      onToggle={fn} onTheme={fn} onTch={fn} permissions={permissions} onAdmin={fn} adminOpen={false} adminTab={null}
      onLogout={fn} onProfile={fn} open onClose={onClose} recoveryOpen={false} onRecovery={fn} onBilling={onBilling} {...over}
    />,
  );
  return { onBilling, onClose };
}

describe("ruta cambios de cobro", () => {
  it("parsea y construye la ruta", () => {
    expect(parseRoute("/virtualpos/cambios-de-cobro")).toEqual({ kind: "billingChanges" });
    expect(parseRoute("/virtualpos/cambios-de-cobro/")).toEqual({ kind: "billingChanges" });
    expect(parseRoute("/virtualpos/cambios-de-cobro/x")).toBeNull();
    expect(routePath({ kind: "billingChanges" })).toBe("/virtualpos/cambios-de-cobro");
  });
});

describe("entrada del menu", () => {
  it("aparece solo con el permiso view", () => {
    setup(["virtualpos.clients.view"]);
    expect(screen.queryByRole("button", { name: "Cambios de cobro" })).toBeNull();
    cleanup();
    setup(["virtualpos.clients.view", "virtualpos.billing_changes.view"]);
    expect(screen.getByRole("button", { name: "Cambios de cobro" })).toBeTruthy();
  });

  it("navega y cierra el menu movil", () => {
    const { onBilling, onClose } = setup(["virtualpos.clients.view", "virtualpos.billing_changes.view"]);
    fireEvent.click(screen.getByRole("button", { name: "Cambios de cobro" }));
    expect(onBilling).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it("se marca activa y el dashboard no", () => {
    setup(["dashboard.view", "virtualpos.clients.view", "virtualpos.billing_changes.view"], { billingOpen: true });
    const active = Array.from(document.querySelectorAll(".sidebar-item.active")).map((n) => n.textContent);
    expect(active).toEqual(["Cambios de cobro"]);
    expect(screen.getByRole("button", { name: "Cambios de cobro" }).getAttribute("aria-current")).toBe("page");
  });
});
