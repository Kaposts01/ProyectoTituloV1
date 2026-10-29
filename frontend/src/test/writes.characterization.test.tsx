/**
 * Caracterización de los diálogos y manejadores de escritura de AppCore (VirtualPOS, Toku, Payku).
 * UX-04. Todas las peticiones están simuladas; datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, contentHtml, listSettled, failWith, mountApp, resetApp, type Call, type Handler } from "./appHarness";
import { page, paykuClient, paykuSubscription, rec, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpPlan, vpSubscription } from "./fixtures";

afterEach(resetApp);

const records = (items: unknown[], total = items.length): Handler => ["GET", "/api/v1/staging/records", page(items, total)];
const form = (name: string) => screen.getByRole("form", { name });
const dialog = (name: string) => screen.getByRole("dialog", { name });
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
/** Campo cuyo rótulo (primer texto del <label>) es exactamente `label`; los asteriscos y mensajes de error van aparte. */
const field = (scope: HTMLElement, label: string) => {
  const found = Array.from(scope.querySelectorAll("label")).find((l) => l.firstChild?.textContent === label);
  if (!found) throw new Error(`Sin campo «${label}»`);
  return found.querySelector("input,select,textarea") as HTMLInputElement;
};
const created = (resource: string, externalId: string, payload: Record<string, unknown>) => ({ id: `new-${externalId}`, external_id: externalId, source: "virtualpos1", resource_type: resource, payload });
const csrfRefreshes = (app: { find: (m: string, p: string) => Call[] }) => app.find("GET", "/api/v1/auth/me").length;

