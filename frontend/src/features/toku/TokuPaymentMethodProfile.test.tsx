import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TokuPaymentMethodProfile } from "./TokuPaymentMethodProfile";
import { resetUnknownWarnings } from "../../i18n/label";

afterEach(cleanup);
beforeEach(() => {
  resetUnknownWarnings();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

const payload = {
  id: "tpm-1",
  gateway: "pasarela_x",
  customer: { id: "tcu-1", name: "Cliente Sintético", government_id: "11111111-1" },
  payment_method: {
    id: "tpm-1",
    type: "card",
    status: "ACTIVE",
    card: { card_brand: "VISA", card_type: "CREDIT", last_digits: "0000", bank_name: "Banco Sintético", three_d_secure: true },
  },
};

const row = (term: string) => screen.getByText(term, { selector: "dt" }).parentElement!;

describe("TokuPaymentMethodProfile: valores en español", () => {
  it("tipo, estado, marca y tipo de tarjeta se traducen; 3D Secure se ve Sí", () => {
    render(<TokuPaymentMethodProfile payload={payload} />);
    expect(screen.getByRole("heading", { name: "Tarjeta" })).toBeTruthy();
    expect(within(row("Estado")).getByText("Activa")).toBeTruthy();
    expect(within(row("Marca")).getByText("Visa")).toBeTruthy();
    expect(within(row("Tipo")).getByText("Tarjeta de crédito")).toBeTruthy();
    expect(within(row("3D Secure")).getByText("Sí")).toBeTruthy();
  });

  it("una pasarela sin traducción conocida se ve «Desconocido (X)»", () => {
    render(<TokuPaymentMethodProfile payload={payload} />);
    expect(within(row("Gateway")).getByText("Desconocido (pasarela_x)")).toBeTruthy();
  });

  it("un tipo de medio desconocido se ve «Desconocido (X)» y sin tipo se ve «Método sin tipo»", () => {
    const { rerender } = render(<TokuPaymentMethodProfile payload={{ ...payload, payment_method: { ...payload.payment_method, type: "crypto" } }} />);
    expect(screen.getByRole("heading", { name: "Desconocido (crypto)" })).toBeTruthy();
    rerender(<TokuPaymentMethodProfile payload={{ ...payload, payment_method: { id: "x" } }} />);
    expect(screen.getByRole("heading", { name: "Método sin tipo" })).toBeTruthy();
  });
});
