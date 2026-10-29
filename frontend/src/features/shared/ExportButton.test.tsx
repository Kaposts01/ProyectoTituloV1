import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { filenameFromDisposition } from "../../api";
import { ExportButton } from "./ExportButton";
import { EXPORT_VOLUME_WARNING_ROWS } from "./exportSupport";

type Reply = { status?: number; json?: unknown; csv?: string; disposition?: string };
let replies: Record<string, Reply>;
let urls: string[];
let saved: string[];

beforeEach(() => {
  replies = {};
  urls = [];
  saved = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    urls.push(input);
    const key = input.includes("/count") ? "count" : "download";
    const r = replies[key] ?? { status: 200 };
    const status = r.status ?? 200;
    return {
      ok: status < 400,
      status,
      headers: { get: (k: string) => (k.toLowerCase() === "content-disposition" ? r.disposition ?? null : k.toLowerCase() === "content-type" ? "application/json" : null) },
      json: async () => r.json ?? {},
      blob: async () => new Blob([r.csv ?? ""], { type: "text/csv" }),
    };
  }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:sintetico"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { saved.push(this.download); });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const count = (rows: number, include_pii = false) => ({ status: 200, json: { entity: "cobros", rows, canales: ["toku"], include_pii } });
const mount = (props: Partial<Parameters<typeof ExportButton>[0]> = {}) =>
  render(<ExportButton entity="cobros" canal="toku" params={{ status: "PAID", filter_field: "id", query: "abc" }} window={{ offset: 100, limit: 100 }} {...props} />);
const openMenu = () => fireEvent.click(screen.getByRole("button", { name: /Exportar/ }));

describe("ExportButton", () => {
  it("muestra el menú con las dos opciones y es accesible", () => {
    mount();
    const trigger = screen.getByRole("button", { name: /Exportar/ });
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    openMenu();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Esta vista (con filtros)",
      "Todo el listado (con los filtros activos, sin paginación)",
    ]);
  });

  it("consulta /count con filtros y canal, muestra «N filas» y descarga con el nombre del Content-Disposition", async () => {
    replies.count = count(1234);
    replies.download = { csv: "a,b", disposition: 'attachment; filename="cobros-toku-20261029.csv"' };
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    expect(await screen.findByText("1.234 filas")).toBeTruthy();
    const countUrl = new URL(urls[0], "http://x");
    expect(countUrl.pathname).toBe("/api/v1/export/cobros/count");
    expect(Object.fromEntries(countUrl.searchParams)).toEqual({ status: "PAID", filter_field: "id", query: "abc", canal: "toku" });
    fireEvent.click(screen.getByRole("button", { name: "Descargar CSV" }));
    await waitFor(() => expect(saved).toEqual(["cobros-toku-20261029.csv"]));
    const dl = new URL(urls[1], "http://x");
    expect(dl.pathname).toBe("/api/v1/export/cobros");
    expect(Object.fromEntries(dl.searchParams)).toEqual({ status: "PAID", filter_field: "id", query: "abc", canal: "toku", all: "true" });
    expect(await screen.findByText(/Descargado cobros-toku-20261029\.csv \(1\.234 filas\)/)).toBeTruthy();
  });

  it("«Esta vista» envía offset y limit y calcula las filas de la página", async () => {
    replies.count = count(150);
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    expect(await screen.findByText("50 filas")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Descargar CSV" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    const dl = new URL(urls[1], "http://x");
    expect(dl.searchParams.get("offset")).toBe("100");
    expect(dl.searchParams.get("limit")).toBe("100");
    expect(dl.searchParams.has("all")).toBe(false);
    expect(new URL(urls[0], "http://x").searchParams.has("offset")).toBe(false);
  });

  it("sin Content-Disposition usa un nombre de respaldo", async () => {
    replies.count = count(500);
    replies.download = { csv: "x" };
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Descargar CSV" }));
    await waitFor(() => expect(saved).toEqual(["cobros-toku.csv"]));
  });

  it("avisa con claridad cuando el volumen es muy grande y pide confirmar", async () => {
    replies.count = count(EXPORT_VOLUME_WARNING_ROWS + 1);
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    expect(await screen.findByText(/Es un archivo muy grande/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Descargar de todos modos" })).toBeTruthy();
    expect(saved).toHaveLength(0);
    expect(urls).toHaveLength(1);
  });

  it("no avisa de volumen en «Esta vista»", async () => {
    replies.count = count(500_000);
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    await screen.findByRole("button", { name: "Descargar CSV" });
    expect(screen.queryByText(/Es un archivo muy grande/)).toBeNull();
  });

  it("403 en /count: «Tu rol no puede exportar este recurso.» y no descarga", async () => {
    replies.count = { status: 403, json: { detail: "Forbidden" } };
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    expect((await screen.findByRole("alert")).textContent).toBe("Tu rol no puede exportar este recurso.");
    expect(urls).toHaveLength(1);
    expect(saved).toHaveLength(0);
  });

  it("403 al descargar: el mismo mensaje, y el botón vuelve a quedar usable", async () => {
    replies.count = count(500);
    replies.download = { status: 403, json: {} };
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Descargar CSV" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Tu rol no puede exportar este recurso.");
    expect((screen.getByRole("button", { name: /Exportar/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("409, 422 y 5xx tienen mensajes propios", async () => {
    for (const [status, text] of [[409, /conflicto en el servidor/], [422, /filtros activos no son válidos/], [500, /servidor falló/], [503, /servidor falló/]] as const) {
      replies.count = { status, json: {} };
      const { unmount } = mount();
      openMenu();
      fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
      expect((await screen.findByRole("alert")).textContent).toMatch(text);
      unmount();
    }
  });

  it("muestra si el archivo incluirá datos personales según /count y la pista de permisos del front", async () => {
    replies.count = count(5, true);
    mount({ canPii: true });
    openMenu();
    expect(screen.getByText(/Tu rol puede exportar con datos personales/)).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    expect(await screen.findByText(/incluirá datos personales/)).toBeTruthy();
    cleanup();
    replies.count = count(5, false);
    mount({ canPii: false });
    openMenu();
    expect(screen.getByText(/exporta sin datos personales/)).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    expect(await screen.findByText("El archivo no incluirá datos personales.")).toBeTruthy();
  });

  it("lista los filtros que la exportación no puede aplicar y las notas de la vista", async () => {
    replies.count = count(5);
    mount({ ignoredFilters: ["RUT: «x»"], notes: ["Nota de la vista."] });
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    expect(await screen.findByText(/No se pueden aplicar a la exportación: RUT: «x»/)).toBeTruthy();
    expect(screen.getByText("Nota de la vista.")).toBeTruthy();
  });

  it("con 0 filas no permite descargar", async () => {
    replies.count = count(0);
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Todo el listado/ }));
    const button = await screen.findByRole("button", { name: "Descargar CSV" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("teclado: el foco entra al menú, flecha abajo navega y Escape cierra devolviendo el foco", () => {
    mount();
    const trigger = screen.getByRole("button", { name: /Exportar/ });
    trigger.focus();
    fireEvent.click(trigger);
    const [first, second] = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("«Cancelar» en la confirmación cierra sin descargar", async () => {
    replies.count = count(500);
    mount();
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    expect(screen.queryByText(/filas/)).toBeNull();
    expect(urls).toHaveLength(1);
  });

  it("limita «Esta vista» a 1.000 filas, el máximo del contrato", async () => {
    replies.count = count(5000);
    mount({ window: { offset: 0, limit: 2500 } });
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Esta vista/ }));
    expect(await screen.findByText("1.000 filas")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Descargar CSV" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(new URL(urls[1], "http://x").searchParams.get("limit")).toBe("1000");
  });
});

describe("filenameFromDisposition", () => {
  it("lee filename con y sin comillas y filename*", () => {
    expect(filenameFromDisposition('attachment; filename="pagos-20261029.csv"')).toBe("pagos-20261029.csv");
    expect(filenameFromDisposition("attachment; filename=clientes.csv")).toBe("clientes.csv");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''a%20b.csv")).toBe("a b.csv");
    expect(filenameFromDisposition(null)).toBeNull();
    expect(filenameFromDisposition("inline")).toBeNull();
  });
});
