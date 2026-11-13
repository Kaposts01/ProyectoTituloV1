/** Suscripciones unificadas (UX-08, /central/suscripciones): columna «Socio» (13C). Datos sintéticos. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import "./UnifiedSubscriptionsView";
import { appReady, mountApp, resetApp, type Handler } from "../../test/appHarness";

afterEach(resetApp);

const page = {
  items: [
    // VirtualPOS: el backend resuelve el nombre aunque la suscripción no traiga el ID del cliente
    { channel: "virtualpos1", subscription_id: "DEMO-VP-1", status: "ACTIVA", secondary_status: "cobrable", start_date: "2026-01-10", end_date: null, amount: "5000", currency: "CLP", last_charge: "2026-10-10", rut: "11111111-1", name: "DEMO Bruno Embebido" },
    // sin nombre en ninguna fuente: guion, el RUT se sigue mostrando
    { channel: "virtualpos1", subscription_id: "DEMO-VP-2", status: "ACTIVA", secondary_status: "Nunca Cobrado", start_date: "2026-01-11", end_date: null, amount: "5000", currency: "CLP", last_charge: null, rut: "22222222-2", name: null },
  ],
  total: 2, offset: 0, limit: 50, by_channel: { virtualpos: 2 }, canales: ["virtualpos1", "virtualpos2"],
};
const handlers: Handler[] = [
  ["GET", "/api/v1/general/subscriptions", page],
  ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [{ status: "ACTIVA", count: 2 }], canales: page.canales }],
];

describe("Suscripciones unificadas: nombre del socio", () => {
  it("muestra el nombre del socio de VirtualPOS junto al RUT y un guion si no hay nombre", async () => {
    mountApp("/central/suscripciones", handlers);
    await appReady();
    const cell = await screen.findByText("DEMO Bruno Embebido");
    const row = cell.closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Ver socio 11.111.111-1" })).toBeTruthy();
    const second = screen.getByRole("button", { name: "DEMO-VP-2" }).closest("tr") as HTMLElement;
    const cells = within(second).getAllByRole("cell");
    expect(cells[2].textContent).toBe("—");
    expect(within(second).getByRole("button", { name: "Ver socio 22.222.222-2" })).toBeTruthy();
  });

  it("el filtro por «Socio» viaja a la API como filter_field=client", async () => {
    const app = mountApp("/central/suscripciones", handlers);
    await appReady();
    await screen.findByText("DEMO Bruno Embebido");
    fireEvent.change(screen.getByLabelText("Buscar en"), { target: { value: "client" } });
    fireEvent.change(screen.getByLabelText("Texto"), { target: { value: "Bruno" } });
    await waitFor(() => {
      const last = app.exact("GET", "/api/v1/general/subscriptions").at(-1)!;
      expect(Object.fromEntries(last.query)).toMatchObject({ filter_field: "client", query: "Bruno" });
    });
  });
});
