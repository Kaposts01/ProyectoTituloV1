import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PageBreadcrumbs } from "./PageBreadcrumbs";

afterEach(cleanup);
describe("Ruta de navegación", () => {
  it("expone un destino real y una página actual que no es un enlace", () => {
    const navigate = vi.fn();
    render(<PageBreadcrumbs crumbs={[{ label: "Dashboard", href: "/central/resumen" }, { label: "Cartera" }, { label: "Socios" }]} onNavigate={navigate} />);
    expect(screen.getByRole("navigation", { name: "Ruta de navegación" })).toBeTruthy();
    expect(screen.getByText("Socios")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Cartera" })).toBeNull();
    const link = screen.getByRole("link", { name: "Dashboard" });
    expect(link).toHaveAttribute("href", "/central/resumen");
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/central/resumen");
  });
  it.each(["ctrlKey", "metaKey", "shiftKey", "altKey"])("respeta %s para las acciones nativas del navegador", (key) => {
    const navigate = vi.fn();
    render(<PageBreadcrumbs crumbs={[{ label: "Dashboard", href: "#dashboard" }, { label: "Socios" }]} onNavigate={navigate} />);
    fireEvent.click(screen.getByRole("link"), { [key]: true });
    expect(navigate).not.toHaveBeenCalled();
  });
});
