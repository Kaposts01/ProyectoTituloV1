import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { detailChannels, menuGroups } from "../navigation";
import { HOVER_CLOSE_MS, HOVER_OPEN_MS, SIDEBAR_PINNED_KEY, Sidebar, type SidebarProps } from "./Sidebar";
import { MENU_ICONS } from "./sidebarIconMap";

const allPerms = [
  "dashboard.view", "virtualpos.clients.view", "toku.customers.view", "payku.clients.view",
  "tch.dashboard.view", "tch.clientes.view", "tch.suscripciones.view", "tch.transacciones.view",
  "users.manage", "sync_runs.view", "virtualpos.recovery.view", "virtualpos.billing_changes.view",
  "subscriptions.cancellation.view",
];

function setup(over: Partial<SidebarProps> = {}) {
  const fn = vi.fn();
  const props: SidebarProps = {
    activeSection: null, channel: null, tchView: null, detailOpen: false, onToggleDetail: fn, theme: "light",
    onDashboard: fn, generalView: "summary", onGeneralClients: fn, onGeneralSubscriptions: fn, onGeneralCharges: fn,
    onAutoReport: fn, onChannel: fn, onSection: fn, onTheme: fn, onTch: fn,
    permissions: allPerms, onAdmin: fn, adminOpen: false, adminTab: null, onLogout: fn,
    onProfile: fn, open: false, onClose: fn, recoveryOpen: false, onRecovery: fn, profileOpen: false,
    onBilling: fn, onCancellations: fn,
    ...over,
  };
  const view = render(<Sidebar {...props} />);
  return { props, view };
}
const aside = () => document.getElementById("app-sidebar")!;
const state = () => aside().getAttribute("data-state");
const panel = () => aside().querySelector(".sidebar-panel")!;
const account = () => screen.getByRole("button", { name: "Opciones de cuenta" });
const openAccount = () => { if (!screen.queryByRole("menu")) fireEvent.click(account()); };
const pin = () => { openAccount(); return screen.getByRole("menuitemcheckbox", { name: "Mantener menú abierto" }); };

function mockReducedMotion(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matches && query.includes("prefers-reduced-motion"),
    media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  window.localStorage.clear();
  mockReducedMotion(false);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Sidebar rail: compacto, expandir y fijar", () => {
  it("arranca compacto (64 px de íconos) y sin fijar", () => {
    setup();
    expect(state()).toBe("compact");
    expect(aside()).not.toHaveClass("is-pinned");
    expect(pin()).toHaveAttribute("aria-checked", "false");
  });

  it("el hover despliega tras la pausa de intención y se repliega al salir", () => {
    vi.useFakeTimers();
    setup();
    fireEvent.pointerEnter(panel());
    act(() => { vi.advanceTimersByTime(HOVER_OPEN_MS - 10); });
    expect(state()).toBe("compact");
    act(() => { vi.advanceTimersByTime(20); });
    expect(state()).toBe("expanded");
    fireEvent.pointerLeave(panel());
    act(() => { vi.advanceTimersByTime(HOVER_CLOSE_MS + 10); });
    expect(state()).toBe("compact");
  });

  it("cruzar el menú rápido con el puntero no lo despliega", () => {
    vi.useFakeTimers();
    setup();
    fireEvent.pointerEnter(panel());
    act(() => { vi.advanceTimersByTime(60); });
    fireEvent.pointerLeave(panel());
    act(() => { vi.advanceTimersByTime(HOVER_OPEN_MS + HOVER_CLOSE_MS); });
    expect(state()).toBe("compact");
  });

  it("«Mantener menú abierto» fija el menú, lo recuerda en localStorage y se puede soltar", () => {
    setup();
    fireEvent.click(pin());
    expect(pin()).toHaveAttribute("aria-checked", "true");
    expect(state()).toBe("expanded");
    expect(aside()).toHaveClass("is-pinned");
    expect(window.localStorage.getItem(SIDEBAR_PINNED_KEY)).toBe("1");
    cleanup();
    setup();
    expect(state()).toBe("expanded");
    fireEvent.click(pin());
    expect(state()).toBe("compact");
    expect(window.localStorage.getItem(SIDEBAR_PINNED_KEY)).toBe("0");
  });

  it("sin acceso a localStorage (modo privado) el menú funciona y se puede fijar en la pestaña", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("bloqueado"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
    setup();
    expect(state()).toBe("compact");
    fireEvent.click(pin());
    expect(state()).toBe("expanded");
  });
});

describe("Sidebar rail: movimiento reducido", () => {
  it("con prefers-reduced-motion marca data-motion=reduced (el CSS quita transiciones)", () => {
    mockReducedMotion(true);
    setup();
    expect(aside()).toHaveAttribute("data-motion", "reduced");
  });
  it("sin la preferencia, data-motion=full", () => {
    setup();
    expect(aside()).toHaveAttribute("data-motion", "full");
  });
  it("sin matchMedia (navegador viejo) no falla", () => {
    // @ts-expect-error simulación de entorno sin matchMedia
    window.matchMedia = undefined;
    setup();
    expect(aside()).toHaveAttribute("data-motion", "full");
  });
});

