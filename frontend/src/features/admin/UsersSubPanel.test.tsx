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
});
