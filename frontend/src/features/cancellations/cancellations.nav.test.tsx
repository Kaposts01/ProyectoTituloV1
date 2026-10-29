import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar, type SidebarProps } from "../../components/Sidebar";

afterEach(cleanup);

function setup(permissions: string[], over: Partial<SidebarProps> = {}) {
  const fn = vi.fn();
  const onCancellations = vi.fn();
  const onClose = vi.fn();
  render(
    <Sidebar
      activeSection={null} channel={null} tchView={null} detailOpen={false} onToggleDetail={fn} theme="light" onDashboard={fn}
      generalView="summary" onGeneralClients={fn} onGeneralSubscriptions={fn} onAutoReport={fn} onChannel={fn} onSection={fn}
      onTheme={fn} onTch={fn} permissions={permissions} onAdmin={fn} adminOpen={false} adminTab={null}
      onLogout={fn} onProfile={fn} open onClose={onClose} recoveryOpen={false} onRecovery={fn} onCancellations={onCancellations} {...over}
    />,
  );
  return { onCancellations, onClose };
}

describe("entrada «Bajas» del menú", () => {
  it("vive en Operación y aparece solo con el permiso de lectura de bajas", () => {
    setup(["dashboard.view", "subscriptions.cancellation.view"]);
    expect(screen.getByRole("group", { name: "Operación" }).textContent).toContain("Bajas");
    cleanup();
    setup(["dashboard.view", "subscriptions.cancellation.request", "subscriptions.cancellation.approve"]);
    expect(screen.queryByRole("button", { name: "Bajas" })).toBeNull();
  });

  it("navega, cierra el menú móvil y se marca como activa (y no Resumen)", () => {
    const { onCancellations, onClose } = setup(["dashboard.view", "subscriptions.cancellation.view"]);
    fireEvent.click(screen.getByRole("button", { name: "Bajas" }));
    expect(onCancellations).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
    cleanup();
    setup(["dashboard.view", "subscriptions.cancellation.view"], { cancellationsOpen: true });
    expect(Array.from(document.querySelectorAll(".sidebar-item.active")).map((n) => n.textContent)).toEqual(["Bajas"]);
    expect(screen.getByRole("button", { name: "Bajas" }).getAttribute("aria-current")).toBe("page");
  });
});