describe("Clientes VirtualPOS: editar", () => {
  it("sin cambios avisa; con cambios envía solo lo modificado (PUT), actualiza la fila y muestra el aviso", async () => {
    const app = mountApp("/virtualpos/clientes", [
      records([vpClient(1)]),
      ["PUT", "/api/v1/writes/virtualpos/clients/cli-1", (call: Call) => ({ payload: { ...vpClient(1).payload, ...(call.body as object) } })],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar cliente VirtualPOS");
    expect(within(f).getByText("Editar cliente")).toBeTruthy();
    expect(within(f).getByText("cli-1")).toBeTruthy();
    expect(within(f).getByText(/Los cambios se aplican mediante la API interna/)).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.submit(f);
    expect(await within(f).findByText("No hay cambios para guardar.")).toBeTruthy();
    expect(app.find("PUT", "/api/v1")).toHaveLength(0);
    type(field(f, "Nombre"), "Nuevo");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("PUT", "/api/v1/writes/virtualpos/clients/cli-1")).toHaveLength(1));
    expect(app.find("PUT", "/api/v1/writes/virtualpos/clients/cli-1")[0].body).toEqual({ first_name: "Nuevo" });
    expect(await screen.findByText("Nuevo Sintética")).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Editar cliente VirtualPOS" })).toBeNull();
    // Hallazgo 3 de UX-04 (corregido): antes el efecto que limpia los avisos se disparaba al cerrar el
    // diálogo y borraba este aviso al instante; ahora solo se limpia al abrir un diálogo.
    expect(await screen.findByText("Cambios guardados correctamente.")).toBeTruthy();
    expect(csrfRefreshes(app)).toBeGreaterThan(1);
  });

  it("el aviso de guardado de cliente se limpia al abrir de nuevo un diálogo de cliente", async () => {
    mountApp("/virtualpos/clientes", [
      records([vpClient(1)]),
      ["PUT", "/api/v1/writes/virtualpos/clients/cli-1", { payload: { ...vpClient(1).payload, first_name: "Nuevo" } }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    let f = form("Editar cliente VirtualPOS");
    type(field(f, "Nombre"), "Nuevo");
    fireEvent.submit(f);
    expect(await screen.findByText("Cambios guardados correctamente.")).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByText("Cambios guardados correctamente.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Editar" }));
    f = form("Editar cliente VirtualPOS");
    expect(screen.queryByText("Cambios guardados correctamente.")).toBeNull();
    expect(f).toBeTruthy();
  });

  it("valida RUT y correo antes de enviar", async () => {
    const app = mountApp("/virtualpos/clientes", [records([vpClient(1)])]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar cliente VirtualPOS");
    type(field(f, "RUT / documento"), "11111111-9");
    fireEvent.submit(f);
    expect(await within(f).findByText("El RUT no es válido.")).toBeTruthy();
    expect(within(f).getByText("Revisa los campos marcados.")).toBeTruthy();
    type(field(f, "RUT / documento"), "11111111-1");
    type(field(f, "Correo electrónico"), "no-es-correo");
    fireEvent.submit(f);
    expect(await within(f).findByText("Ingresa un correo electrónico válido.")).toBeTruthy();
    expect(app.find("PUT", "/api/v1")).toHaveLength(0);
  });

  it("si el servidor rechaza muestra el mensaje y «Invalid RUT» se traduce al campo", async () => {
    mountApp("/virtualpos/clientes", [records([vpClient(1)]), ["PUT", "/api/v1/writes/virtualpos/clients/cli-1", failWith(400, "Invalid RUT")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar cliente VirtualPOS");
    type(field(f, "Nombre"), "Otro");
    fireEvent.submit(f);
    expect(await within(f).findByText("El RUT no es válido.")).toBeTruthy();
    expect(within(f).getByText("Revisa los campos marcados en rojo.")).toBeTruthy();
  });

  it("«Cancelar» cierra el diálogo sin enviar nada", async () => {
    const app = mountApp("/virtualpos/clientes", [records([vpClient(1)])]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.click(within(form("Editar cliente VirtualPOS")).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("form", { name: "Editar cliente VirtualPOS" })).toBeNull();
    expect(app.find("PUT", "/api/v1")).toHaveLength(0);
  });
});

describe("Clientes VirtualPOS: crear", () => {
  it("valida campos obligatorios, RUT duplicado y envía POST con la cuenta elegida", async () => {
    const app = mountApp("/virtualpos/clientes", [
      records([vpClient(1)]),
      ["POST", "/api/v1/writes/virtualpos/clients", (call: Call) => created("client", "cli-9", call.body as Record<string, unknown>)],
    ]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11111111-1" });
    fireEvent.click(screen.getByRole("button", { name: "+ Nuevo cliente" }));
    const f = form("Crear cliente VirtualPOS");
    expect(within(f).getByText("Nuevo cliente")).toBeTruthy();
    expect(within(f).getByText("Cuenta VirtualPOS:")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    type(field(f, "Tipo de documento"), "1");
    fireEvent.submit(f);
    expect(await within(f).findByText("El nombre es obligatorio.")).toBeTruthy();
    expect(within(f).getByText("El correo electrónico es obligatorio.")).toBeTruthy();
    expect(within(f).getByText("El número de documento es obligatorio.")).toBeTruthy();
    expect(within(f).getByText("Revisa los campos marcados en rojo.")).toBeTruthy();
    type(field(f, "Nombre"), "Persona");
    type(field(f, "Correo electrónico"), "nueva@example.invalid");
    type(field(f, "RUT / documento"), "11111111-1");
    fireEvent.submit(f);
    expect(await within(f).findByText("Ya existe un cliente con este documento en el listado actual.")).toBeTruthy();
    type(field(f, "RUT / documento"), "22222222-2");
    fireEvent.click(within(f).getByRole("button", { name: "Cuenta 2" }));
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/virtualpos/clients")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/writes/virtualpos/clients")[0].body).toMatchObject({ first_name: "Persona", email: "nueva@example.invalid", social_id: "22222222-2", social_id_type: "1", status: "ACTIVO", type: "PERSONA", platform: "virtualpos2" });
    expect(await screen.findByText("2 registros")).toBeTruthy();
    // Hallazgo 3 de UX-04 (corregido): el aviso de creación ya no se borra al cerrar el diálogo.
    expect(await screen.findByText("Cliente creado correctamente.")).toBeTruthy();
  });
});

describe("Planes y suscripciones VirtualPOS: crear", () => {
  it("plan: valida obligatorios y rangos y envía POST con tipos numéricos y booleanos", async () => {
    const app = mountApp("/virtualpos/planes", [
      records([vpPlan(1)]),
      ["POST", "/api/v1/writes/virtualpos/plans", (call: Call) => created("plan", "plan-9", call.body as Record<string, unknown>)],
    ]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de plan Plan Sintético 1" });
    fireEvent.click(screen.getByRole("button", { name: "+ Nuevo plan" }));
    const f = form("Crear plan VirtualPOS");
    expect(within(f).getByText("Nuevo plan")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.submit(f);
    expect(await within(f).findByText("El nombre del plan es obligatorio.")).toBeTruthy();
    expect(within(f).getByText("Ingresa un monto válido (número ≥ 0).")).toBeTruthy();
    type(field(f, "Nombre del plan"), "Plan Nuevo");
    type(field(f, "Monto"), "7500");
    type(field(f, "Día de cobro del mes (1-28)"), "31");
    fireEvent.submit(f);
    expect(await within(f).findByText("El día de cobro debe ser entre 1 y 28.")).toBeTruthy();
    type(field(f, "Día de cobro del mes (1-28)"), "15");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/virtualpos/plans")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/writes/virtualpos/plans")[0].body).toEqual({
      platform: "virtualpos1", name: "Plan Nuevo", amount: 7500, currency: "CLP", frequency_type: "monthly", fixed_amount_day_charge: 15,
      automatic_renewal: true, show_in_terminal: false, is_active: true,
    });
    expect(await screen.findByText("Plan creado correctamente.")).toBeTruthy();
  });

  it("suscripción: valida obligatorios y envía POST", async () => {
    const app = mountApp("/virtualpos/suscripciones", [
      records([vpSubscription(1)]),
      ["POST", "/api/v1/writes/virtualpos/subscriptions", (call: Call) => created("subscription", "sub-9", call.body as Record<string, unknown>)],
    ]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de suscripción 11111111-1" });
    fireEvent.click(screen.getByRole("button", { name: "+ Nueva suscripción" }));
    const f = form("Crear suscripción VirtualPOS");
    fireEvent.submit(f);
    expect(await within(f).findByText("El ID del plan es obligatorio.")).toBeTruthy();
    expect(within(f).getByText("El RUT es obligatorio.")).toBeTruthy();
    type(field(f, "ID del plan"), "plan-1");
    type(field(f, "Correo electrónico del cliente"), "s@example.invalid");
    type(field(f, "Nombre"), "Persona");
    type(field(f, "Apellido"), "Nueva");
    type(field(f, "RUT"), "33333333-3");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/virtualpos/subscriptions")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/writes/virtualpos/subscriptions")[0].body).toEqual({
      platform: "virtualpos1", plan_id: "plan-1", email: "s@example.invalid", first_name: "Persona", last_name: "Nueva", social_id: "33333333-3",
    });
    expect(await screen.findByText("Suscripción creada correctamente.")).toBeTruthy();
  });
});

describe("Suscripciones VirtualPOS: cancelar y crear cargo", () => {
  it("lista: «Cancelar Sub» abre la confirmación, envía DELETE y marca la fila", async () => {
    const app = mountApp("/virtualpos/suscripciones", [
      records([vpSubscription(1)]),
      ["DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1", { external_id: "sub-1", status: "CANCELADA" }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar Sub" }));
    const d = dialog("Cancelar suscripción VirtualPOS");
    expect(within(d).getByText("¿Estás seguro de cancelar esta suscripción?")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar cancelación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Cancelar suscripción VirtualPOS" })).toBeNull());
    expect(screen.getByText("Cancelada")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancelar Sub" })).toBeNull();
  });

  it("lista: si el DELETE falla muestra el error en el diálogo y permite «Volver»", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)]), ["DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1", failWith(502, "proveedor caído")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar Sub" }));
    const d = dialog("Cancelar suscripción VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar cancelación" }));
    expect(await within(d).findByText("proveedor caído")).toBeTruthy();
    fireEvent.click(within(d).getByRole("button", { name: "Volver" }));
    expect(screen.queryByRole("dialog", { name: "Cancelar suscripción VirtualPOS" })).toBeNull();
  });

  it("lista: «+ Cargo» valida fecha pasada y monto y envía POST a /subscriptions/{id}/charges", async () => {
    const app = mountApp("/virtualpos/suscripciones", [
      records([vpSubscription(1)]),
      ["POST", "/api/v1/writes/virtualpos/subscriptions/sub-1/charges", (call: Call) => created("charge", "chg-9", call.body as Record<string, unknown>)],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "+ Cargo" }));
    const f = form("Crear cargo VirtualPOS");
    expect(within(f).getByText("Sub: sub-1")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.submit(f);
    expect(await within(f).findByText("La fecha del cargo es obligatoria.")).toBeTruthy();
    expect(within(f).getByText("Ingresa un monto válido (número ≥ 1).")).toBeTruthy();
    type(f.querySelector('[name="charge_date"]') as HTMLElement, "2020-01-01");
    type(f.querySelector('[name="amount"]') as HTMLElement, "9990");
    fireEvent.submit(f);
    expect(await within(f).findByText("La fecha del cargo no puede ser una fecha pasada.")).toBeTruthy();
    const future = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
    type(f.querySelector('[name="charge_date"]') as HTMLElement, future);
    type(f.querySelector('[name="description"]') as HTMLElement, "Cuota sintética");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/virtualpos/subscriptions/sub-1/charges")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/writes/virtualpos/subscriptions/sub-1/charges")[0].body).toEqual({ charge_date: future, amount: 9990, description: "Cuota sintética" });
    expect(await screen.findByText("Cargo creado correctamente (ID: chg-9).")).toBeTruthy();
  });

  it("ficha de suscripción: cancelar actualiza el estado en la ficha", async () => {
    const detail = { subscription: vpSubscription(1), payment_method: null, charges: [], charge_total: 0, payments: [], payment_total: 0 };
    const app = mountApp("/virtualpos/suscripciones/sub-1", [
      records([]),
      ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-1", detail],
      ["DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1", { external_id: "sub-1", status: "CANCELADA" }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar Sub" }));
    fireEvent.click(within(dialog("Cancelar suscripción VirtualPOS")).getByRole("button", { name: "Confirmar cancelación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Cancelar Sub" })).toBeNull());
    expect(screen.getByText("Cancelada")).toBeTruthy();
  });
});

describe("Cargos VirtualPOS: cancelar y reintentar", () => {
  it("cancelar: confirma, envía DELETE, marca la fila y avisa", async () => {
    const app = mountApp("/virtualpos/cargos", [
      records([vpCharge(1, "pendiente")]),
      ["DELETE", "/api/v1/writes/virtualpos/charges/chg-1", { external_id: "chg-1", status: "cancelado" }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    const d = dialog("Cancelar cargo VirtualPOS");
    expect(within(d).getByText("Cancelar cargo")).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar cancelación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/virtualpos/charges/chg-1")).toHaveLength(1));
    expect(await screen.findByText("Cargo chg-1 cancelado.")).toBeTruthy();
    expect(screen.getByText("Cancelado")).toBeTruthy();
  });

  it("reintentar: confirma, envía POST …/retry y deja el cargo en «procesando» si volvió «rechazado»", async () => {
    const app = mountApp("/virtualpos/cargos", [
      records([vpCharge(2, "rechazado")]),
      ["POST", "/api/v1/writes/virtualpos/charges/chg-2/retry", { external_id: "chg-2", status: "rechazado", payload: { id: "chg-2", status: "rechazado", amount: 10000, charge_date: "2025-04-05" } }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    const d = dialog("Reintentar cargo VirtualPOS");
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar reintento" }));
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/virtualpos/charges/chg-2/retry")).toHaveLength(1));
    expect(await screen.findByText("Cargo chg-2 reintentado.")).toBeTruthy();
    expect(screen.getByText("Procesando")).toBeTruthy();
  });

  it("reintentar: si falla muestra el error en el diálogo", async () => {
    mountApp("/virtualpos/cargos", [records([vpCharge(2, "rechazado")]), ["POST", "/api/v1/writes/virtualpos/charges/chg-2/retry", failWith(409, "ya reintentado hoy")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    const d = dialog("Reintentar cargo VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar reintento" }));
    expect(await within(d).findByText("ya reintentado hoy")).toBeTruthy();
  });
});

describe("Toku y Payku: editar, eliminar y cambiar estado", () => {
  it("Toku cliente: editar envía PUT con solo lo modificado y actualiza la fila", async () => {
    const app = mountApp("/toku/clientes", [
      records([tokuCustomer(1)]),
      ["PUT", "/api/v1/writes/toku/customers/tcu-1", (call: Call) => ({ external_id: "tcu-1", payload: { ...tokuCustomer(1).payload, ...(call.body as object) } })],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar Cliente");
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    type(field(f, "Nombre"), "Cliente Renombrado");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("PUT", "/api/v1/writes/toku/customers/tcu-1")).toHaveLength(1));
    expect(app.find("PUT", "/api/v1/writes/toku/customers/tcu-1")[0].body).toEqual({ name: "Cliente Renombrado" });
    expect(await screen.findByText("Cliente Renombrado")).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Editar Cliente" })).toBeNull();
  });

  it("Toku cliente: editar sin cambios cierra el diálogo sin enviar", async () => {
    const app = mountApp("/toku/clientes", [records([tokuCustomer(1)])]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.submit(form("Editar Cliente"));
    await waitFor(() => expect(screen.queryByRole("form", { name: "Editar Cliente" })).toBeNull());
    expect(app.find("PUT", "/api/v1")).toHaveLength(0);
  });

  it("Toku cliente: eliminar envía DELETE y marca el registro como «deleted»", async () => {
    const app = mountApp("/toku/clientes", [records([tokuCustomer(1)]), ["DELETE", "/api/v1/writes/toku/customers/tcu-1", { external_id: "tcu-1", status: "deleted" }]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Eliminar" }));
    const d = dialog("Eliminar Cliente");
    expect(within(d).getByText(/Se enviará DELETE \/customers\/tcu-1 a Toku\. Esta acción no se puede deshacer\./)).toBeTruthy();
    await listSettled();
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar eliminación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/toku/customers/tcu-1")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Eliminar Cliente" })).toBeNull());
  });

  it("Toku suscripción: «Eliminar» en la lista abre un diálogo de solo lectura (sin envío habilitado)", async () => {
    mountApp("/toku/suscripciones", [records([tokuSubscription(1)])]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Eliminar" }));
    const d = dialog("Eliminar Suscripción");
    expect(within(d).getByText(/permanece en modo solo lectura/)).toBeTruthy();
    expect((within(d).getByRole("button", { name: "Confirmar eliminación" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(d).getByRole("button", { name: "Volver" }));
    expect(screen.queryByRole("dialog", { name: "Eliminar Suscripción" })).toBeNull();
  });

  it("Toku suscripción: «Gestionar estado» desde la ficha envía POST …/status y actualiza el estado", async () => {
    const app = mountApp("/toku/suscripciones/tsu-1", [
      records([]),
      ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1), related: [] }],
      ["POST", "/api/v1/writes/toku/subscriptions/tsu-1/status", { external_id: "tsu-1", status: "PAUSED", payload: { id: "tsu-1" } }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Gestionar estado" }));
    const f = form("Gestionar estado suscripción Toku");
    await listSettled();
    expect(Array.from(f.querySelectorAll('[name="status"] option')).map((o) => [o.getAttribute("value"), o.textContent])).toEqual([
      ["", "Seleccionar..."], ["ACTIVE", "Activa — Activar"], ["PAUSED", "Pausada — Pausar"], ["CANCELLED", "Cancelada — Cancelar"],
    ]);
    expect(contentHtml()).toMatchSnapshot();
    fireEvent.submit(f);
    expect(await within(f).findByText("Selecciona un estado.")).toBeTruthy();
    type(f.querySelector('[name="status"]') as HTMLElement, "PAUSED");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("POST", "/api/v1/writes/toku/subscriptions/tsu-1/status")).toHaveLength(1));
    expect(app.find("POST", "/api/v1/writes/toku/subscriptions/tsu-1/status")[0].body).toEqual({ status: "PAUSED" });
    await waitFor(() => expect(screen.queryByRole("form", { name: "Gestionar estado suscripción Toku" })).toBeNull());
  });

  it("Payku cliente: editar envía PUT a /writes/payku/clients/{id}; eliminar envía DELETE", async () => {
    const app = mountApp("/payku/clientes", [
      records([paykuClient(1)]),
      ["PUT", "/api/v1/writes/payku/clients/pcl-1", (call: Call) => ({ external_id: "pcl-1", payload: { ...paykuClient(1).payload, ...(call.body as object) } })],
      ["DELETE", "/api/v1/writes/payku/clients/pcl-1", { external_id: "pcl-1", status: "deleted" }],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar Cliente");
    type(field(f, "Nombre"), "Payku Renombrado");
    fireEvent.submit(f);
    await waitFor(() => expect(app.find("PUT", "/api/v1/writes/payku/clients/pcl-1")).toHaveLength(1));
    expect(await screen.findByText("Payku Renombrado")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    fireEvent.click(within(dialog("Eliminar Cliente")).getByRole("button", { name: "Confirmar eliminación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/payku/clients/pcl-1")).toHaveLength(1));
  });

  it("Payku suscripción: eliminar envía DELETE y deja el estado «cancelled»", async () => {
    const app = mountApp("/payku/suscripciones", [records([paykuSubscription(1)]), ["DELETE", "/api/v1/writes/payku/subscriptions/psu-1", { external_id: "psu-1", status: "cancelled" }]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Eliminar" }));
    fireEvent.click(within(dialog("Eliminar Suscripción")).getByRole("button", { name: "Confirmar eliminación" }));
    await waitFor(() => expect(app.find("DELETE", "/api/v1/writes/payku/subscriptions/psu-1")).toHaveLength(1));
    expect(await screen.findByText("Cancelada")).toBeTruthy();
  });

  it("registro de otro recurso (Toku factura): editar es solo visual y el guardado está deshabilitado", async () => {
    const invoice = rec("toku", "invoice", "tin-1", { id: "tin-1", amount: 5000, status: "UNPAID", due_date: "2025-04-01", is_paid: false }, { client_rut: "22222221-2", client_name: "Cliente Toku 1" });
    mountApp("/toku/deudas/tin-1", [records([]), ["GET", "/api/v1/staging/toku/invoice/tin-1", { record: invoice, related: [] }]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar Deuda");
    expect(within(f).getByText(/Formulario visual\. El guardado remoto permanece deshabilitado/)).toBeTruthy();
    expect((within(f).getByRole("button", { name: "Guardar cambios" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
