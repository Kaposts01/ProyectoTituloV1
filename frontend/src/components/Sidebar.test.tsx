import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar, type SidebarProps } from "./Sidebar";

const allPerms = [
  "dashboard.view", "virtualpos.clients.view", "toku.customers.view", "payku.clients.view",
  "tch.dashboard.view", "tch.clientes.view", "tch.suscripciones.view", "tch.transacciones.view",
  "users.manage", "sync_runs.view", "virtualpos.recovery.view", "virtualpos.billing_changes.view",
];

function setup(over: Partial<SidebarProps> = {}) {
  const fn = vi.fn();
  const props: SidebarProps = {
    activeSection: null, channel: null, tchView: null, detailOpen: false, onToggleDetail: fn, theme: "light",
    onDashboard: fn, generalView: "summary", onGeneralClients: fn, onGeneralSubscriptions: fn,
    onAutoReport: fn, onChannel: fn, onSection: fn, onTheme: fn, onTch: fn,
    permissions: allPerms, onAdmin: fn, adminOpen: false, adminTab: null, onLogout: fn,
    onProfile: fn, open: false, onClose: fn, recoveryOpen: false, onRecovery: fn, profileOpen: false, onBilling: fn,
    ...over,
  };
  render(<Sidebar {...props} />);
  return props;
}
const active = () => Array.from(document.querySelectorAll(".sidebar-item.active")).map((n) => n.textContent);
const tchGroup = () => screen.getByRole("group", { name: "TCH" });

afterEach(cleanup);

