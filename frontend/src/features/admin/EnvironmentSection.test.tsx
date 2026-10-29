import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";

vi.mock("../../api", () => ({ getJson: vi.fn() }));
import { getJson } from "../../api";
import { EnvironmentSection } from "./EnvironmentSection";

const mocked = vi.mocked(getJson);
const PERM = ["system.environment.switch"];

function mockApi(sw: unknown) {
  mocked.mockImplementation(async (path: string) => {
    if (path.endsWith("/environment")) return { app_env: "production", label: "Producción", is_production: true };
    if (sw instanceof Error) throw sw;
    return sw;
  });
}

beforeEach(() => { invalidateCache(); mocked.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("EnvironmentSection", () => {
  it("no aparece ni consulta sin permiso", () => {
    mockApi({ target_env: "sandbox", target_label: "Sandbox", url: "https://sb.example" });
    const { container } = render(<EnvironmentSection permissions={[]} />);
    expect(container).toBeEmptyDOMElement();
    expect(mocked).not.toHaveBeenCalled();
  });

  it("se oculta ante un error (403)", async () => {
    mockApi(new Error("403"));
    const { container } = render(<EnvironmentSection permissions={PERM} />);
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    expect(container).toBeEmptyDOMElement();
  });

  it("deshabilita el boton si url es null", async () => {
    mockApi({ target_env: "sandbox", target_label: "Sandbox", url: null });
    render(<EnvironmentSection permissions={PERM} />);
    expect(await screen.findByRole("button", { name: "Cambiar a Sandbox" })).toBeDisabled();
    expect(screen.getByText(/falta SANDBOX_APP_URL/)).toBeInTheDocument();
  });

  it("confirma antes de abrir con noopener", async () => {
    mockApi({ target_env: "sandbox", target_label: "Sandbox", url: "https://sb.example/" });
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<EnvironmentSection permissions={PERM} />);
    expect(await screen.findByText("Producción")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cambiar a Sandbox" }));
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByText(/Vas a abrir el ambiente Sandbox en otra pestaña/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir Sandbox" }));
    expect(open).toHaveBeenCalledWith("https://sb.example/", "_blank", "noopener,noreferrer");
  });

  it("usa 'Volver a' al apuntar a produccion", async () => {
    mockApi({ target_env: "production", target_label: "Producción", url: "https://prod.example/" });
    render(<EnvironmentSection permissions={PERM} />);
    expect(await screen.findByRole("button", { name: "Volver a Producción" })).toBeEnabled();
  });

  it("usa la escala del sistema: h2 de seccion, boton secundario y separacion", async () => {
    mockApi({ target_env: "production", target_label: "Producción", url: "https://prod.example/" });
    const { container } = render(<EnvironmentSection permissions={PERM} />);
    const btn = await screen.findByRole("button", { name: "Volver a Producción" });
    expect(btn).toHaveClass("secondary-button");
    const heading = screen.getByRole("heading", { name: "Ambiente", level: 2 });
    expect(heading).toHaveClass("section-title");
    expect(container.querySelector("section")).toHaveClass("environment-section");
  });

  it("los botones del dialogo de confirmacion usan los componentes del sistema", async () => {
    mockApi({ target_env: "sandbox", target_label: "Sandbox", url: "https://sb.example/" });
    render(<EnvironmentSection permissions={PERM} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cambiar a Sandbox" }));
    expect(screen.getByRole("button", { name: "Abrir Sandbox" })).toHaveClass("primary-button");
    expect(screen.getByRole("button", { name: "Cancelar" })).toHaveClass("secondary-button");
  });
});
