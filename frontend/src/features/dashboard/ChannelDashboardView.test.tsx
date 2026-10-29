import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelDashboardView } from "./ChannelDashboardView";
import { statusResourceLabels, tokuMetrics } from "../shared/constants";
import { providerGroups } from "../../navigation";
import type { ChannelDashboard } from "../shared/types";

afterEach(cleanup);

const empty = (source: string, over: Partial<ChannelDashboard> = {}): ChannelDashboard => ({
  source, records: 0, resources: {}, resource_amounts: {}, statuses: [], activity_resource: "transaction", activity: [], years: [], last_sync: null, ...over,
});

function view(data: ChannelDashboard, props: { syncUnavailable?: boolean; onSync?: () => void } = {}) {
  const onSync = props.onSync ?? vi.fn();
  render(
    <ChannelDashboardView data={data} mode="count" year={null} syncing={false} onMode={vi.fn()} onYear={vi.fn()}
      onOpenResource={vi.fn()} onReport={vi.fn()} onSync={onSync} syncUnavailable={props.syncUnavailable} />,
  );
  return { onSync };
}

const card = (heading: string) => screen.getByRole("heading", { name: heading }).closest("article")!;

describe("estados vacíos accionables", () => {
  it("Toku sin cobros: la tarjeta se encoge y ofrece sincronizar", () => {
    const { onSync } = view(empty("toku"));
    const c = card("Cobros mensuales (transacciones)");
    expect(c).toHaveClass("panel-compact");
    expect(within(c).getByText(/Sincroniza el canal para ver datos/)).toBeInTheDocument();
    fireEvent.click(within(c).getByRole("button", { name: /Sincronizar/ }));
    expect(onSync).toHaveBeenCalledWith("toku");
  });

  it("Estados de la operación vacío: tarjeta compacta con instrucción y acción", () => {
    view(empty("toku"));
    const c = card("Estados de la operación");
    expect(c).toHaveClass("panel-compact");
    expect(within(c).getByText(/Sincroniza el canal para ver datos/)).toBeInTheDocument();
  });

  it("Payku sin transacciones: mismo tratamiento", () => {
    view(empty("payku"));
    const c = card("Transacciones mensuales");
    expect(c).toHaveClass("panel-compact");
    expect(within(c).getByRole("button", { name: /Sincronizar/ })).toBeEnabled();
  });

  it("con datos la tarjeta de estados NO es compacta", () => {
    view(empty("toku", { statuses: [{ resource: "transaction", status: "SUCCESS", count: 2 }], resources: { transaction: 2 } }));
    expect(card("Estados de la operación")).not.toHaveClass("panel-compact");
  });

  it("sync deshabilitado: motivo visible, enlazado por aria-describedby, y sin botón en el estado vacío", () => {
    view(empty("payku"), { syncUnavailable: true });
    const hero = screen.getByRole("button", { name: /↻ Sincronizar/ });
    expect(hero).toBeDisabled();
    const reasonId = hero.getAttribute("aria-describedby");
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId!)).toHaveTextContent("Payku no está habilitado en este ambiente");
    const c = card("Transacciones mensuales");
    expect(within(c).getByText("Payku no está habilitado en este ambiente")).toBeVisible();
    expect(within(c).queryByRole("button", { name: /Sincronizar/ })).not.toBeInTheDocument();
  });

  it("sync habilitado: el botón principal no apunta a ningún motivo", () => {
    view(empty("toku"));
    expect(screen.getByRole("button", { name: /↻ Sincronizar/ })).not.toHaveAttribute("aria-describedby");
  });
});

describe("tildes en etiquetas", () => {
  it("'Métodos de pago' con tilde en métricas, recursos y navegación", () => {
    expect(tokuMetrics.find((m) => m.resource === "payment_method")?.label).toBe("Métodos de pago cobrables");
    expect(statusResourceLabels.payment_method).toBe("Métodos de pago");
    const toku = providerGroups.find((g) => g.sections[0].source === "toku")!;
    expect(toku.sections.find((s) => s.resource === "payment_method")?.label).toBe("Métodos de pago");
  });
  it("el aria-label de las métricas lleva tilde", () => {
    view(empty("toku"));
    expect(screen.getByRole("region", { name: "Métricas Toku" })).toBeInTheDocument();
  });
});
