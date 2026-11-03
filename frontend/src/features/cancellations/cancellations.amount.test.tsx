import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn(), getBlob: vi.fn(), saveBlob: vi.fn() }));
vi.mock("../../api", () => ({
  getJson: mocks.getJson, postJson: mocks.postJson, getBlob: mocks.getBlob, saveBlob: mocks.saveBlob,
  friendlyError: (_e: unknown, f: string) => f,
}));
vi.mock("../shared/utils", () => ({ refreshCsrfToken: vi.fn() }));

import { CancellationsInbox } from "./CancellationsInbox";
import { parseAmount, taskActions, type ManualTask } from "./manualTasks";

const VIEW = "subscriptions.cancellation.view";
const TASKS_VIEW = "subscriptions.manual_tasks.view";
const TASKS_CONFIRM = "subscriptions.manual_tasks.confirm";
const BILLING_REQUEST = "virtualpos.billing_changes.request";
const canOf = (perms: string[]) => (p: string) => perms.includes(p);
const apiError = (status: number, detail: unknown) => Object.assign(new Error("texto crudo del servidor"), { status, detail });

function task(over: Partial<ManualTask> = {}): ManualTask {
  return {
    id: "t1", task_type: "tch_bank_mandate", channel: "tch", subscription_external_id: "910001", status: "pending",
    cancellation_request_id: "r1", target_amount: null, previous_amount: null, created_by: "ana", assigned_to_user_id: "u1",
    assigned_to: "ana", confirmed_by_user_id: null, confirmed_by: null, confirmed_at: null, confirmation_comment: null,
    verified_at: null, verification_source: null, dismissed_by: null, dismissed_at: null, dismiss_comment: null,
    code: "TCH_BANK_MANDATE_OUTSIDE_CRM", created_at: "2026-11-02T10:00:00+00:00", ...over,
  };
}

let tasks: ManualTask[] = [];

beforeEach(() => {
  mocks.getJson.mockReset();
  mocks.postJson.mockReset();
  mocks.getBlob.mockReset();
  mocks.saveBlob.mockReset();
  tasks = [task(), task({ id: "t2", task_type: "payku_amount_change", channel: "payku", subscription_external_id: "sus_1", target_amount: 15000, previous_amount: 9900, code: "PAYKU_AMOUNT_NO_API" })];
  mocks.getJson.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/cancellations?")) return { items: [], total: 0, limit: 25, offset: 0 };
    if (path.startsWith("/api/v1/manual-tasks?")) return { items: tasks, total: tasks.length, limit: 25, offset: 0 };
    throw new Error(`ruta no mockeada ${path}`);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Tareas manuales (MGT-11/13/14)", () => {
  it("la pestaña solo aparece con el permiso de ver tareas", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("tab", { name: "Historial" });
    expect(screen.queryByRole("tab", { name: "Tareas manuales" })).toBeNull();
    cleanup();
    render(<CancellationsInbox can={canOf([VIEW, TASKS_VIEW])} />);
    expect(await screen.findByRole("tab", { name: "Tareas manuales" })).toBeTruthy();
  });

  it("lista las tareas abiertas en español y sin acciones para quien solo ve", async () => {
    render(<CancellationsInbox can={canOf([VIEW, TASKS_VIEW])} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tareas manuales" }));
    expect(await screen.findByText("Revocar mandato TCH en el banco")).toBeTruthy();
    expect(screen.getByText("Cambiar monto en Payku")).toBeTruthy();
    expect(screen.getAllByText("Pendiente").length).toBe(2);
    expect(screen.queryByRole("button", { name: "Confirmar que lo hice" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Descargar bajas TCH/ })).toBeNull();
    expect(mocks.getJson.mock.calls.some((c) => String(c[0]).includes("status=pending&status=confirmed"))).toBe(true);
  });

  it("confirmar registra la acción manual y recarga la lista", async () => {
    mocks.postJson.mockResolvedValueOnce({ ...task(), status: "confirmed", confirmed_by: "luis" });
    render(<CancellationsInbox can={canOf([VIEW, TASKS_VIEW, TASKS_CONFIRM])} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tareas manuales" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Confirmar que lo hice" }))[0]);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/queda registrado que usted hizo la acción manual/)).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Revocado en el banco" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    await screen.findByText(/quedó registrado su usuario y la fecha/);
    expect(mocks.postJson).toHaveBeenCalledWith("/api/v1/manual-tasks/t1/confirm", { comment: "Revocado en el banco" });
  });

  it("descartar exige motivo y muestra errores del catálogo, no del servidor", async () => {
    mocks.postJson.mockRejectedValueOnce(apiError(409, { code: "invalid_task_state", message: "texto crudo" }));
    render(<CancellationsInbox can={canOf([VIEW, TASKS_VIEW, TASKS_CONFIRM])} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tareas manuales" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Descartar" }))[0]);
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Descartar" }));
    expect(within(dialog).getByText("El comentario es obligatorio.")).toBeTruthy();
    expect(mocks.postJson).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Ya no aplica" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Descartar" }));
    expect(await within(dialog).findByText(/La tarea cambió de estado/)).toBeTruthy();
    expect(screen.queryByText("texto crudo")).toBeNull();
  });

  it("descarga el CSV de bajas TCH en trámite", async () => {
    const blob = new Blob(["a"]);
    mocks.getBlob.mockResolvedValueOnce({ blob, filename: "bajas_tch_en_tramite.csv" });
    render(<CancellationsInbox can={canOf([VIEW, TASKS_VIEW, TASKS_CONFIRM])} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tareas manuales" }));
    fireEvent.click(await screen.findByRole("button", { name: /Descargar bajas TCH en trámite/ }));
    await waitFor(() => expect(mocks.saveBlob).toHaveBeenCalledWith(blob, "bajas_tch_en_tramite.csv"));
    expect(mocks.getBlob).toHaveBeenCalledWith("/api/v1/manual-tasks/tch-export");
  });

  it("acciones por estado y permiso", () => {
    const can = canOf([TASKS_CONFIRM]);
    expect(taskActions({ status: "pending" }, can)).toEqual({ confirm: true, dismiss: true });
    expect(taskActions({ status: "confirmed" }, can)).toEqual({ confirm: false, dismiss: true });
    expect(taskActions({ status: "verified" }, can)).toEqual({ confirm: false, dismiss: false });
    expect(taskActions({ status: "pending" }, canOf([]))).toEqual({ confirm: false, dismiss: false });
  });
});

