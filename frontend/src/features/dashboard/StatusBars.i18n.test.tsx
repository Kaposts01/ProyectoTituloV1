import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StatusBars } from "./StatusBars";

afterEach(cleanup);

describe("StatusBars: estados en español", () => {
  const statuses = [
    { resource: "charge", status: "PAID", count: 3 },
    { resource: "charge", status: "failed", count: 2 },
    { resource: "charge", status: "ZZ_NUEVO", count: 1 },
  ];

  it("la leyenda y el título de cada segmento traducen el estado; el color sigue el valor crudo", () => {
    const { container } = render(<StatusBars source="virtualpos" resources={{ charge: 6 }} statuses={statuses} />);
    expect(screen.getByText("Pagado")).toBeTruthy();
    expect(screen.getByText("Fallido")).toBeTruthy();
    expect(screen.getByText("Desconocido (ZZ_NUEVO)")).toBeTruthy();
    expect(screen.queryByText("PAID")).toBeNull();
    const titles = Array.from(container.querySelectorAll(".status-bar-segment")).map((el) => el.getAttribute("title"));
    expect(titles).toEqual(["Pagado: 3", "Fallido: 2", "Desconocido (ZZ_NUEVO): 1"]);
    const kinds = Array.from(container.querySelectorAll(".status-bar-segment")).map((el) => el.getAttribute("data-status-kind"));
    expect(kinds).toEqual(["paid", "rejected", "unknown"]);
  });

  it("UI-34: un recurso con total y sin estados muestra el total sin barra vacía", () => {
    const { container } = render(<StatusBars source="virtualpos" resources={{ charge: 6, plan: 8 }} statuses={statuses} />);
    expect(screen.getByText("8")).toBeTruthy();
    expect(screen.getByText("Sin estado informado por el canal")).toBeTruthy();
    expect(container.querySelectorAll(".status-bar-track")).toHaveLength(1);
  });
});