describe("Sidebar rail: submenú «Detalle por canal»", () => {
  it("el botón anuncia aria-expanded, gira su chevron por estado y en compacto despliega el rail", () => {
    const onToggleDetail = vi.fn();
    setup({ onToggleDetail });
    const toggle = screen.getByRole("button", { name: /Detalle por canal/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.querySelector('[data-icon="chevron"]')).not.toBeNull();
    fireEvent.click(toggle);
    expect(onToggleDetail).toHaveBeenCalledTimes(1);
    expect(state()).toBe("expanded");
  });
  it("despliega un proveedor por vez y conserva todas sus pantallas permitidas", () => {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, "1");
    setup({ detailOpen: true });
    const toggle = screen.getByRole("button", { name: /Detalle por canal/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    let previous: HTMLElement | null = null;
    for (const channel of detailChannels((p) => allPerms.includes(p))) {
      const group = screen.getByRole("group", { name: channel.name });
      const header = within(group).getByRole("button", { name: channel.name });
      fireEvent.click(header);
      expect(header).toHaveAttribute("aria-expanded", "true");
      if (previous) expect(previous).toHaveAttribute("aria-expanded", "false");
      for (const item of channel.items) expect(within(group).getByRole("button", { name: item.label })).toBeInTheDocument();
      previous = header;
    }
  });

  it("si la pantalla activa está dentro del detalle, el botón lo indica aun plegado", () => {
    setup({ channel: "toku" });
    expect(screen.getByRole("button", { name: /Detalle por canal/ })).toHaveClass("has-active");
  });
});

describe("Sidebar rail: entradas, íconos, tooltips y teclado", () => {
  it("no se pierde ninguna entrada: todas las de menuGroups aparecen, en orden, cada una con su ícono", () => {
    setup();
    const ids = menuGroups.flatMap((g) => g.items.map((i) => i.id));
    for (const id of ids) expect(MENU_ICONS[id], `sin ícono: ${id}`).toBeDefined();
    const rendered = Array.from(document.querySelectorAll<HTMLElement>(".sidebar-nav [data-item]"));
    expect(rendered.map((n) => n.dataset.item)).toEqual(ids);
    for (const node of rendered) expect(node.querySelector(`svg[data-icon="${MENU_ICONS[node.dataset.item!]}"]`)).not.toBeNull();
    expect(new Set(Object.values(MENU_ICONS)).size).toBe(ids.length);
  });

  it("los encabezados Cartera, Operación y Sistema siguen en el DOM (en compacto los oculta el CSS)", () => {
    setup();
    expect(Array.from(document.querySelectorAll(".sidebar-nav > .sidebar-group:not(.sidebar-detail) .sidebar-section-toggle")).map((n) => n.textContent)).toEqual(["Cartera", "Operación", "Sistema"]);
  });

  it("en compacto, el foco de teclado en un ítem muestra un tooltip con su nombre", () => {
    setup();
    act(() => { screen.getByRole("button", { name: "Cartera" }).focus(); });
    expect(document.querySelector(".sidebar-tooltip")).toHaveTextContent("Cartera");
    act(() => { screen.getByRole("button", { name: "Operación" }).focus(); });
    expect(document.querySelector(".sidebar-tooltip")).toHaveTextContent("Operación");
  });

  it("desplegado no hay tooltip (el nombre ya se ve)", () => {
    setup();
    fireEvent.click(pin());
    fireEvent.click(screen.getByRole("button", { name: "Cartera" }));
    act(() => { screen.getByRole("button", { name: "Socios" }).focus(); });
    expect(document.querySelector(".sidebar-tooltip")).toBeNull();
  });

  it("enfocar el buscador despliega el rail; Escape lo vuelve a compactar", () => {
    setup();
    act(() => { screen.getByLabelText("Buscar en el menú").focus(); });
    expect(state()).toBe("expanded");
    fireEvent.keyDown(screen.getByLabelText("Buscar en el menú"), { key: "Escape" });
    expect(state()).toBe("compact");
  });

  it("el ítem activo mantiene aria-current=page y los íconos son decorativos", () => {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, "1");
    setup({ generalView: "clients" });
    const item = screen.getByRole("button", { name: "Socios" });
    expect(item).toHaveAttribute("aria-current", "page");
    expect(item.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("los textos fijos salen del catálogo es.ts", () => {
    setup();
    expect(screen.getByRole("navigation", { name: "Navegación principal" })).toBeInTheDocument();
    openAccount();
    expect(screen.getByRole("menuitem", { name: "Cambiar tema" })).toHaveTextContent("Modo oscuro");
    expect(screen.getByRole("menuitem", { name: "Cerrar sesión" })).toBeInTheDocument();
  });

  it("como drawer móvil abierto se muestra desplegado", () => {
    setup({ open: true });
    expect(state()).toBe("expanded");
  });
});

describe("Sidebar account popup", () => {
  it("only shows the account trigger until it is pressed", () => {
    setup({ username: "operador.sintetico" });
    expect(account()).toHaveAttribute("aria-expanded", "false");
    expect(account()).toHaveTextContent("OS");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Mi perfil" })).not.toBeInTheDocument();
    expect(document.querySelector(".sidebar-footer")?.querySelectorAll("button")).toHaveLength(1);
  });

  it("opens exactly the four requested actions and focuses the first", () => {
    setup();
    fireEvent.click(account());
    const menu = screen.getByRole("menu", { name: "Opciones de cuenta" });
    expect(menu.querySelectorAll("button")).toHaveLength(4);
    expect(account()).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(pin());
  });

  it("supports arrows, Home/End and Escape without closing the mobile drawer", () => {
    const onClose = vi.fn();
    setup({ open: true, onClose });
    fireEvent.keyDown(account(), { key: "ArrowDown" });
    const menu = screen.getByRole("menu");
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Cerrar sesión" }));
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(pin());
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Cambiar tema" }));
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Cerrar sesión" }));
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(account());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on an outside pointer without stealing its focus", () => {
    setup();
    fireEvent.click(account());
    const outside = document.createElement("button");
    document.body.append(outside);
    try {
      outside.focus();
      fireEvent.pointerDown(outside);
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
      expect(document.activeElement).toBe(outside);
    } finally { outside.remove(); }
  });

  it.each(["theme", "profile", "logout"])("selecting %s runs its action once and closes", (action) => {
    const callback = vi.fn();
    setup(action === "theme" ? { onTheme: callback } : action === "profile" ? { onProfile: callback } : { onLogout: callback });
    fireEvent.click(account());
    fireEvent.click(screen.getByRole("menuitem", { name: action === "theme" ? "Cambiar tema" : action === "profile" ? "Mi perfil" : "Cerrar sesión" }));
    expect(callback).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("Tab dismisses the popup and returns focus to the trigger", () => {
    setup();
    fireEvent.click(account());
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Tab" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(account());
  });
});

describe("Sidebar section accordions", () => {
  const section = (id: string) => document.querySelector<HTMLButtonElement>(`[data-section="${id}"]`)!;
  const expandedSetup = (props: Partial<SidebarProps> = {}) => {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, "1");
    return setup(props);
  };

  it("starts with summary and collapsed section headers", () => {
    expandedSetup();
    for (const id of ["cartera", "operacion", "sistema", "detail"]) expect(section(id)).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Socios" })).not.toBeInTheDocument();
  });

  it("opens one main section at a time and allows closing it", () => {
    expandedSetup();
    fireEvent.click(section("cartera"));
    expect(screen.getByRole("button", { name: "Socios" })).toBeVisible();
    fireEvent.click(section("operacion"));
    expect(section("cartera")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Socios" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recuperador" })).toBeVisible();
    fireEvent.click(section("operacion"));
    expect(section("operacion")).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the current screen section after navigation without forcing manually closed sections", () => {
    const { props, view } = expandedSetup({ generalView: "clients" });
    expect(section("cartera")).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(section("cartera"));
    view.rerender(<Sidebar {...props} />);
    expect(section("cartera")).toHaveAttribute("aria-expanded", "false");
    view.rerender(<Sidebar {...props} generalView="report" />);
    expect(section("sistema")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Reportes" })).toHaveAttribute("aria-current", "page");
  });

  it("search opens matching branches and restores the prior section when cleared", () => {
    expandedSetup();
    fireEvent.click(section("operacion"));
    const search = screen.getByRole("searchbox", { name: "Buscar en el menú" });
    fireEvent.change(search, { target: { value: "suscripciones" } });
    expect(section("cartera")).toHaveAttribute("aria-expanded", "true");
    expect(section("cartera")).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Suscripciones" }).length).toBeGreaterThan(1);
    fireEvent.change(search, { target: { value: "" } });
    expect(section("operacion")).toHaveAttribute("aria-expanded", "true");
    expect(section("cartera")).toHaveAttribute("aria-expanded", "false");
  });

  it("opens current provider, keeps permissions and collapses only one level with Left", () => {
    expandedSetup({ tchView: "transactions" });
    expect(section("detail")).toHaveAttribute("aria-expanded", "true");
    expect(section("channel:tch")).toHaveAttribute("aria-expanded", "true");
    const item = within(screen.getByRole("group", { name: "TCH" })).getByRole("button", { name: "Transacciones" });
    item.focus();
    fireEvent.keyDown(item, { key: "ArrowLeft" });
    expect(section("channel:tch")).toHaveAttribute("aria-expanded", "false");
    expect(section("detail")).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(section("channel:tch"));
    fireEvent.keyDown(section("channel:tch"), { key: "ArrowRight" });
    expect(section("channel:tch")).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("button", { name: "Planes" })).not.toBeInTheDocument();
  });

  it("a compact section click reveals its labels and children", () => {
    setup({ generalView: "clients" });
    expect(section("cartera")).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(section("cartera"));
    expect(state()).toBe("expanded");
    expect(section("cartera")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Socios" })).toBeVisible();
  });

  it("profile does not leave a stale central section selected", () => {
    expandedSetup({ generalView: "clients", profileOpen: true });
    expect(document.querySelector('.sidebar-nav .sidebar-item[aria-current="page"]')).toBeNull();
  });
});
