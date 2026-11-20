import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn(), patchJson: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson, postJson: mocks.postJson, putJson: mocks.putJson, patchJson: mocks.patchJson,
}));
vi.mock("../shared/utils", () => ({ refreshCsrfToken: vi.fn(async () => undefined) }));

import { UsersSubPanel } from "./UsersSubPanel";

beforeEach(() => {
  mocks.getJson.mockReset(); mocks.postJson.mockReset();
  mocks.getJson.mockResolvedValue([]);
  mocks.postJson.mockResolvedValue({ id: "u2" });
});
afterEach(cleanup);

describe("UsersSubPanel", () => {
  it("crear usuario: tras el POST limpia el formulario y avisa (antes: «Cannot read properties of null (reading 'reset')»)", async () => {
    const { container } = render(<UsersSubPanel canManage roles={[{ id: "r1", name: "soporte" } as never]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo usuario" }));
    const username = container.querySelector<HTMLInputElement>('input[name="username"]')!;
    const password = container.querySelector<HTMLInputElement>('input[name="password"]')!;
    fireEvent.change(username, { target: { value: "operador.sintetico" } });
    fireEvent.change(password, { target: { value: "marea-lenta-azul-47" } });
    fireEvent.submit(username.form!);

    expect(await screen.findByText("Usuario creado.")).toBeTruthy();
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledTimes(1));
    expect(username.value).toBe("");
    expect(screen.queryByText(/reading 'reset'/)).toBeNull();
  });

  const roles = [{ id: "r1", name: "soporte" } as never];
  const user = { id: "u1", username: "ana", is_active: true, roles: [], permissions: [], created_at: null };

  function fillCreate(container: HTMLElement, googleEmail: string) {
    const open = screen.queryByRole("button", { name: "Nuevo usuario" });
    if (open) fireEvent.click(open);
    const username = container.querySelector<HTMLInputElement>('input[name="username"]')!;
    fireEvent.change(username, { target: { value: "operador.sintetico" } });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[name="password"]')!, { target: { value: "marea-lenta-azul-47" } });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[name="google_email"]')!, { target: { value: googleEmail } });
    fireEvent.submit(username.form!);
  }

  it("alta: envía google_email y vacío va como null", async () => {
    const { container } = render(<UsersSubPanel canManage roles={roles} />);
    await screen.findByRole("button", { name: "Nuevo usuario" });
    fillCreate(container, "ana@techo.org");
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledTimes(1));
    expect(mocks.postJson.mock.calls[0][1]).toMatchObject({ google_email: "ana@techo.org" });
    await screen.findByText("Usuario creado.");
    fillCreate(container, "");
    await waitFor(() => expect(mocks.postJson).toHaveBeenCalledTimes(2));
    expect(mocks.postJson.mock.calls[1][1]).toMatchObject({ google_email: null });
  });

  it("alta: mensajes claros para 409 y 422", async () => {
    const { container } = render(<UsersSubPanel canManage roles={roles} />);
    await screen.findByRole("button", { name: "Nuevo usuario" });
    mocks.postJson.mockRejectedValueOnce(Object.assign(new Error("conflicto"), { status: 409 }));
    fillCreate(container, "ana@techo.org");
    expect(await screen.findByText("Ese correo de Google ya está asignado a otro usuario.")).toBeTruthy();
    mocks.postJson.mockRejectedValueOnce(Object.assign(new Error("inválido"), { status: 422 }));
    fillCreate(container, "ana@otro.com");
    expect(await screen.findByText("El correo de Google no es válido: debe ser una cuenta @techo.org.")).toBeTruthy();
  });

  it("listado muestra el correo y edición lo precarga, lo cambia y lo quita", async () => {
    mocks.getJson.mockResolvedValue([{ ...user, google_email: "ana@techo.org" }, { ...user, id: "u2", username: "luis", google_email: null }]);
    mocks.putJson.mockResolvedValue({});
    const { container } = render(<UsersSubPanel canManage roles={roles} />);
    expect(await screen.findByText("ana@techo.org")).toBeTruthy();
    expect(screen.getByText("Sin correo")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Editar" })[0]);
    const input = container.querySelector<HTMLInputElement>('input[name="google_email"]')!;
    expect(input.value).toBe("ana@techo.org");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.submit(input.form!);
    await waitFor(() => expect(mocks.putJson).toHaveBeenCalledTimes(1));
    expect(mocks.putJson.mock.calls[0][1]).toMatchObject({ google_email: null });
  });

  it("edición: 409 y 422 muestran mensaje claro", async () => {
    mocks.getJson.mockResolvedValue([{ ...user, google_email: null }]);
    const { container } = render(<UsersSubPanel canManage roles={roles} />);
    await screen.findByText("ana");
    for (const [status, text] of [[409, "Ese correo de Google ya está asignado a otro usuario."], [422, "El correo de Google no es válido: debe ser una cuenta @techo.org."]] as const) {
      mocks.putJson.mockRejectedValueOnce(Object.assign(new Error("x"), { status }));
      fireEvent.click(screen.getByRole("button", { name: "Editar" }));
      fireEvent.submit(container.querySelector<HTMLInputElement>('input[name="google_email"]')!.form!);
      expect(await screen.findByText(text)).toBeTruthy();
    }
  });
});
