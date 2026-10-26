import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../apiCache";

vi.mock("../api", () => ({ getJson: vi.fn() }));
import { getJson } from "../api";
import { EnvironmentBanner } from "./EnvironmentBanner";

const mocked = vi.mocked(getJson);

beforeEach(() => { invalidateCache(); mocked.mockReset(); });
afterEach(cleanup);

describe("EnvironmentBanner", () => {
  it("se muestra en sandbox", async () => {
    mocked.mockResolvedValue({ app_env: "sandbox", label: "Sandbox", is_production: false });
    render(<EnvironmentBanner />);
    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent(/SANDBOX/);
    expect(banner).toHaveTextContent(/no es producción/);
    expect(document.documentElement).toHaveClass("has-env-banner");
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
});
