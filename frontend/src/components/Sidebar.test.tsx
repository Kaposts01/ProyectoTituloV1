import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
