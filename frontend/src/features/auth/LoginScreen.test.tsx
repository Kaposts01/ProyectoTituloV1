import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const env = vi.hoisted(() => ({ fetchEnvironment: vi.fn() }));
vi.mock("../shared/environment", () => ({ fetchEnvironment: env.fetchEnvironment }));

import { LoginScreen } from "./LoginScreen";

beforeEach(() => {
  env.fetchEnvironment.mockReset();
  env.fetchEnvironment.mockResolvedValue({ app_env: "test", label: "Test", is_production: false });
  window.history.replaceState(null, "", "/");
});

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

describe("LoginScreen: Entrar con Google", () => {
  it("no aparece si google_login_enabled falta o es false", async () => {
    render(<LoginScreen onLogin={() => {}} />);
    await waitFor(() => expect(env.fetchEnvironment).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: "Entrar con Google" })).toBeNull();
    expect(screen.getByRole("button", { name: "Ingresar" })).toBeTruthy();
  });

  it("aparece como enlace a /api/v1/auth/google/start si está habilitado", async () => {
    env.fetchEnvironment.mockResolvedValue({ app_env: "test", label: "Test", is_production: false, google_login_enabled: true });
    render(<LoginScreen onLogin={() => {}} />);
    const link = await screen.findByRole("link", { name: "Entrar con Google" });
    expect(link.getAttribute("href")).toBe("/api/v1/auth/google/start");
    expect(document.querySelector('[name="username"]')).toBeTruthy();
  });

  it("con ?login_error=google muestra el mensaje y limpia el parámetro", async () => {
    window.history.replaceState(null, "", "/?login_error=google&otro=1");
    render(<LoginScreen onLogin={() => {}} />);
    expect(await screen.findByText("No fue posible iniciar sesión con Google.")).toBeTruthy();
    expect(window.location.search).toBe("?otro=1");
  });

  it("sin el parámetro no hay mensaje", async () => {
    render(<LoginScreen onLogin={() => {}} />);
    await waitFor(() => expect(env.fetchEnvironment).toHaveBeenCalled());
    expect(screen.queryByText("No fue posible iniciar sesión con Google.")).toBeNull();
  });
});
