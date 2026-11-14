/**
 * Errores de escritura y de staging en pantalla (decisión D35): el backend responde `detail` = {code, message} y la
 * interfaz muestra el texto en español del catálogo por código (nunca el texto genérico del estado HTTP ni el
 * `message` del servidor cuando el código está en el catálogo). Todas las peticiones están simuladas; datos sintéticos.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { appReady, failWith, mountApp, resetApp, type Handler } from "./appHarness";
import { page, paykuClient, paykuSubscription, tokuCustomer, tokuSubscription, vpCharge, vpClient, vpSubscription } from "./fixtures";

afterEach(resetApp);

const SERVER_TEXT = "texto de respaldo del servidor";
const records = (items: unknown[]): Handler => ["GET", "/api/v1/staging/records", page(items, items.length)];
const form = (name: string) => screen.getByRole("form", { name });
const dialog = (name: string) => screen.getByRole("dialog", { name });
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
const field = (scope: HTMLElement, label: string) => {
  const found = Array.from(scope.querySelectorAll("label")).find((l) => l.firstChild?.textContent === label);
  if (!found) throw new Error(`Sin campo «${label}»`);
  return found.querySelector("input,select,textarea") as HTMLInputElement;
};
/** Respuesta de error con detalle estructurado; el `message` del servidor es distinto del texto del catálogo. */
const coded = (status: number, code: string) => failWith(status, { code, message: SERVER_TEXT });
const GENERIC_BY_STATUS: Record<number, string> = {
  404: "El recurso solicitado no fue encontrado.",
  409: "La operación entra en conflicto con el estado actual. Actualiza e inténtalo de nuevo.",
  502: "El servicio externo no respondió correctamente. Inténtalo más tarde.",
  503: "El servicio no está disponible temporalmente. Inténtalo más tarde.",
};
/** Ni el `message` del servidor ni el texto genérico del estado HTTP aparecen cuando el código está en el catálogo. */
const expectSpecific = (scope: HTMLElement, status: number) => {
  expect(within(scope).queryByText(SERVER_TEXT)).toBeNull();
  const generic = GENERIC_BY_STATUS[status];
  if (generic) expect(within(scope).queryByText(generic)).toBeNull();
};

