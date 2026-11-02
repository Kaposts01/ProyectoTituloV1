import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, getJson: vi.fn(), postForm: vi.fn() };
});
import { ApiError, getJson, postForm } from "../../api";
import { TOKU_REPORTS_PERMISSION, TokuReportsSection, type TokuReportsStatus } from "./TokuReportsSection";

const mockedGet = vi.mocked(getJson);
const mockedPost = vi.mocked(postForm);

const STATUS: TokuReportsStatus = {
  max_age_days: 7,
  reports: [
    { report_type: "deudas", generated_at: "2026-08-09T09:00:00+00:00", loaded_at: "2026-10-20T10:00:00+00:00", rows_total: 12, age_days: 85, is_stale: true },
    { report_type: "pagos", generated_at: "2026-10-30T09:00:00+00:00", loaded_at: "2026-10-31T10:00:00+00:00", rows_total: 3, age_days: 3, is_stale: false },
  ],
  stale_types: ["deudas"],
};

function pickFile(name = "Pagos.xlsx") {
  const input = screen.getByLabelText("Archivo de reporte de Toku") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], name)] } });
}

beforeEach(() => { mockedGet.mockReset(); mockedPost.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("TokuReportsSection", () => {
  it("sin el permiso no aparece ni consulta la API (RBAC)", () => {
    const { container } = render(<TokuReportsSection permissions={["toku.subscriptions.view", "sync.run"]} />);
    expect(container).toBeEmptyDOMElement();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("muestra la frescura por tipo y avisa del dato con más de 7 días (DEC-21)", async () => {
    mockedGet.mockResolvedValue(STATUS);
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    expect(await screen.findByText("Deudas")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/v1/imports/toku-reports/status");
    expect(screen.getByRole("alert")).toHaveTextContent("Hay reportes con dato de más de 7 días: Deudas.");
    expect(screen.getByText("Pagos").closest("tr")).not.toHaveAttribute("data-stale");
    expect(screen.getByText("Deudas").closest("tr")).toHaveAttribute("data-stale", "true");
  });

  it("sin reportes vencidos no muestra el aviso", async () => {
    mockedGet.mockResolvedValue({ ...STATUS, reports: [STATUS.reports[1]], stale_types: [] });
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    await screen.findByText("Pagos");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sube el archivo al POST existente y muestra el resumen con los avisos traducidos", async () => {
    mockedGet.mockResolvedValue({ max_age_days: 7, reports: [], stale_types: [] });
    mockedPost.mockResolvedValue({
      report_type: "pagos", rows_total: 3, rows_new: 2, rows_updated: 1, rows_skipped: 0, rows_stale: 0,
      data_age_days: 20, warnings: ["data_older_than_max_age"],
    });
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    await screen.findByText("Todavía no se ha cargado ningún reporte.");
    pickFile();
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, form] = mockedPost.mock.calls[0];
    expect(path).toBe("/api/v1/imports/toku-reports");
    expect((form as FormData).get("report")).toBeInstanceOf(File);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Reporte de Pagos cargado: 2 nuevas, 1 actualizadas, 0 omitidas.");
    expect(status).toHaveTextContent("El dato de este archivo tiene más de 7 días.");
    expect(mockedGet).toHaveBeenCalledTimes(2); // refresca la frescura tras cargar
  });

  it("traduce los códigos de error del backend sin mostrar el contenido del archivo", async () => {
    mockedGet.mockResolvedValue({ max_age_days: 7, reports: [], stale_types: [] });
    mockedPost.mockRejectedValue(new ApiError("x", 409, { code: "already_loaded", message: "Este reporte ya fue cargado" }));
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    await screen.findByText("Todavía no se ha cargado ningún reporte.");
    pickFile();
    expect(await screen.findByRole("alert")).toHaveTextContent("Este reporte ya fue cargado antes (mismo contenido).");
  });

  it("un 403 del backend muestra que falta el permiso", async () => {
    mockedGet.mockResolvedValue({ max_age_days: 7, reports: [], stale_types: [] });
    mockedPost.mockRejectedValue(new ApiError("x", 403, { code: "forbidden" }));
    render(<TokuReportsSection permissions={[TOKU_REPORTS_PERMISSION]} />);
    await screen.findByText("Todavía no se ha cargado ningún reporte.");
    pickFile();
    expect(await screen.findByRole("alert")).toHaveTextContent("No tienes permiso para cargar reportes de Toku.");
  });
});
