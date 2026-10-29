import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar, type SidebarProps } from "./Sidebar";

const allPerms = [
  "dashboard.view", "virtualpos.clients.view", "toku.customers.view", "payku.clients.view",
  "tch.dashboard.view", "tch.clientes.view", "tch.suscripciones.view", "tch.transacciones.view",
  "users.manage", "virtualpos.recovery.view",
];

function setup(over: Partial<SidebarProps> = {}) {
  const fn = vi.fn();
  const props: SidebarProps = {
    activeSection: null, channel: null, tchView: null, openProvider: "TCH", theme: "light",
    onDashboard: fn, generalView: "summary", onGeneralClients: fn, onGeneralSubscriptions: fn,
    onAutoReport: fn, onChannel: fn, onSection: fn, onToggle: fn, onTheme: fn, onTch: fn,
    permissions: allPerms, onAdmin: fn, adminOpen: false, adminTab: null, onLogout: fn,
    onProfile: fn, open: false, onClose: fn, recoveryOpen: false, onRecovery: fn, profileOpen: false,
    ...over,
  };
  render(<Sidebar {...props} />);
  return props;
}
const active = () => Array.from(document.querySelectorAll(".sidebar-item.active")).map((n) => n.textContent);

afterEach(cleanup);

describe("Sidebar", () => {
  it("vista central marca Dashboard", () => {
    setup();
    expect(active()).toEqual(["Dashboard"]);
  });
  it("canal, admin, recuperador y perfil no marcan Dashboard", () => {
    setup({ channel: "toku" });
    expect(active()).not.toContain("Dashboard");
  });
  it("admin no marca Dashboard", () => {
    setup({ adminOpen: true, adminTab: "usuarios" });
    expect(active()).not.toContain("Dashboard");
  });
  it("recuperador no marca Dashboard", () => {
    setup({ recoveryOpen: true, openProvider: "VirtualPOS" });
    expect(active()).toEqual(["Recuperador de Socios"]);
  });
  it("perfil no marca Dashboard", () => {
    setup({ profileOpen: true });
    expect(active()).toEqual([]);
  });
  it("generalView clients marca solo Clientes", () => {
    setup({ generalView: "clients" });
    expect(active()).toEqual(["Clientes"]);
  });
  it("oculta Suscripciones y Transacciones TCH sin permiso", () => {
    setup({ permissions: ["tch.dashboard.view", "tch.clientes.view"] });
    expect(screen.queryByText("Suscripciones")).toBeNull();
    expect(screen.queryByText("Transacciones")).toBeNull();
    expect(screen.getByText("Clientes")).toBeInTheDocument();
  });
  it("muestra Suscripciones y Transacciones TCH con permiso", () => {
    setup({ permissions: ["tch.dashboard.view", "tch.suscripciones.view", "tch.transacciones.view"] });
    expect(screen.getByText("Suscripciones")).toBeInTheDocument();
    expect(screen.getByText("Transacciones")).toBeInTheDocument();
  });
  it("muestra puntos de salud con el nivel correcto", () => {
    setup({ health: {
      toku: { channel: "toku", level: "warn", last_finished_at: "x", age_hours: 30 },
      tch: { channel: "tch", level: "error", last_finished_at: null, age_hours: null },
      payku: { channel: "payku", level: "ok", last_finished_at: "x", age_hours: 2 },
    } });
    const dots = Array.from(document.querySelectorAll(".health-dot")).map((d) => d.getAttribute("data-level"));
    expect(dots.sort()).toEqual(["error", "ok", "warn"]);
    expect(screen.getByLabelText("Sincronizado: hace 2 h")).toHaveClass("ok");
  });
  it("sin datos de salud no hay puntos", () => {
    setup({ health: {} });
    expect(document.querySelector(".health-dot")).toBeNull();
  });
  it("Esc cierra el drawer abierto", () => {
    const props = setup({ open: true });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalled();
  });
});

describe("Sidebar como drawer modal (movil)", () => {
  function Harness({ initialOpen = false, onCloseSpy }: { initialOpen?: boolean; onCloseSpy?: () => void }) {
    const [open, setOpen] = useState(initialOpen);
    const noop = () => {};
    return (
      <div className="app-layout">
        <button className="burger-btn" aria-label="Abrir menu" onClick={() => setOpen(true)}>b</button>
        <Sidebar
          activeSection={null} channel={null} tchView={null} openProvider={null} theme="light" onDashboard={noop}
          generalView="summary" onGeneralClients={noop} onGeneralSubscriptions={noop} onAutoReport={noop}
          onChannel={noop} onSection={noop} onToggle={noop} onTheme={noop} onTch={noop} permissions={allPerms}
          onAdmin={noop} adminOpen={false} adminTab={null} onLogout={noop} onProfile={noop} open={open}
          onClose={() => { onCloseSpy?.(); setOpen(false); }} recoveryOpen={false} onRecovery={noop}
        />
        <main data-testid="content">contenido</main>
      </div>
    );
  }

  it("cerrado: sin velo y el contenido no esta inert", () => {
    render(<Harness />);
    expect(document.querySelector(".sidebar-overlay")).toBeNull();
    expect(screen.getByTestId("content")).not.toHaveAttribute("inert");
  });

  it("abierto: hay velo, el contenido queda inert/aria-hidden y el foco entra al menu", () => {
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("Abrir menu"));
    expect(document.querySelector(".sidebar-overlay")).not.toBeNull();
    const content = screen.getByTestId("content");
    expect(content).toHaveAttribute("inert");
    expect(content).toHaveAttribute("aria-hidden", "true");
    expect(document.getElementById("app-sidebar")!.contains(document.activeElement)).toBe(true);
  });

  it("clic en el velo cierra, quita inert y devuelve el foco a la hamburguesa", () => {
    render(<Harness />);
    const burger = screen.getByLabelText("Abrir menu");
    burger.focus();
    fireEvent.click(burger);
    fireEvent.click(document.querySelector(".sidebar-overlay")!);
    expect(document.querySelector(".sidebar-overlay")).toBeNull();
    expect(screen.getByTestId("content")).not.toHaveAttribute("inert");
    expect(screen.getByTestId("content")).not.toHaveAttribute("aria-hidden");
    expect(document.activeElement).toBe(burger);
  });

  it("Escape cierra y devuelve el foco", () => {
    const spy = vi.fn();
    render(<Harness onCloseSpy={spy} />);
    const burger = screen.getByLabelText("Abrir menu");
    burger.focus();
    fireEvent.click(burger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(burger);
  });

  it("no pisa un inert o aria-hidden previo del contenido al cerrar", () => {
    render(<Harness />);
    screen.getByTestId("content").setAttribute("aria-hidden", "false");
    const burger = screen.getByLabelText("Abrir menu");
    fireEvent.click(burger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByTestId("content")).toHaveAttribute("aria-hidden", "false");
  });
});
