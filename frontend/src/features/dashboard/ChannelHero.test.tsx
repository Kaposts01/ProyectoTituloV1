/** PERF-03 (d264 A): la cabecera real del canal se ve desde el inicio, con los controles deshabilitados. Datos sintéticos. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, mountApp, resetApp } from "../../test/appHarness";
import { PageSkeleton } from "../../components/PageSkeleton";
import { ChannelHero } from "./ChannelHero";

afterEach(() => { cleanup(); resetApp(); });

describe("ChannelHero en carga", () => {
  it.each([["virtualpos", "VIRTUALPOS"], ["toku", "TOKU"], ["payku", "PAYKU"]])("%s: eyebrow, título y descripción reales con controles deshabilitados", (source, eyebrow) => {
    render(<PageSkeleton label="Cargando mini dashboard..." variant="cards" header={<ChannelHero source={source} loading />} />);
    expect(screen.getByText(eyebrow)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Resumen operativo/ })).toBeTruthy();
    expect(screen.getByText("Indicadores y actividad del período seleccionado.")).toBeTruthy();
    for (const name of ["Cantidad", "Monto", "↻ Sincronizar", "Generar reporte"]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect((screen.getByLabelText("Año") as HTMLSelectElement).disabled).toBe(true);
    // sigue habiendo un solo aviso de carga y el esqueleto de tarjetas, pero ya no la barra de título
    expect(screen.getByRole("status")).toHaveTextContent("Cargando mini dashboard...");
    expect(document.querySelector(".page-skeleton-title")).toBeNull();
    expect(document.querySelectorAll(".page-skeleton-cards .summary-skeleton")).toHaveLength(4);
  });

  it("al llegar los datos usa el mismo marcado y solo se habilitan los controles", () => {
    const { container, rerender } = render(<ChannelHero source="toku" loading />);
    const shape = (root: HTMLElement) => Array.from(root.querySelectorAll("*")).map((el) => el.tagName + "." + el.className).join("|");
    const loadingShape = shape(container);
    rerender(<ChannelHero source="toku" years={[2026]} year={2026} lastSyncStatus="completed" />);
    // misma estructura de elementos (cabecera, controles, fila de acciones), distinta solo en habilitado y texto
    expect(shape(container).replace(/\s(ready|attention)/g, "")).toBe(loadingShape.replace(/\s(ready|attention)/g, ""));
    for (const name of ["Cantidad", "Monto", "↻ Sincronizar", "Generar reporte"]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(false);
    }
    expect((screen.getByLabelText("Año") as HTMLSelectElement).disabled).toBe(false);
  });
});

describe("canal en AppCore mientras llegan los datos", () => {
  it("muestra la cabecera real, con los controles deshabilitados, hasta que responde el dashboard", async () => {
    mountApp("/toku/resumen", [["GET", "/api/v1/staging/dashboard/toku", () => new Promise(() => undefined)]]);
    await appReady();
    expect(await screen.findByRole("heading", { name: /Resumen operativo/ })).toBeTruthy();
    expect(screen.getByText("TOKU")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Generar reporte" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Cantidad" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
