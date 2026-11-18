import { act } from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, mountApp, resetApp } from "./appHarness";

afterEach(resetApp);
const trail = () => within(screen.getByRole("navigation", { name: "Ruta de navegación" }));

describe("Orientación dentro del CRM", () => {
  it("Dashboard comparte nombre en menú, encabezado, ruta y pestaña", async () => {
    mountApp("/central/resumen");
    await appReady();
    await screen.findByRole("heading", { level: 1, name: "Dashboard" });
    expect(document.querySelector('[data-item="summary"]')).toHaveTextContent("Dashboard");
    expect(trail().getByText("Dashboard")).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(document.title).toBe("Dashboard | SynkmetriX"));
  });
  it("los enlaces de la ruta y Atrás actualizan la pantalla sin recargar", async () => {
    mountApp("/mi-perfil/editar");
    await appReady();
    await screen.findByRole("heading", { level: 1, name: "Editar perfil" });
    fireEvent.click(trail().getByRole("link", { name: "Mi perfil" }));
    await screen.findByRole("heading", { level: 1, name: "Mi perfil" });
    expect(window.location.pathname).toBe("/mi-perfil");
    act(() => {
      window.history.replaceState({}, "", "/mi-perfil/editar");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await screen.findByRole("heading", { level: 1, name: "Editar perfil" });
    await waitFor(() => expect(document.title).toBe("Editar perfil | SynkmetriX"));
  });
  it("un acceso limitado mantiene Clientes del canal y omite Dashboard de la ruta", async () => {
    mountApp("/toku/clientes", [["GET", "/api/v1/staging/records", { items: [], total: 0, offset: 0, limit: 50 }]], { permissions: ["toku.customers.view"] });
    await appReady();
    await screen.findByRole("heading", { level: 1, name: "Clientes" });
    expect(trail().queryByText("Dashboard")).toBeNull();
    expect(trail().getByRole("link", { name: "Toku" })).toHaveAttribute("href", "/toku/resumen");
    expect(trail().getByText("Clientes")).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(document.title).toBe("Clientes · Toku | SynkmetriX"));
  });
  it("una URL sin acceso redirige sin mostrarla como destino permitido", async () => {
    mountApp("/admin/usuarios", [], { permissions: [] });
    await appReady();
    await screen.findByRole("heading", { level: 1, name: "Mi perfil" });
    expect(trail().queryByText("Administración")).toBeNull();
    expect(trail().queryByRole("link", { name: "Dashboard" })).toBeNull();
    await waitFor(() => expect(document.title).toBe("Mi perfil | SynkmetriX"));
  });
});