describe("Sidebar (menú de un solo nivel)", () => {
  // Cambio deliberado: antes el ítem se llamaba «Dashboard».
  it("vista central marca Resumen", () => {
    setup();
    expect(active()).toEqual(["Resumen"]);
  });
  it("canal no marca Resumen", () => {
    setup({ channel: "toku" });
    expect(active()).not.toContain("Resumen");
  });
  it("admin marca solo Administración y no Resumen", () => {
    setup({ adminOpen: true, adminTab: "users" });
    expect(active()).toEqual(["Administración"]);
  });
  it("sincronización marca solo Sincronización", () => {
    setup({ adminOpen: true, adminTab: "sync" });
    expect(active()).toEqual(["Sincronización"]);
  });
  // Cambio deliberado: el recuperador ya no cuelga del grupo VirtualPOS; se llama «Recuperador» y vive en Operación.
  it("recuperador marca «Recuperador»", () => {
    setup({ recoveryOpen: true });
    expect(active()).toEqual(["Recuperador"]);
  });
  it("perfil no marca ningún ítem", () => {
    setup({ profileOpen: true });
    expect(active()).toEqual([]);
  });
  // Cambio deliberado: «Clientes» pasa a «Socios»; «Reporte automático» a «Reportes».
  it("generalView clients marca solo Socios; report marca Reportes", () => {
    setup({ generalView: "clients" });
    expect(active()).toEqual(["Socios"]);
    cleanup();
    setup({ generalView: "report" });
    expect(active()).toEqual(["Reportes"]);
  });
  it("los títulos de grupo (Cartera, Operación, Sistema) se pintan como encabezado de su grupo", () => {
    setup();
    for (const name of ["Cartera", "Operación", "Sistema"]) {
      const label = within(screen.getByRole("group", { name })).getByText(name);
      expect(label.className).toBe("sidebar-section-label");
    }
  });
  it("el ítem activo lleva aria-current=page", () => {
    setup({ generalView: "subscriptions" });
    expect(screen.getByRole("button", { name: "Suscripciones" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Socios" })).not.toHaveAttribute("aria-current");
  });
  // Cambio deliberado: las pantallas de TCH viven ahora en «Detalle por canal» (plegado y transitorio).
  it("oculta Suscripciones y Transacciones TCH sin permiso", () => {
    setup({ detailOpen: true, permissions: ["tch.dashboard.view", "tch.clientes.view"] });
    expect(within(tchGroup()).queryByText("Suscripciones")).toBeNull();
    expect(within(tchGroup()).queryByText("Transacciones")).toBeNull();
    expect(within(tchGroup()).getByText("Clientes")).toBeInTheDocument();
  });
  it("muestra Suscripciones y Transacciones TCH con permiso", () => {
    setup({ detailOpen: true, permissions: ["tch.dashboard.view", "tch.suscripciones.view", "tch.transacciones.view"] });
    expect(within(tchGroup()).getByText("Suscripciones")).toBeInTheDocument();
    expect(within(tchGroup()).getByText("Transacciones")).toBeInTheDocument();
  });
  it("las fichas de TCH marcan su lista en «Detalle por canal»", () => {
    setup({ detailOpen: true, tchView: "subscription-detail" });
    expect(within(tchGroup()).getByRole("button", { name: "Suscripciones" })).toHaveAttribute("aria-current", "page");
  });
  it("«Detalle por canal» arranca plegado y su botón anuncia aria-expanded y el estado transitorio", () => {
    const onToggleDetail = vi.fn();
    setup({ onToggleDetail });
    const toggle = screen.getByRole("button", { name: /Detalle por canal/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.textContent).toContain("Transitorio");
    expect(screen.queryByRole("group", { name: "TCH" })).toBeNull();
    fireEvent.click(toggle);
    expect(onToggleDetail).toHaveBeenCalledTimes(1);
  });
  it("desplegado, muestra el aviso de retirada y marca el ítem de canal activo", () => {
    setup({ detailOpen: true, channel: "toku" });
    expect(screen.getByText(/Se retira cuando existan las vistas unificadas/)).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Toku" })).getByRole("button", { name: "Resumen" })).toHaveAttribute("aria-current", "page");
  });
  it("sin datos de salud no hay indicador", () => {
    setup({ health: {} });
    expect(document.querySelector(".health-dot")).toBeNull();
    expect(document.querySelector(".sidebar-health")).toBeNull();
  });
  // Cambio deliberado: antes un punto por canal junto a cada grupo; ahora un indicador global (el peor nivel) en el
  // encabezado y el detalle por canal al abrirlo.
  it("indicador global: toma el peor nivel y el detalle por canal aparece al abrirlo", () => {
    setup({ health: {
      toku: { channel: "toku", level: "warn", last_finished_at: "x", age_hours: 30 },
      tch: { channel: "tch", level: "error", last_finished_at: null, age_hours: null },
      payku: { channel: "payku", level: "ok", last_finished_at: "x", age_hours: 2 },
    } });
    const global = document.querySelector('.health-dot[data-scope="global"]');
    expect(global?.getAttribute("data-level")).toBe("error");
    const toggle = screen.getByRole("button", { name: /Sincronización con fallos/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Al día · hace 2 h")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Sincronización por canal" });
    expect(within(list).getByText("Al día · hace 2 h")).toBeInTheDocument();
    expect(within(list).getByText("Atrasada · hace 30 h")).toBeInTheDocument();
    expect(within(list).getAllByText("Falló")).toHaveLength(1);
    expect(within(list).getAllByRole("listitem").map((li) => li.querySelector("[data-level]")?.getAttribute("data-level"))).toEqual(["warn", "ok", "error"]);
  });
  it("todos los canales ok: indicador «Todo al día»", () => {
    setup({ health: { toku: { channel: "toku", level: "ok", last_finished_at: "x", age_hours: 1 } } });
    expect(screen.getByRole("button", { name: /Todo al día/ })).toBeInTheDocument();
  });
  it("Esc cierra el drawer abierto", () => {
    const props = setup({ open: true });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalled();
  });
});

describe("Sidebar: buscador del menú", () => {
  const search = (text: string) => fireEvent.change(screen.getByLabelText("Buscar en el menú"), { target: { value: text } });
  const labels = () => Array.from(document.querySelectorAll(".sidebar-nav .sidebar-item")).map((n) => n.textContent);
  it("filtra por rótulo sin distinguir tildes ni mayúsculas y oculta los grupos vacíos", () => {
    setup();
    search("ADMINISTRACION");
    expect(labels()).toEqual(["Administración"]);
    expect(screen.queryByText("Cartera")).toBeNull();
  });
  it("buscar un grupo muestra sus ítems", () => {
    setup();
    search("operacion");
    expect(labels()).toEqual(["Recuperador", "Cambios de cobro"]);
  });
  it("las coincidencias del detalle por canal se muestran aunque esté plegado", () => {
    setup();
    search("payku");
    expect(labels()).toEqual(["Resumen", "Clientes"]);
    expect(screen.getByRole("group", { name: "Payku" })).toBeInTheDocument();
  });
  it("sin coincidencias avisa", () => {
    setup();
    search("zzz");
    expect(screen.getByRole("status")).toHaveTextContent("Sin resultados");
  });
  it("elegir un resultado navega y cierra el menú móvil", () => {
    const onGeneralClients = vi.fn();
    const onClose = vi.fn();
    setup({ open: true, onGeneralClients, onClose });
    search("socios");
    fireEvent.click(screen.getByRole("button", { name: "Socios" }));
    expect(onGeneralClients).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
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
          activeSection={null} channel={null} tchView={null} detailOpen={false} onToggleDetail={noop} theme="light" onDashboard={noop}
          generalView="summary" onGeneralClients={noop} onGeneralSubscriptions={noop} onAutoReport={noop}
          onChannel={noop} onSection={noop} onTheme={noop} onTch={noop} permissions={allPerms}
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
