import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChartRangeSelector } from "./ChartRangeSelector";
import type { ChartRange } from "./chartRows";

afterEach(cleanup);

describe("ChartRangeSelector", () => {
  it("muestra las tres opciones como grupo de radios con la activa marcada", () => {
    render(<ChartRangeSelector value="12m" onChange={() => {}} yearLabel="Año 2026" />);
    expect(screen.getByRole("radiogroup", { name: "Rango del gráfico" })).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["Últimos 12 meses", "Año 2026", "Todo"]);
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
  });

  it("el clic cambia el valor", () => {
    const onChange = vi.fn();
    render(<ChartRangeSelector value="12m" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Todo" }));
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("roving tabindex: solo la opción activa es alcanzable con Tab", () => {
    render(<ChartRangeSelector value="year" onChange={() => {}} />);
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);
  });

  it("teclado: flechas, Inicio y Fin mueven y seleccionan con vuelta circular", () => {
    function Harness() {
      const [v, setV] = useState<ChartRange>("12m");
      return <ChartRangeSelector value={v} onChange={setV} />;
    }
    render(<Harness />);
    const checked = () => screen.getAllByRole("radio").find((r) => r.getAttribute("aria-checked") === "true")?.textContent;
    fireEvent.keyDown(screen.getByRole("radio", { name: "Últimos 12 meses" }), { key: "ArrowRight" });
    expect(checked()).toBe("Año");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Año" }), { key: "ArrowRight" });
    expect(checked()).toBe("Todo");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Todo" }), { key: "ArrowRight" });
    expect(checked()).toBe("Últimos 12 meses");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Últimos 12 meses" }), { key: "ArrowLeft" });
    expect(checked()).toBe("Todo");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Todo" }), { key: "Home" });
    expect(checked()).toBe("Últimos 12 meses");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Últimos 12 meses" }), { key: "End" });
    expect(checked()).toBe("Todo");
  });
});