describe("Cambiar monto por canal (MGT-15)", () => {
  it("el botón solo aparece con el permiso de solicitar cambios de cobro", async () => {
    render(<CancellationsInbox can={canOf([VIEW])} />);
    await screen.findByRole("tab", { name: "Historial" });
    expect(screen.queryByRole("button", { name: "Cambiar monto" })).toBeNull();
    cleanup();
    render(<CancellationsInbox can={canOf([VIEW, BILLING_REQUEST])} />);
    expect(await screen.findByRole("button", { name: "Cambiar monto" })).toBeTruthy();
  });

  it("Toku: vista previa obligatoria y luego crea la solicitud en la bandeja de cobros", async () => {
    mocks.postJson
      .mockResolvedValueOnce({ summary: { previous_amount: 9900, new_amount: 12900, variation_pct: 30.3 }, plan_preview: { toku: { invoices_to_update: 2, invoices_in_progress_skipped: 1 } }, would_self_approve: true })
      .mockResolvedValueOnce({ id: "b1", status: "aprobada" });
    render(<CancellationsInbox can={canOf([VIEW, BILLING_REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cambiar monto" }));
    const dialog = screen.getByRole("dialog");
    const send = within(dialog).getByRole("button", { name: "Enviar solicitud" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("ID de la suscripción"), { target: { value: "TEST-sub-1" } });
    fireEvent.change(within(dialog).getByLabelText("Monto nuevo (CLP)"), { target: { value: "12.900" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ver vista previa" }));
    expect(await within(dialog).findByText(/1 cuota\(s\) en proceso de cobro/)).toBeTruthy();
    expect(mocks.postJson).toHaveBeenLastCalledWith("/api/v1/billing/changes/preview",
      { request_type: "change_amount", platform: "toku", subscription_external_id: "TEST-sub-1", new_amount: 12900 });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar solicitud" }));
    expect(await screen.findByText(/creado y autoaprobado en «Cambios de cobro»/)).toBeTruthy();
    expect(mocks.postJson.mock.calls[1][0]).toBe("/api/v1/billing/changes");
  });

  it("Payku: registra una tarea manual", async () => {
    mocks.postJson.mockResolvedValueOnce(task({ task_type: "payku_amount_change" }));
    render(<CancellationsInbox can={canOf([VIEW, BILLING_REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cambiar monto" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Canal"), { target: { value: "payku" } });
    fireEvent.change(within(dialog).getByLabelText("ID de la suscripción"), { target: { value: "sus_1" } });
    fireEvent.change(within(dialog).getByLabelText("Monto nuevo (CLP)"), { target: { value: "15000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Registrar tarea manual" }));
    expect(await screen.findByText(/Tarea manual registrada/)).toBeTruthy();
    expect(mocks.postJson).toHaveBeenCalledWith("/api/v1/manual-tasks/payku-amount", { subscription_external_id: "sus_1", new_amount: 15000 });
  });

  it("VirtualPOS y TCH explican dónde se cambia el monto sin enviar nada", async () => {
    render(<CancellationsInbox can={canOf([VIEW, BILLING_REQUEST])} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cambiar monto" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Canal"), { target: { value: "virtualpos1" } });
    expect(within(dialog).getByText(/se cambia en «Cambios de cobro»/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Canal"), { target: { value: "tch" } });
    expect(within(dialog).getByText(/TCH no permite cambiar el monto desde el CRM/)).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /Enviar|Registrar/ })).toBeNull();
  });

  it("parseAmount acepta miles con punto y rechaza lo que no es un entero positivo", () => {
    expect(parseAmount("12.900")).toBe(12900);
    expect(parseAmount("$ 15000")).toBe(15000);
    expect(parseAmount("0")).toBeNull();
    expect(parseAmount("12,5")).toBeNull();
    expect(parseAmount("abc")).toBeNull();
  });
});
