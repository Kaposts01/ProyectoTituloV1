import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, getJson: vi.fn(), postJson: vi.fn() };
});
import { ApiError, getJson, postJson } from "../../api";
import { PaykuWalletWithdraw, WALLET_URL, WALLET_WITHDRAW_URL, type WalletBalance } from "./PaykuWalletWithdraw";

const mockedGet = vi.mocked(getJson);
const mockedPost = vi.mocked(postJson);

function balance(over: Partial<WalletBalance> = {}): WalletBalance {
  return { enabled: true, amount_available: 12345, currency: "CLP", ...over };
}

beforeEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
});
afterEach(cleanup);

describe("PaykuWalletWithdraw (CRM-14F)", () => {
  it("muestra el saldo y abre un diálogo de confirmación con el monto", async () => {
    mockedGet.mockResolvedValue(balance() as never);
    render(<PaykuWalletWithdraw />);
    expect(await screen.findByTestId("wallet-available")).toHaveTextContent("12.345");
    expect(mockedGet).toHaveBeenCalledWith(WALLET_URL);

    fireEvent.click(screen.getByRole("button", { name: "Retirar fondos" }));
    const dialog = screen.getByRole("dialog", { name: "Retirar todo el saldo" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("wallet-confirm-amount")).toHaveTextContent("CLP $12.345");
    expect(mockedPost).not.toHaveBeenCalled(); // abrir el diálogo no retira nada
  });

  it("al confirmar envía el monto visto como expected_amount y relee el saldo", async () => {
    mockedGet.mockResolvedValueOnce(balance() as never).mockResolvedValueOnce(balance({ amount_available: 0 }) as never);
    mockedPost.mockResolvedValue({ status: "completed" } as never);
    render(<PaykuWalletWithdraw />);
    fireEvent.click(await screen.findByRole("button", { name: "Retirar fondos" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar retiro" }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith(WALLET_WITHDRAW_URL, { expected_amount: 12345 }));
    expect(await screen.findByRole("status")).toHaveTextContent("Retiro solicitado a Payku");
    expect(mockedGet).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Retirar fondos" })).toBeDisabled();
  });

  it("«Volver» cierra el diálogo sin retirar", async () => {
    mockedGet.mockResolvedValue(balance() as never);
    render(<PaykuWalletWithdraw />);
    fireEvent.click(await screen.findByRole("button", { name: "Retirar fondos" }));
    fireEvent.click(screen.getByRole("button", { name: "Volver" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("con el flag apagado el botón queda deshabilitado y se explica", async () => {
    mockedGet.mockResolvedValue(balance({ enabled: false, amount_available: null, currency: null }) as never);
    render(<PaykuWalletWithdraw />);
    expect(await screen.findByText("El retiro de fondos está deshabilitado en este ambiente.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirar fondos" })).toBeDisabled();
  });

  it("sin saldo el botón queda deshabilitado", async () => {
    mockedGet.mockResolvedValue(balance({ amount_available: 0 }) as never);
    render(<PaykuWalletWithdraw />);
    expect(await screen.findByText("No hay saldo disponible para retirar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirar fondos" })).toBeDisabled();
  });

  it("si el saldo cambió muestra el error traducido y relee el saldo", async () => {
    mockedGet.mockResolvedValueOnce(balance() as never).mockResolvedValueOnce(balance({ amount_available: 999 }) as never);
    mockedPost.mockRejectedValue(
      new ApiError("El saldo de la billetera cambió desde que lo viste. No se retiró nada: revisa el monto nuevo y confirma otra vez.", 409, {
        code: "payku_wallet_balance_changed",
        message: "x",
      }),
    );
    render(<PaykuWalletWithdraw />);
    fireEvent.click(await screen.findByRole("button", { name: "Retirar fondos" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar retiro" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El saldo de la billetera cambió");
    await waitFor(() => expect(screen.getByTestId("wallet-confirm-amount")).toHaveTextContent("999"));
  });
});
