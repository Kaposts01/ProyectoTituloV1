/// <reference types="node" />
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { OperationalAlerts } from "./OperationalAlerts";
import type { Alert } from "./alertTypes";

afterEach(cleanup);

const mk = (n: number, over: Partial<Alert> = {}): Alert[] =>
  Array.from({ length: n }, (_, i) => ({ severity: "media" as const, kind: `Tipo ${String(i).padStart(2, "0")}`, channel: "Toku", detail: `${i + 1} cargos`, ...over }));

const groupsOf = () => screen.getAllByTestId("alert-group");

describe("OperationalAlerts", () => {
  it("sin alertas muestra el mensaje de todo en orden", () => {
    render(<OperationalAlerts alerts={[]} />);
    expect(screen.getByText(/Sin alertas operativas/)).toBeInTheDocument();
  });

  it("muestra solo los 5 peores grupos y el botón 'Ver todas (N)' colapsado", () => {
    render(<OperationalAlerts alerts={mk(12)} />);
    expect(groupsOf()).toHaveLength(5);
    const btn = screen.getByRole("button", { name: "Ver todas (12)" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    // el peor (mayor valor numérico) va primero
    expect(within(groupsOf()[0]).getByText("Tipo 11")).toBeInTheDocument();
  });

  it("sin más de 5 grupos no hay botón", () => {
    render(<OperationalAlerts alerts={mk(5)} />);
    expect(screen.queryByRole("button", { name: /Ver todas/ })).not.toBeInTheDocument();
  });

  it("expande y colapsa con aria-expanded, mueve el foco al primer grupo nuevo y lo devuelve al botón", () => {
    render(<OperationalAlerts alerts={mk(8)} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver todas (8)" }));
    expect(groupsOf()).toHaveLength(8);
    const less = screen.getByRole("button", { name: "Ver menos" });
    expect(less).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(groupsOf()[5]);
    fireEvent.click(less);
    expect(groupsOf()).toHaveLength(5);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Ver todas (8)" }));
  });

  it("titula 'N alertas en M grupos' (singular correcto)", () => {
    const { unmount } = render(<OperationalAlerts alerts={[...mk(3), ...mk(2, { kind: "Tipo 00" })]} />);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("5 alertas en 3 grupos");
    unmount();
    render(<OperationalAlerts alerts={mk(1)} />);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("1 alerta en 1 grupo");
  });

  it("agrupa periodos: 'N periodos' se expande para ver las filas con su periodo", () => {
    const alerts = [1, 2, 3].map((m) => ({ severity: "alta" as const, kind: "Rechazo alto", channel: "VirtualPOS", detail: `${m * 10}% de rechazo`, period: `2026-0${m}` }));
    render(<OperationalAlerts alerts={alerts} />);
    expect(groupsOf()).toHaveLength(1);
    const toggle = screen.getByRole("button", { name: /3 periodos/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("2026-01")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("2026-01")).toBeInTheDocument();
    expect(screen.getByText("2026-03")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByText("2026-01")).not.toBeInTheDocument();
  });

  it("toda fila lleva texto de severidad (no solo color) y usa lista semántica", () => {
    render(<OperationalAlerts alerts={[{ severity: "alta", kind: "T1", channel: "A", detail: "1" }, { severity: "baja", kind: "T2", channel: "B", detail: "1" }, { severity: "media", kind: "T3", channel: "C", detail: "1" }]} />);
    const list = screen.getByRole("list", { name: "Alertas operativas" });
    for (const g of within(list).getAllByTestId("alert-group")) {
      expect(within(g).getByText(/^(Alta|Media|Baja)$/)).toBeInTheDocument();
    }
  });

  it("forma vieja (sin periodo ni id) y nueva (con periodo) conviven", () => {
    render(<OperationalAlerts alerts={[{ severity: "media", kind: "Viejo", channel: "Toku", detail: "2 cargos" }, { severity: "media", kind: "Nuevo", channel: "Toku", detail: "1 cargo", period: "2026-05" }]} />);
    expect(groupsOf()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /periodo/ })).not.toBeInTheDocument();
  });

  it("'Ver más' de una alerta con id sigue cargando el detalle", async () => {
    const loadDetail = vi.fn().mockResolvedValue([{ externalId: "S-1", rut: "1-9", status: "x", amount: 100, subscriptionDate: "2026-01-01" }]);
    render(<OperationalAlerts alerts={[{ id: "abc", severity: "alta", kind: "T", channel: "Toku", detail: "1" }]} loadDetail={loadDetail} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver más" }));
    await waitFor(() => expect(screen.getByText("S-1")).toBeInTheDocument());
    expect(loadDetail).toHaveBeenCalledWith("abc");
  });

  it("el CSS de filas de alerta no usa borde izquierdo de color (DESIGN.md)", () => {
    const rules = readFileSync("src/App.css", "utf8").split("}").filter((r) => /\.dashboard-alert/.test(r.split("{")[0]));
    expect(rules.length).toBeGreaterThan(0);
    for (const r of rules) expect(r).not.toMatch(/border-left/);
  });
});

describe("textos en español (paso 9)", () => {
  it("la severidad se escribe con mayúscula inicial y una desconocida cae a «Baja»", () => {
    render(<OperationalAlerts alerts={[{ severity: "alta", kind: "T1", channel: "A", detail: "1" }, { severity: "zz" as never, kind: "T2", channel: "B", detail: "1" }]} />);
    expect(screen.getAllByText("Alta").length).toBeGreaterThan(0);
    expect(screen.getByText("Baja")).toBeInTheDocument();
    expect(screen.queryByText("alta", { selector: ".alert-sev" })).toBeNull();
  });

  it("el detalle de una alerta traduce el estado y el estado del último cobro", async () => {
    const loadDetail = vi.fn().mockResolvedValue([{ externalId: "s1", rut: "11111111-1", status: "ACTIVE", amount: 1000, subscriptionDate: "2025-01-01", lastCharge: "2025-03-01", lastChargeStatus: "FAILED", attempts: 2 }]);
    render(<OperationalAlerts alerts={[{ id: "abc", severity: "alta", kind: "T", channel: "Toku", detail: "1" }]} loadDetail={loadDetail} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver más" }));
    expect(await screen.findByText("Activa")).toBeInTheDocument();
    expect(screen.getByText("Fallido")).toBeInTheDocument();
    expect(screen.queryByText("ACTIVE")).toBeNull();
  });
});
