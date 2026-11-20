/** PERF-03 (d264 C): integración con AppCore. Los datos adelantados no se ven hasta que /auth/me confirma la sesión. */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { getCached } from "./apiCache";
import { FIRST_PAGE_URLS, startEarlyData, takeEarly } from "./earlyData";
import { appReady, failWith, mountApp, resetApp, session, type Handler } from "./test/appHarness";

afterEach(resetApp);

const row = { channel: "virtualpos1", subscription_id: "DEMO-VP-1", status: "ACTIVA", secondary_status: "cobrable", start_date: "2026-01-10", end_date: null, amount: "5000", currency: "CLP", last_charge: null, rut: "11111111-1", name: "DEMO Uno" };
const page = { items: [row], total: 1, offset: 0, limit: 50, by_channel: { virtualpos: 1 }, canales: ["virtualpos1"] };
const statuses: Handler = ["GET", "/api/v1/general/subscriptions/statuses", { statuses: [], canales: ["virtualpos1"] }];

describe("datos adelantados con AppCore", () => {
  it("la primera página se pide una sola vez, en paralelo con /auth/me, y se ve solo con la sesión confirmada", async () => {
    let confirm: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { confirm = resolve; });
    const app = mountApp("/central/suscripciones", [
      ["GET", "/api/v1/auth/me", () => gate.then(() => session())],
      ["GET", "/api/v1/general/subscriptions", page],
      statuses,
    ]);
    startEarlyData("/central/suscripciones", "");
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/subscriptions")).toHaveLength(1));
    // /auth/me sigue en vuelo: nada de la vista está en pantalla
    expect(screen.queryByText("DEMO Uno")).toBeNull();
    confirm();
    expect(await screen.findByText("DEMO Uno")).toBeTruthy();
    expect(app.exact("GET", "/api/v1/general/subscriptions")).toHaveLength(1);
  });

  it("si /auth/me da 401 se descarta lo adelantado y no se muestra la vista", async () => {
    let settle: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { settle = resolve; });
    const app = mountApp("/central/suscripciones", [
      ["GET", "/api/v1/auth/me", () => gate.then(() => failWith(401, "No autenticado"))],
      ["GET", "/api/v1/general/subscriptions", page],
      statuses,
    ]);
    startEarlyData("/central/suscripciones", "");
    await waitFor(() => expect(app.exact("GET", "/api/v1/general/subscriptions")).toHaveLength(1));
    settle();
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeTruthy();
    expect(screen.queryByText("DEMO Uno")).toBeNull();
    expect(takeEarly(FIRST_PAGE_URLS.subscriptions)).toBeNull();
  });

  it("al cerrar sesión se descarta lo adelantado", async () => {
    mountApp("/central/suscripciones", [
      ["GET", "/api/v1/general/subscriptions", page], statuses, ["POST", "/api/v1/auth/logout", {}],
      ["GET", "/api/v1/staging/dashboard/general/clients", { items: [], total: 0, offset: 0, limit: 50 }],
    ]);
    await appReady();
    await screen.findByText("DEMO Uno");
    startEarlyData("/central/clientes", "");
    await waitFor(() => expect(getCached(`early:${FIRST_PAGE_URLS.clients}`, 60_000)).not.toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "Opciones de cuenta" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Cerrar sesión" }));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeTruthy();
    expect(takeEarly(FIRST_PAGE_URLS.clients)).toBeNull();
  });
});
