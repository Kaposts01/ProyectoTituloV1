import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ChannelTableScroll } from "./ChannelTableScroll";

afterEach(cleanup);

it("permite enfocar el área de scroll nativo, sin duplicar barras ni ocultar contenido", () => {
  render(<ChannelTableScroll label="Suscripciones de TCH"><table><thead><tr><th>Ficha</th></tr></thead>
    <tbody><tr><td><button>Ver ficha DEMO</button></td></tr></tbody></table></ChannelTableScroll>);
  expect(screen.getByRole("region", { name: "Tabla de Suscripciones de TCH" })).toHaveAttribute("tabindex", "0");
  expect(screen.getByRole("button", { name: "Ver ficha DEMO" })).toBeTruthy();
  expect(screen.queryByRole("slider")).toBeNull();
  expect(screen.queryByText("Explorar columnas")).toBeNull();
});
