import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { VirtualPosWriteDialogs } from "./VirtualPosWriteDialogs";
import { useVirtualPosWrites } from "./useVirtualPosWrites";

const noop = () => {};
const details = {
  clientDetail: null, setClientDetail: noop, subscriptionDetail: null, setSubscriptionDetail: noop, chargeDetail: null, setChargeDetail: noop,
} as never;

function Harness() {
  const writes = useVirtualPosWrites({
    records: { total: 0, items: [] } as never,
    setRecords: noop as never,
    details,
  });
  return (
    <>
      <button type="button" onClick={() => writes.setCreatingSubscription(true)}>abrir</button>
      <VirtualPosWriteDialogs writes={writes} vp2Enabled={false} />
    </>
  );
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function fillAndSubmit() {
  fireEvent.click(screen.getByText("abrir"));
  const form = screen.getByLabelText("Crear suscripción VirtualPOS");
  const set = (name: string, value: string) => {
    fireEvent.change(form.querySelector(`[name="${name}"]`) as HTMLInputElement, { target: { value } });
  };
  set("plan_id", "plan-x");
  set("email", "prueba@example.com");
  set("first_name", "Prueba");
  set("last_name", "Sintética");
  set("social_id", "11111111-1");
  fireEvent.click(screen.getByRole("button", { name: "Crear suscripción" }));
}

const postBodies = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls
    .filter(([url, init]) => String(url).includes("/writes/virtualpos/subscriptions") && init?.method === "POST")
    .map(([, init]) => JSON.parse(init.body as string));

describe("alta de suscripción VirtualPOS: confirmación de duplicado", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("409 duplicate_active_subscription pregunta y reenvía con confirm_duplicate", async () => {
    let subPosts = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/writes/virtualpos/subscriptions")) {
        subPosts += 1;
        if (subPosts === 1) {
          return json(409, { detail: { code: "duplicate_active_subscription", message: "dup", existing_external_id: "sub_123", existing_status: "active" } });
        }
        return json(200, { id: "1", external_id: "sub_new", source: "virtualpos1", payload: {} });
      }
      return json(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness />);
    fillAndSubmit();

    expect(await screen.findByText(/Esta persona ya tiene una suscripción activa en este plan \(código sub_123\)\. ¿Crear otra\?/)).toBeInTheDocument();
    expect(screen.getByLabelText("Crear suscripción VirtualPOS")).toBeInTheDocument();
    expect(postBodies(fetchMock)).toHaveLength(1);
    expect(postBodies(fetchMock)[0].confirm_duplicate).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: "Crear de todas formas" }));
    await waitFor(() => expect(postBodies(fetchMock)).toHaveLength(2));
    const [first, second] = postBodies(fetchMock);
    expect(second).toEqual({ ...first, confirm_duplicate: true });
    await waitFor(() => expect(screen.queryByLabelText("Crear suscripción VirtualPOS")).not.toBeInTheDocument());
  });

  it("Cancelar vuelve al formulario sin enviar", async () => {
    const fetchMock = vi.fn(async () =>
      json(409, { detail: { code: "duplicate_active_subscription", message: "dup", existing_external_id: "sub_123", existing_status: "active" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness />);
    fillAndSubmit();
    await screen.findByText(/¿Crear otra\?/);
    const antes = postBodies(fetchMock).length;
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByText(/¿Crear otra\?/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Crear suscripción" })).toBeInTheDocument();
    expect(postBodies(fetchMock)).toHaveLength(antes);
  });

  it("otro 409 muestra el mensaje de siempre", async () => {
    const fetchMock = vi.fn(async () => json(409, { detail: { code: "otro_conflicto_de_prueba", message: "Conflicto de prueba con el estado actual." } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness />);
    fillAndSubmit();
    expect(await screen.findByText(/Conflicto de prueba con el estado actual\./)).toBeInTheDocument();
    expect(screen.queryByText(/¿Crear otra\?/)).not.toBeInTheDocument();
  });
});