describe("VirtualPOS: errores de escritura con detalle {code, message}", () => {
  it("cliente nuevo: documento duplicado en el proveedor (409) muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/clientes", [records([vpClient(1)]), ["POST", "/api/v1/writes/virtualpos/clients", coded(409, "virtualpos_client_duplicate_document")]]);
    await appReady();
    await screen.findByRole("button", { name: "Ver ficha de cliente 11.111.111-1" });
    fireEvent.click(screen.getByRole("button", { name: "+ Nuevo cliente" }));
    const f = form("Crear cliente VirtualPOS");
    type(field(f, "Tipo de documento"), "1");
    type(field(f, "Nombre"), "Persona");
    type(field(f, "Correo electrónico"), "nueva@example.invalid");
    type(field(f, "RUT / documento"), "22222222-2");
    fireEvent.submit(f);
    expect(await within(f).findByText("Ya existe un cliente con ese documento de identidad en VirtualPOS.")).toBeTruthy();
    expectSpecific(f, 409);
  });

  it("cliente: editar con las escrituras deshabilitadas (403) muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/clientes", [records([vpClient(1)]), ["PUT", "/api/v1/writes/virtualpos/clients/cli-1", coded(403, "virtualpos_writes_disabled")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar cliente VirtualPOS");
    type(field(f, "Nombre"), "Otro");
    fireEvent.submit(f);
    expect(await within(f).findByText("Las escrituras a VirtualPOS están deshabilitadas en este ambiente.")).toBeTruthy();
    expectSpecific(f, 403);
  });

  it("plan nuevo: VirtualPOS lo rechaza (502) y se muestra el texto específico, no el genérico", async () => {
    mountApp("/virtualpos/planes", [records([]), ["POST", "/api/v1/writes/virtualpos/plans", coded(502, "virtualpos_rejected_plan")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "+ Nuevo plan" }));
    const f = form("Crear plan VirtualPOS");
    type(field(f, "Nombre del plan"), "Plan Nuevo");
    type(field(f, "Monto"), "7500");
    type(field(f, "Día de cobro del mes (1-28)"), "15");
    fireEvent.submit(f);
    expect(await within(f).findByText("VirtualPOS rechazó el plan.")).toBeTruthy();
    expectSpecific(f, 502);
  });

  it("suscripción nueva: pendiente de conciliación (503) muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)]), ["POST", "/api/v1/writes/virtualpos/subscriptions", coded(503, "subscription_requires_reconciliation")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "+ Nueva suscripción" }));
    const f = form("Crear suscripción VirtualPOS");
    type(field(f, "ID del plan"), "plan-1");
    type(field(f, "Correo electrónico del cliente"), "s@example.invalid");
    type(field(f, "Nombre"), "Persona");
    type(field(f, "Apellido"), "Nueva");
    type(field(f, "RUT"), "33333333-3");
    fireEvent.submit(f);
    expect(await within(f).findByText(/La suscripción se creó en el proveedor, pero quedó pendiente de conciliación/)).toBeTruthy();
    expectSpecific(f, 503);
  });

  it("cargo nuevo desde la suscripción: listado incompleto (502) muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)]), ["POST", "/api/v1/writes/virtualpos/subscriptions/sub-1/charges", coded(502, "virtualpos_charge_listing_incomplete")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "+ Cargo" }));
    const f = form("Crear cargo VirtualPOS");
    const future = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
    type(f.querySelector('[name="charge_date"]') as HTMLElement, future);
    type(f.querySelector('[name="amount"]') as HTMLElement, "9990");
    fireEvent.submit(f);
    expect(await within(f).findByText(/No se pudo leer completo el listado de cobros de VirtualPOS/)).toBeTruthy();
    expectSpecific(f, 502);
  });

  it("cancelar suscripción: pendiente de conciliación (503) se muestra en el diálogo", async () => {
    mountApp("/virtualpos/suscripciones", [records([vpSubscription(1)]), ["DELETE", "/api/v1/writes/virtualpos/subscriptions/sub-1", coded(503, "cancellation_requires_reconciliation")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar Sub" }));
    const d = dialog("Cancelar suscripción VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar cancelación" }));
    expect(await within(d).findByText(/La cancelación se hizo en el proveedor, pero quedó pendiente de conciliación/)).toBeTruthy();
    expectSpecific(d, 503);
  });

  it("cancelar cargo: cargo inexistente (404) muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/cargos", [records([vpCharge(1, "pendiente")]), ["DELETE", "/api/v1/writes/virtualpos/charges/chg-1", coded(404, "charge_not_found")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    const d = dialog("Cancelar cargo VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar cancelación" }));
    expect(await within(d).findByText("No se encontró el cargo.")).toBeTruthy();
    expectSpecific(d, 404);
  });

  it("reintentar cargo: VirtualPOS rechaza el reintento (409) y se muestra el texto del catálogo", async () => {
    mountApp("/virtualpos/cargos", [records([vpCharge(2, "rechazado")]), ["POST", "/api/v1/writes/virtualpos/charges/chg-2/retry", coded(409, "virtualpos_rejected_charge_retry")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    const d = dialog("Reintentar cargo VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar reintento" }));
    expect(await within(d).findByText("VirtualPOS rechazó el reintento del cargo.")).toBeTruthy();
    expectSpecific(d, 409);
  });
});

