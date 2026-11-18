import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { UnifiedFilterBar } from "./UnifiedControls";

afterEach(cleanup);
function Example({ busy = false }: { busy?: boolean }) {
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState("");
  const [field, setField] = useState("all");
  const [status, setStatus] = useState("");
  return <UnifiedFilterBar idPrefix="demo" query={query} onQuery={setQuery} channel={channel} onChannel={setChannel}
    field={field} onField={setField} fields={[{ value: "all", label: "Todos los campos" }, { value: "rut", label: "RUT" }]}
    status={status} onStatus={setStatus} statuses={[{ status: "ACTIVE", count: 3 }]} channels={["toku"]}
    busy={busy} actions={<button>Exportar</button>} />;
}
const toggle = () => fireEvent.click(document.querySelector(".portfolio-more-filters summary")!);
describe("Busqueda y filtros progresivos", () => {
  it("busca directamente y conserva criterios al cerrar Más filtros", () => {
    render(<Example />);
    expect(screen.getByRole("searchbox", { name: "Buscar" })).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Estado" })).toBeNull();
    toggle();
    fireEvent.change(screen.getByRole("combobox", { name: "Estado" }), { target: { value: "ACTIVE" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Buscar en" }), { target: { value: "rut" } });
    toggle();
    expect(screen.queryByRole("combobox", { name: "Estado" })).toBeNull();
    expect(screen.getByRole("list", { name: "Filtros activos" })).toHaveTextContent("Estado:");
    expect(screen.getByText(/Busca en RUT/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    toggle();
    expect(screen.getByRole("combobox", { name: "Estado" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Buscar en" })).toHaveValue("all");
  });
  it("borra la búsqueda y devuelve foco al campo sin borrar los otros criterios", () => {
    render(<Example />);
    fireEvent.change(screen.getByRole("combobox", { name: "Canal" }), { target: { value: "toku" } });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "DEMO" } });
    fireEvent.click(screen.getByRole("button", { name: "Borrar búsqueda" }));
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.getByRole("searchbox")).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "Canal" })).toHaveValue("toku");
  });
  it("bloquea exportar mientras la nueva consulta sigue pendiente", () => {
    render(<Example busy />);
    expect(screen.getByRole("button", { name: "Exportar" })).toBeDisabled();
  });
});
