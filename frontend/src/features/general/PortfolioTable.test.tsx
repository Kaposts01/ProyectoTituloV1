import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PortfolioTable, type PortfolioColumn } from "./PortfolioTable";

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
const columns: PortfolioColumn<{ id: string; extra: string }>[] = [
  { id: "id", label: "ID", required: true, cell: (r) => r.id },
  { id: "extra", label: "Inicio", initiallyHidden: true, cell: (r) => r.extra },
];
const props = { view: "subscriptions" as const, caption: "suscripciones", columns,
  rows: [{ id: "DEMO-1", extra: "2026-01-01" }], rowKey: (r: { id: string }) => r.id,
  loading: false, filtered: false, onRetry: vi.fn(), onClear: vi.fn() };
const openColumns = () => fireEvent.click(document.querySelector(".portfolio-columns summary")!);

describe("Tablas de Cartera", () => {
  it("permite recuperar columnas, protege el identificador y guarda solo nombres de columnas", () => {
    render(<PortfolioTable {...props} />);
    expect(screen.queryByRole("columnheader", { name: "Inicio" })).toBeNull();
    openColumns();
    expect(screen.getByRole("checkbox", { name: /Mostrar columna ID/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar columna Inicio" }));
    expect(screen.getByRole("columnheader", { name: "Inicio" })).toBeTruthy();
    expect(screen.getByText("2026-01-01")).toBeTruthy();
    expect(localStorage.getItem("synkmetrix:list-columns:v1:subscriptions")).toBe("[]");
    cleanup(); render(<PortfolioTable {...props} />);
    expect(screen.getByRole("columnheader", { name: "Inicio" })).toBeTruthy();
    openColumns(); fireEvent.click(screen.getByRole("button", { name: "Restaurar columnas" }));
    expect(screen.queryByRole("columnheader", { name: "Inicio" })).toBeNull();
    expect(localStorage.getItem("synkmetrix:list-columns:v1:subscriptions")).toBe('["extra"]');
  });
  it("tolera preferencias corruptas y almacenamiento deshabilitado", () => {
    localStorage.setItem("synkmetrix:list-columns:v1:subscriptions", "broken-json");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<PortfolioTable {...props} />);
    openColumns(); fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar columna Inicio" }));
    expect(screen.getByText("2026-01-01")).toBeTruthy();
  });
  it("durante la carga no muestra filas de la consulta anterior como resultados actuales", () => {
    render(<PortfolioTable {...props} loading />);
    expect(screen.getByRole("region", { name: "Tabla de suscripciones" })).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("DEMO-1")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Actualizando resultados");
    expect(screen.queryByText(/No hay resultados/)).toBeNull();
  });
  it("distingue errores, falta de acceso y resultados vacíos filtrados", () => {
    const retry = vi.fn(), clear = vi.fn();
    const view = render(<PortfolioTable {...props} error="Error de lectura" onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Error de lectura");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" })); expect(retry).toHaveBeenCalledOnce();
    view.rerender(<PortfolioTable {...props} forbidden />);
    expect(screen.getByText(/No tienes permiso/)).toBeTruthy();
    expect(screen.queryByText(/Todavía no hay/)).toBeNull();
    view.rerender(<PortfolioTable {...props} rows={[]} filtered onClear={clear} />);
    fireEvent.click(screen.getByRole("button", { name: "Quitar todos los filtros" }));
    expect(clear).toHaveBeenCalledOnce();
  });
});