describe("Toku y Payku: errores de escritura con detalle {code, message}", () => {
  it("Toku cliente: editar bloqueado por las guardas de ambiente (403)", async () => {
    mountApp("/toku/clientes", [records([tokuCustomer(1)]), ["PUT", "/api/v1/writes/toku/customers/tcu-1", coded(403, "toku_write_blocked")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar Cliente");
    type(field(f, "Nombre"), "Cliente Renombrado");
    fireEvent.submit(f);
    expect(await within(f).findByText("Toku bloqueó la escritura por las protecciones de este ambiente.")).toBeTruthy();
    expectSpecific(f, 403);
  });

  it("Toku cliente: eliminar con el rechazo del proveedor (502) muestra el texto del catálogo", async () => {
    mountApp("/toku/clientes", [records([tokuCustomer(1)]), ["DELETE", "/api/v1/writes/toku/customers/tcu-1", coded(502, "toku_rejected_deletion")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Eliminar" }));
    const d = dialog("Eliminar Cliente");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar eliminación" }));
    expect(await within(d).findByText("Toku rechazó la eliminación.")).toBeTruthy();
    expectSpecific(d, 502);
  });

  it("Toku suscripción: cambiar estado y Toku lo rechaza (502)", async () => {
    mountApp("/toku/suscripciones/tsu-1", [
      records([]),
      ["GET", "/api/v1/staging/toku/subscription/tsu-1", { record: tokuSubscription(1), related: [] }],
      ["POST", "/api/v1/writes/toku/subscriptions/tsu-1/status", coded(502, "toku_rejected_status_change")],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Gestionar estado" }));
    const f = form("Gestionar estado suscripción Toku");
    type(f.querySelector('[name="status"]') as HTMLElement, "PAUSED");
    fireEvent.submit(f);
    expect(await within(f).findByText("Toku rechazó el cambio de estado.")).toBeTruthy();
    expectSpecific(f, 502);
  });

  it("Payku cliente: editar con las escrituras deshabilitadas (403)", async () => {
    mountApp("/payku/clientes", [records([paykuClient(1)]), ["PUT", "/api/v1/writes/payku/clients/pcl-1", coded(403, "payku_writes_disabled")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const f = form("Editar Cliente");
    type(field(f, "Nombre"), "Payku Renombrado");
    fireEvent.submit(f);
    expect(await within(f).findByText("Las escrituras a Payku están deshabilitadas en este ambiente.")).toBeTruthy();
    expectSpecific(f, 403);
  });

  it("Payku suscripción: eliminar con el rechazo del proveedor (502)", async () => {
    mountApp("/payku/suscripciones", [records([paykuSubscription(1)]), ["DELETE", "/api/v1/writes/payku/subscriptions/psu-1", coded(502, "payku_rejected_cancellation")]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Eliminar" }));
    const d = dialog("Eliminar Suscripción");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar eliminación" }));
    expect(await within(d).findByText("Payku rechazó la cancelación.")).toBeTruthy();
    expectSpecific(d, 502);
  });
});

describe("Código desconocido: se muestra el message del backend; sin message, el texto genérico", () => {
  async function openRetryDialog(reply: unknown) {
    mountApp("/virtualpos/cargos", [records([vpCharge(2, "rechazado")]), ["POST", "/api/v1/writes/virtualpos/charges/chg-2/retry", reply]]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    const d = dialog("Reintentar cargo VirtualPOS");
    fireEvent.click(within(d).getByRole("button", { name: "Confirmar reintento" }));
    return d;
  }

  it("código nuevo con message en español", async () => {
    const d = await openRetryDialog(failWith(409, { code: "codigo_nuevo", message: "Mensaje nuevo en español." }));
    expect(await within(d).findByText("Mensaje nuevo en español.")).toBeTruthy();
  });

  it("código nuevo sin message: texto genérico del estado HTTP", async () => {
    const d = await openRetryDialog(failWith(409, { code: "codigo_nuevo" }));
    expect(await within(d).findByText(GENERIC_BY_STATUS[409])).toBeTruthy();
  });
});

describe("Staging y programador", () => {
  it("la ficha de un registro inexistente muestra el texto del catálogo (404 virtualpos_subscription_not_found)", async () => {
    mountApp("/virtualpos/suscripciones/sub-9", [records([]), ["GET", "/api/v1/staging/virtualpos/subscriptions/sub-9", coded(404, "virtualpos_subscription_not_found")]]);
    await appReady();
    expect(await screen.findByText("No se encontró la suscripción en VirtualPOS.")).toBeTruthy();
    expect(screen.queryByText(SERVER_TEXT)).toBeNull();
  });

  it("programador: iniciar una sincronización cuando ya hay otra activa (409) muestra el texto del catálogo", async () => {
    mountApp("/admin/sincronizaciones", [
      ["GET", "/api/v1/scheduler/jobs", [{ id: "sync_all_channels", name: "Sincronización sintética", cron: "0 3 * * *", next_run: null, last_run: null, status: "scheduled" }]],
      ["GET", "/api/v1/scheduler/runs", { total: 0, items: [] }],
      ["POST", "/api/v1/scheduler/jobs/sync_all_channels/run", coded(409, "sync_already_active")],
    ]);
    await appReady();
    fireEvent.click(await screen.findByRole("button", { name: /^Sincronizar/ }));
    // 13D: lanzar un proceso pide confirmación (mismo patrón que «Sync completo»).
    fireEvent.click(await screen.findByRole("button", { name: "Sí, ejecutar" }));
    await waitFor(() => expect(document.querySelector(".scheduler-error")?.textContent).toBe("Ya hay una sincronización en curso. Espera a que termine."));
  });
});
