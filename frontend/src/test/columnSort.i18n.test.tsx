/**
 * Paso 2: ordenar y filtrar por columna sigue funcionando aunque el rótulo cambie, y la URL conserva la clave
 * estable (`?orden=Email`), no el texto traducido. Datos sintéticos.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, listSettled, mountApp, resetApp, type Handler } from "./appHarness";
import { page, vpClient } from "./fixtures";

afterEach(resetApp);

const records: Handler = ["GET", "/api/v1/staging/records", page([vpClient(1)])];
const lastRecordsCall = (app: ReturnType<typeof mountApp>) => app.exact("GET", "/api/v1/staging/records").at(-1)!;

describe("orden por columna con rótulo traducido", () => {
  it("ordenar por «Correo electrónico» pide sort_field=email y la URL guarda la clave Email", async () => {
    const app = mountApp("/virtualpos/clientes", [records]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    fireEvent.click(screen.getByTitle("Ordenar por Correo electrónico"));
    await waitFor(() => expect(lastRecordsCall(app).query.get("sort_field")).toBe("email"));
    expect(lastRecordsCall(app).query.get("sort_direction")).toBe("asc");
    expect(window.location.search).toBe("?orden=Email&direccion=asc");
  });

  it("un enlace guardado con ?orden=Telefono sigue ordenando por teléfono", async () => {
    const app = mountApp("/virtualpos/clientes?orden=Telefono&direccion=desc", [records]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    await waitFor(() => expect(lastRecordsCall(app).query.get("sort_field")).toBe("phone_number"));
    expect(lastRecordsCall(app).query.get("sort_direction")).toBe("desc");
  });

  it("el filtro por columna usa el campo, no el rótulo", async () => {
    const app = mountApp("/virtualpos/clientes", [records]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    fireEvent.change(screen.getByLabelText("Buscar por Correo electrónico"), { target: { value: "p1@" } });
    await waitFor(() => expect(lastRecordsCall(app).query.getAll("filters")).toContain("email:p1@"));
    await listSettled();
  });
});
