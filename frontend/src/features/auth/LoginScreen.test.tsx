import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "./LoginScreen";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function submitWith(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: status < 400, status, headers: { get: () => "application/json" }, json: async () => body })));
  render(<LoginScreen onLogin={() => {}} />);
  fireEvent.change(document.querySelector('[name="username"]') as HTMLInputElement, { target: { value: "operador.sintetico" } });
  fireEvent.change(document.querySelector('[name="password"]') as HTMLInputElement, { target: { value: "clave-sintetica" } });
  fireEvent.submit(document.querySelector("form") as HTMLFormElement);
}

describe("LoginScreen: errores en español", () => {
  it("credenciales inválidas se ven en español, no el texto del servidor", async () => {
    submitWith(401, { detail: "Invalid username or password" });
    expect(await screen.findByText("Usuario o contraseña incorrectos.")).toBeTruthy();
    expect(screen.queryByText("Invalid username or password")).toBeNull();
  });

  it("autenticación no configurada", async () => {
    submitWith(503, { detail: "Authentication is not configured" });
    expect(await screen.findByText("La autenticación no está configurada en este servidor.")).toBeTruthy();
  });

  it("sin detalle usa el texto de reserva", async () => {
    submitWith(500, {});
    expect(await screen.findByText("No se pudo iniciar sesión")).toBeTruthy();
  });
});
