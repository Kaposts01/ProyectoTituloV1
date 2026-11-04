/** Cobros unificados (UX-09, /central/cobros): tabla multicanal, filtros, rechazo y Exportar. Datos sintéticos. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import "./UnifiedChargesView";
import { appReady, mountApp, resetApp, type Handler } from "../../test/appHarness";

afterEach(resetApp);

const chargesPage = {
  items: [
    { channel: "virtualpos1", charge_id: "C-1", subscription_id: "S-1", status: "rechazado", charge_date: "2026-10-03", period: null, amount: "1000", currency: "CLP", rejection_reason: null, rut: "11111111-1", name: "Socio Sintético" },
    { channel: "tch", charge_id: "77", subscription_id: "900", status: "RECHAZADA", charge_date: "2026-10-04", period: "2026-10", amount: "5000", currency: "CLP", rejection_reason: "Sin fondos", rut: null, name: null },
  ],
  total: 120, offset: 0, limit: 50, by_channel: { virtualpos: 100, toku: 0, tch: 20 }, canales: ["virtualpos1", "virtualpos2", "toku", "tch"],
};
const summary = {
  today: "2026-11-02",
  channels: [
    { channel: "virtualpos", label: "VirtualPOS", basis: "cargos", basis_label: "", paid: 90, rejected: 10, evaluable: 100, rate: 10 },
    { channel: "toku", label: "Toku", basis: "transacciones", basis_label: "", paid: 0, rejected: 0, evaluable: 0, rate: null },
  ],
  total: { paid: 90, rejected: 10, evaluable: 100, rate: 10 },
};
const handlers: Handler[] = [
  ["GET", "/api/v1/general/charges", chargesPage],
  ["GET", "/api/v1/general/charges/statuses", { statuses: [{ status: "rechazado", count: 10 }, { status: "RECHAZADA", count: 20 }], canales: chargesPage.canales }],
  ["GET", "/api/v1/general/charges/summary", summary],
  ["GET", "/api/v1/general/payments", { ...chargesPage, items: [], total: 0, by_channel: {} }],
  ["GET", "/api/v1/general/payments/statuses", { statuses: [], canales: [] }],
  ["GET", "/api/v1/export/cobros/count", { entity: "cobros", rows: 7, canales: [], include_pii: false }],
];

describe("Cobros unificados", () => {
  it("lista cobros de varios canales con la tasa de rechazo única y enlaza a la ficha por canal", async () => {
    const app = mountApp("/central/cobros", handlers);
    await appReady();
    expect(await screen.findByRole("heading", { name: "Cobros" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "C-1" })).toBeTruthy();
    const table = screen.getByRole("button", { name: "C-1" }).closest("table") as HTMLElement;
    expect(within(table).getByText("TCH")).toBeTruthy();
    expect(within(table).getByText("Sin fondos")).toBeTruthy();
    expect(within(table).getByText("Rechazado")).toBeTruthy();
    const rejection = screen.getByRole("region", { name: "Rechazo por canal" });
    expect(within(rejection).getByText("10,0 %", { selector: "h3 .mono" })).toBeTruthy();
    const first = app.exact("GET", "/api/v1/general/charges")[0];
    expect(Object.fromEntries(first.query)).toEqual({ offset: "0", limit: "50" });
    // el menú marca Cobros dentro de Cartera
    expect(screen.getByRole("button", { name: "Cobros" })).toHaveAttribute("aria-current", "page");
  });

  it("los filtros de canal, estado y resultado viajan a la API y al Exportar", async () => {
    const app = mountApp("/central/cobros", handlers);
    await appReady();
    await screen.findByRole("button", { name: "C-1" });
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "tch" } });
    await screen.findByRole("option", { name: "Rechazada (20)" });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "RECHAZADA" } });
    fireEvent.change(screen.getByLabelText("Resultado"), { target: { value: "rejected" } });
    await waitFor(() => {
      const last = app.exact("GET", "/api/v1/general/charges").at(-1)!;
      expect(Object.fromEntries(last.query)).toEqual({ canal: "tch", status: "RECHAZADA", outcome: "rejected", offset: "0", limit: "50" });
    });
    fireEvent.click(screen.getByRole("button", { name: /Exportar/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    await screen.findByText("7 filas");
    const count = app.exact("GET", "/api/v1/export/cobros/count").at(-1)!;
    expect(Object.fromEntries(count.query)).toEqual({ status: "RECHAZADA", outcome: "rejected", canal: "tch" });
  });

  it("d143: los filtros activos se ven como chips; «×» quita uno y «Limpiar filtros» los quita todos", async () => {
    const app = mountApp("/central/cobros", handlers);
    await appReady();
    await screen.findByRole("button", { name: "C-1" });
    expect(document.querySelector(".filter-count")?.textContent).toBe("120 cobros");
    expect(screen.queryByRole("button", { name: "Limpiar filtros" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "tch" } });
    fireEvent.change(screen.getByLabelText("Resultado"), { target: { value: "rejected" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-10-01" } });
    const chips = screen.getByRole("list", { name: "Filtros activos" });
    expect(within(chips).getByText("Canal: TCH")).toBeTruthy();
    expect(within(chips).getByText("Desde: 2026-10-01")).toBeTruthy();
    // quitar un filtro
    fireEvent.click(screen.getByRole("button", { name: "Quitar filtro Canal: TCH" }));
    expect((screen.getByLabelText("Canal") as HTMLSelectElement).value).toBe("");
    expect(within(screen.getByRole("list", { name: "Filtros activos" })).queryByText("Canal: TCH")).toBeNull();
    await waitFor(() => {
      const last = app.exact("GET", "/api/v1/general/charges").at(-1)!;
      expect(Object.fromEntries(last.query)).toEqual({ outcome: "rejected", date_from: "2026-10-01", offset: "0", limit: "50" });
    });
    // limpiar todos
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    expect(screen.queryByRole("list", { name: "Filtros activos" })).toBeNull();
    expect((screen.getByLabelText("Resultado") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Desde") as HTMLInputElement).value).toBe("");
    await waitFor(() => {
      const last = app.exact("GET", "/api/v1/general/charges").at(-1)!;
      expect(Object.fromEntries(last.query)).toEqual({ offset: "0", limit: "50" });
    });
  });

  it("paginación en el servidor: Siguiente pide el offset 50", async () => {
    const app = mountApp("/central/cobros", handlers);
    await appReady();
    await screen.findByRole("button", { name: "C-1" });
    fireEvent.click(screen.getByRole("button", { name: "Siguiente →" }));
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/charges").at(-1)?.query.get("offset")).toBe("50"));
  });

  it("sin permisos de cobros ni pagos la ruta no se abre y el menú no la ofrece", async () => {
    mountApp("/central/cobros", handlers, { permissions: ["dashboard.view"] });
    await appReady();
    await waitFor(() => expect(window.location.pathname).toBe("/central/resumen"));
    expect(screen.queryByRole("button", { name: "Cobros" })).toBeNull();
  });

  it("con solo permiso de pagos abre la pestaña Pagos", async () => {
    const app = mountApp("/central/cobros", handlers, { permissions: ["toku.transactions.view"] });
    await appReady();
    expect(await screen.findByRole("tab", { name: "Pagos" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Cobros" })).toBeNull();
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/payments").length).toBeGreaterThan(0));
    expect(app.exact("GET", "/api/v1/general/charges/summary")).toHaveLength(0);
  });
});
