import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PageSkeleton } from "./PageSkeleton";

afterEach(cleanup);

describe("PageSkeleton", () => {
  it("anuncia la carga a lectores de pantalla y marca la zona como ocupada", () => {
    render(<PageSkeleton label="Cargando vista..." />);
    expect(screen.getByRole("status")).toHaveTextContent("Cargando vista...");
    const busy = screen.getByTestId("page-skeleton-blocks");
    expect(busy).toHaveAttribute("aria-busy", "true");
    // H5: el aviso no está dentro de la zona ocupada ni el <main> entero lo está.
    expect(busy).not.toContainElement(screen.getByRole("status"));
    expect(screen.getByTestId("page-skeleton")).not.toHaveAttribute("aria-busy");
  });

  it("reserva bloques con alto (variante tabla: filtros y cuerpo)", () => {
    const { container } = render(<PageSkeleton label="x" />);
    expect(container.querySelector(".page-skeleton-filters")).not.toBeNull();
    expect(container.querySelector(".page-skeleton-body")).not.toBeNull();
    expect(container.querySelectorAll(".page-skeleton-cards .summary-skeleton")).toHaveLength(0);
  });

  it("variante tarjetas: cuatro tarjetas esqueleto y el cuerpo", () => {
    const { container } = render(<PageSkeleton label="x" variant="cards" />);
    expect(container.querySelectorAll(".page-skeleton-cards .summary-skeleton")).toHaveLength(4);
    expect(container.querySelector(".page-skeleton-body")).not.toBeNull();
  });

  it("los bloques decorativos no se exponen a lectores de pantalla", () => {
    const { container } = render(<PageSkeleton label="x" />);
    container.querySelectorAll(".summary-skeleton").forEach((el) => expect(el).toHaveAttribute("aria-hidden", "true"));
  });
});
