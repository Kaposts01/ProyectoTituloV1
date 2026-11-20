import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../apiCache";

vi.mock("../api", () => ({ getJson: vi.fn() }));
import { getJson } from "../api";
import { EnvironmentBanner, reserveEnvironmentBannerSpace } from "./EnvironmentBanner";

const mocked = vi.mocked(getJson);

beforeEach(() => { invalidateCache(); mocked.mockReset(); });
afterEach(() => { cleanup(); vi.unstubAllEnvs(); document.documentElement.classList.remove("has-env-banner"); });

describe("EnvironmentBanner", () => {
  it("se muestra en sandbox", async () => {
    mocked.mockResolvedValue({ app_env: "sandbox", label: "Sandbox", is_production: false });
    render(<EnvironmentBanner />);
    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent(/SANDBOX/);
    expect(banner).toHaveTextContent(/no es producción/);
    await waitFor(() => expect(document.documentElement).toHaveClass("has-env-banner"));
  });

  it("no se muestra en produccion", async () => {
    mocked.mockResolvedValue({ app_env: "production", label: "Producción", is_production: true });
    render(<EnvironmentBanner />);
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("status")).toBeNull();
    expect(document.documentElement).not.toHaveClass("has-env-banner");
  });

  it("no se muestra ni falla ante error", async () => {
    mocked.mockRejectedValue(new Error("boom"));
    render(<EnvironmentBanner />);
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("en la build de sandbox reserva el espacio de forma síncrona, antes de la respuesta", () => {
    vi.stubEnv("MODE", "sandbox");
    mocked.mockReturnValue(new Promise(() => undefined));
    render(<EnvironmentBanner />);
    expect(document.documentElement).toHaveClass("has-env-banner");
    expect(document.querySelector(".env-banner")).not.toBeNull();
  });

  it("reserveEnvironmentBannerSpace marca el html solo en sandbox", () => {
    reserveEnvironmentBannerSpace();
    expect(document.documentElement).not.toHaveClass("has-env-banner");
    vi.stubEnv("MODE", "sandbox");
    reserveEnvironmentBannerSpace();
    expect(document.documentElement).toHaveClass("has-env-banner");
  });

  it("en producción no reserva nada mientras carga", () => {
    vi.stubEnv("MODE", "production");
    mocked.mockReturnValue(new Promise(() => undefined));
    render(<EnvironmentBanner />);
    expect(document.documentElement).not.toHaveClass("has-env-banner");
    expect(document.querySelector(".env-banner")).toBeNull();
  });

  it("en sandbox libera el espacio si el servidor responde que es producción", async () => {
    vi.stubEnv("MODE", "sandbox");
    mocked.mockResolvedValue({ app_env: "production", label: "Producción", is_production: true });
    render(<EnvironmentBanner />);
    await waitFor(() => expect(document.documentElement).not.toHaveClass("has-env-banner"));
  });
});
