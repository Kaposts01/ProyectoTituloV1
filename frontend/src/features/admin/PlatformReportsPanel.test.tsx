import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, getJson: vi.fn(), postForm: vi.fn() };
});
import { ApiError, getJson, postForm } from "../../api";
import {
  IMPORTS_STATUS_URL, PAYKU_REPORTS_PERMISSION, PlatformReportsPanel, VP_REPORTS_PERMISSION, type ImportsStatus,
} from "./PlatformReportsPanel";
import { TOKU_REPORTS_PERMISSION } from "./TokuReportsSection";

const mockedGet = vi.mocked(getJson);
const mockedPost = vi.mocked(postForm);

const load = (over: Record<string, unknown>) => ({
  report_type: "transacciones", filename: null, loaded_at: null, rows_total: null, rows_new: null, rows_updated: null,
  rows_skipped: null, result: null, error_label: null, data_at: null, age_days: null, is_stale: false, ...over,
});

const STATUS: ImportsStatus = {
  max_age_days: 7,
  channels: [
    {
      channel: "virtualpos",
      reports: [
        load({ filename: "TransaccionesPAT-VirtualPOS-1792546479.csv", loaded_at: "2026-11-01T10:00:00+00:00", rows_total: 120, result: "completed", age_days: 12, is_stale: true }),
        load({ report_type: "suscriptores" }),
      ],
      stale_types: ["transacciones"],
    },
    {
      channel: "payku",
      reports: [load({ filename: "Payku_dataTransacciones.xlsx", loaded_at: "2026-11-03T10:00:00+00:00", rows_total: 40, result: "failed", age_days: 1 })],
      stale_types: [],
    },
    { channel: "tch", reports: [load({ report_type: "reporte", filename: "tch.xlsx", rows_total: 9, result: "consolidado", age_days: 2 })], stale_types: [] },
  ],
};

const ALL = [TOKU_REPORTS_PERMISSION, VP_REPORTS_PERMISSION, PAYKU_REPORTS_PERMISSION];

function card(key: string): HTMLElement {
  return document.querySelector(`[data-channel="${key}"]`) as HTMLElement;
}

function pick(labelText: string, name: string) {
  const input = screen.getByLabelText(labelText) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], name)] } });
}

beforeEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
  mockedGet.mockImplementation(async (path: string) => {
    if (path === IMPORTS_STATUS_URL) return STATUS as never;
    return { max_age_days: 7, reports: [], stale_types: [] } as never; // estado de Toku
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("PlatformReportsPanel", () => {
  it("sin ningún permiso de carga no aparece ni consulta la API (RBAC)", () => {
    const { container } = render(<PlatformReportsPanel permissions={["sync.run"]} isAdmin={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("reúne los cuatro canales en un solo lugar para el admin", async () => {
    render(<PlatformReportsPanel permissions={ALL} isAdmin />);
    expect(screen.getByRole("heading", { name: "Importar reportes de plataformas" })).toBeInTheDocument();
    expect(await screen.findByText("TransaccionesPAT-VirtualPOS-1792546479.csv")).toBeInTheDocument();
    for (const name of ["Reportes de Toku", "Reportes PAT de VirtualPOS", "Reportes de Payku", "Reporte Excel de TCH"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(mockedGet).toHaveBeenCalledWith(IMPORTS_STATUS_URL);
    expect(document.body.textContent).not.toMatch(/\b(completed|failed|running)\b/); // siempre traducidos
  });

  it("muestra solo los canales con permiso", async () => {
    render(<PlatformReportsPanel permissions={[PAYKU_REPORTS_PERMISSION]} isAdmin={false} />);
    expect(await screen.findByText("Payku_dataTransacciones.xlsx")).toBeInTheDocument();
    expect(card("payku")).not.toBeNull();
    expect(card("virtualpos")).toBeNull();
    expect(card("tch")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Reportes de Toku" })).toBeNull();
  });

  it("muestra la última carga por tipo (fecha, nombre, filas, resultado) y avisa del dato con más de 7 días", async () => {
    render(<PlatformReportsPanel permissions={ALL} isAdmin />);
    await screen.findByText("TransaccionesPAT-VirtualPOS-1792546479.csv");
    const vp = within(card("virtualpos"));
    expect(vp.getByRole("alert")).toHaveTextContent("Hay archivos con dato de más de 7 días: Transacciones.");
    const row = vp.getByText("TransaccionesPAT-VirtualPOS-1792546479.csv").closest("tr") as HTMLElement;
    expect(row).toHaveAttribute("data-stale", "true");
    expect(within(row).getByText("120")).toBeInTheDocument();
    expect(within(row).getByText("Cargado")).toBeInTheDocument();
    expect(vp.getByText("Suscriptores").closest("tr")).toHaveTextContent("Sin cargas");
    expect(within(card("payku")).getByText("Fallido")).toBeInTheDocument();
    expect(within(card("payku")).queryByRole("alert")).toBeNull();
    expect(within(card("tch")).getByText("Consolidado")).toBeInTheDocument();
  });

  it("sube un reporte de Payku y muestra el resumen de filas cargadas y omitidas", async () => {
    mockedPost.mockResolvedValue({ report_type: "transacciones", rows_total: 3, rows_new: 2, rows_updated: 0, rows_skipped: 1, warnings: [] });
    render(<PlatformReportsPanel permissions={[PAYKU_REPORTS_PERMISSION]} isAdmin={false} />);
    await screen.findByText("Payku_dataTransacciones.xlsx");
    pick("Archivo: Reportes de Payku", "Payku_dataTransacciones.xlsx");
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, form] = mockedPost.mock.calls[0];
    expect(path).toBe("/api/v1/imports/payku-reports");
    expect((form as FormData).get("report")).toBeInstanceOf(File);
    expect(await within(card("payku")).findByRole("status")).toHaveTextContent(
      "Archivo de Transacciones cargado: 2 nuevas, 0 actualizadas, 1 omitidas (de 3 filas).",
    );
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(2)); // refresca la última carga
  });

  it("traduce los errores de encabezados y de archivo duplicado del PAT de VirtualPOS", async () => {
    mockedPost.mockRejectedValueOnce(new ApiError("x", 422, { code: "invalid_format", message: "faltan columnas: Id cargo" }));
    mockedPost.mockRejectedValueOnce(new ApiError("x", 409, { code: "already_loaded", message: "ya" }));
    render(<PlatformReportsPanel permissions={[VP_REPORTS_PERMISSION]} isAdmin={false} />);
    await screen.findByText("TransaccionesPAT-VirtualPOS-1792546479.csv");
    pick("Archivo: Reportes PAT de VirtualPOS", "malo.csv");
    expect(await within(card("virtualpos")).findByText("El archivo no tiene los encabezados esperados o su tipo no se puede cargar.")).toBeInTheDocument();
    expect(mockedPost.mock.calls[0][0]).toBe("/api/v1/imports/virtualpos-reports");
    pick("Archivo: Reportes PAT de VirtualPOS", "repetido.csv");
    expect(await within(card("virtualpos")).findByText("Este reporte ya fue cargado antes (mismo contenido).")).toBeInTheDocument();
  });

  it("la carga de TCH usa la importación existente y avisa que corre en segundo plano", async () => {
    mockedPost.mockResolvedValue({ run_id: "r-1", status: "accepted" });
    render(<PlatformReportsPanel permissions={[]} isAdmin />);
    await screen.findByText("tch.xlsx");
    pick("Archivo: Reporte Excel de TCH", "tch.xlsx");
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost.mock.calls[0][0]).toBe("/api/v1/tch/import-report");
    expect(await within(card("tch")).findByRole("status")).toHaveTextContent("Importación iniciada.");
  });
});
