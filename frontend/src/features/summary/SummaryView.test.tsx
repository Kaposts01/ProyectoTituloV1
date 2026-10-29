/**
 * Pruebas de render de la pantalla Resumen unificado con `fetch` simulado. Datos sintéticos (summaryFixtures.ts).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidateCache } from "../../apiCache";
import { rawEmptyMonth, rawKpi, rawSingleChannel, rawSummary, type RawSummary } from "./summaryFixtures";
import { SummaryView } from "./SummaryView";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div data-testid="rc">{cloneElement(children, { width: 600, height: 280 })}</div>
    ),
  };
});

type Reply = { status?: number; body: unknown } | "pending";
type Responder = (url: URL) => Reply;

const HEALTH = [
  { channel: "virtualpos", level: "ok", last_finished_at: "2026-10-15T09:00:00-03:00", age_hours: 3 },
  { channel: "tch", level: "warn", last_finished_at: "2026-10-12T20:00:00-03:00", age_hours: 70 },
];

let calls: URL[] = [];

function installFetch(summary: Responder, health: unknown = HEALTH) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://localhost");
    calls.push(url);
    const reply: Reply = url.pathname === "/api/v1/sync-runs/health" ? { body: health } : summary(url);
    if (reply === "pending") return new Promise(() => {});
    const status = reply.status ?? 200;
    return { ok: status < 400, status, headers: { get: (key: string) => (key.toLowerCase() === "content-type" ? "application/json" : null) }, json: async () => reply.body };
  }));
}

const summaryCalls = () => calls.filter((url) => url.pathname === "/api/v1/dashboard/general");

beforeEach(() => invalidateCache());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  invalidateCache();
});

const KPI_LABELS = ["Ingreso total", "Acumulado del año", "Socios totales", "Activaciones", "Bajas", "Crecimiento neto", "Churn", "Cobrabilidad", "No cobrado", "Por cobrar", "MRR", "ARPU"];

/** Tarjeta de KPI por su rótulo. */
function card(label: string): HTMLElement {
  const found = screen.getAllByRole("article").find((el) => el.querySelector(".metric-label")?.textContent === label);
  if (!found) throw new Error(`Sin tarjeta «${label}»`);
  return found;
}

/** Valor mostrado en la tarjeta (sin contar el delta). */
function valueOf(label: string): string | null | undefined {
  return card(label).querySelector(".kpi-value")?.textContent;
}

async function ready() {
  await screen.findByRole("region", { name: "Indicadores del mes" });
}

describe("Resumen unificado: tarjetas", () => {
  it("muestra las 12 tarjetas con sus valores formateados", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    for (const label of KPI_LABELS) expect(card(label)).toBeTruthy();
    expect(screen.getAllByRole("article")).toHaveLength(12);
    expect(valueOf("Ingreso total")).toBe("$92.000");
    expect(valueOf("Acumulado del año")).toBe("$168.000");
    expect(valueOf("Socios totales")).toBe("8");
    expect(valueOf("Activaciones")).toBe("3");
    expect(valueOf("Bajas")).toBe("4");
    expect(valueOf("Crecimiento neto")).toBe("-1");
    expect(valueOf("Churn")).toBe("44,4%");
    expect(valueOf("Cobrabilidad")).toBe("66,7%");
    expect(valueOf("No cobrado")).toBe("$30.000");
    expect(valueOf("Por cobrar")).toBe("$10.000");
    expect(valueOf("MRR")).toBe("$90.000");
    expect(valueOf("ARPU")).toBe("$12.857");
  });

  it("socios totales lleva la nota «suma por canal, no deduplicada»", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(within(card("Socios totales")).getByText(/suma por canal, no deduplicada/i)).toBeTruthy();
  });

  it("cada tarjeta lleva el delta contra el mes anterior y el chip «sin meta» (no se inventan metas)", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    for (const label of KPI_LABELS) {
      const el = card(label);
      expect(within(el).getByTestId("kpi-delta"), label).toBeTruthy();
      expect(within(el).getByText("sin meta"), label).toBeTruthy();
      expect(within(el).queryByRole("progressbar"), label).toBeNull();
    }
    expect(screen.queryByText("en meta")).toBeNull();
    expect(screen.queryByText("lejos de meta")).toBeNull();
    expect(within(card("Socios totales")).getByTestId("kpi-delta").textContent).toMatch(/baja.*-1.*vs mes anterior/);
    expect(within(card("Ingreso total")).getByTestId("kpi-delta").textContent).toMatch(/sube.*\+\$17\.000/);
  });

  it("el churn es una tarjeta con sparkline y muestra su definición como PROPUESTA pendiente de confirmar", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(card("Churn").querySelector("svg.kpi-spark")).toBeTruthy();
    const help = screen.getByText(/Bajas del mes ÷ socios al inicio del mes/);
    expect(help.textContent).toMatch(/propuesta/i);
    expect(help.textContent).toMatch(/pendiente de confirmación/i);
    expect(card("Churn").parentElement?.contains(help)).toBe(true);
  });

  it("el delta del churn baja es bueno y subir es malo (sube 33,3 pts => clase «bad»)", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(within(card("Churn")).getByTestId("kpi-delta").className).toContain("bad");
  });

  it("MRR y ARPU en null se ven «—» con texto accesible «sin datos», sin inventar 0", async () => {
    const raw = rawSummary({ is_current_month: false, kpis: { ...rawSummary().kpis, mrr: rawKpi(null, null, "clp", { por_canal: {} }), arpu: rawKpi(null, null, "clp") } });
    installFetch(() => ({ body: raw }));
    render(<SummaryView />);
    await ready();
    for (const label of ["MRR", "ARPU"]) {
      const el = card(label);
      expect(within(el).getByRole("img", { name: "sin datos" }).textContent).toBe("—");
      expect(within(el).getByText(/mes en curso/i)).toBeTruthy();
    }
    expect(valueOf("Ingreso total")).toBe("$92.000");
  });
});

describe("Resumen unificado: gráficos", () => {
  it("muestra los tres gráficos con su botón «Ver datos» y su tabla accesible", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(screen.getByRole("heading", { name: "Ingreso por canal" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Socios totales" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Activaciones y bajas" })).toBeTruthy();
    const toggles = screen.getAllByRole("button", { name: "Ver datos" });
    expect(toggles).toHaveLength(3);
    fireEvent.click(toggles[0]);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(13);
    expect(within(table).getByRole("columnheader", { name: "Total" })).toBeTruthy();
    for (const name of ["VirtualPOS", "Toku", "Payku", "TCH"]) expect(within(table).getByRole("columnheader", { name })).toBeTruthy();
    // mes sin dato de Payku: «—», no 0
    expect(within(within(table).getAllByRole("row")[1]).getAllByRole("cell")[2].textContent).toBe("—");
  });

  it("la tabla de activaciones y bajas incluye la columna de crecimiento neto", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    fireEvent.click(screen.getAllByRole("button", { name: "Ver datos" })[2]);
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Crecimiento neto" })).toBeTruthy();
    expect(within(table).getByRole("columnheader", { name: "Activaciones" })).toBeTruthy();
    expect(within(table).getByRole("columnheader", { name: "Bajas" })).toBeTruthy();
  });

  it("las pestañas «Últimos 12 meses / Año / Todo» recortan los gráficos", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    const group = screen.getByRole("radiogroup", { name: /rango/i });
    expect(within(group).getByRole("radio", { name: "Últimos 12 meses" }).getAttribute("aria-checked")).toBe("true");
    expect(within(group).getByRole("radio", { name: "Todo" })).toBeTruthy();
    fireEvent.click(within(group).getByRole("radio", { name: "Año 2026" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Ver datos" })[0]);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(11); // cabecera + enero a octubre
  });

  it("el rango no vuelve a pedir datos al servidor", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    fireEvent.click(screen.getByRole("radio", { name: "Todo" }));
    expect(summaryCalls()).toHaveLength(1);
  });

  it("rotula el dato de TCH como «Dato al <fecha>» (viene de Excel)", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    const health = await screen.findByRole("region", { name: "Sincronización por canal" });
    expect(within(health).getByText(/Dato al 12-10-2026/)).toBeTruthy();
    expect(screen.getAllByText(/Dato al 12-10-2026/).length).toBeGreaterThanOrEqual(2); // salud y gráfico de ingreso
  });

  it("sin TCH entre los canales no hay rótulo «Dato al»", async () => {
    installFetch(() => ({ body: rawSingleChannel("toku") }), [{ channel: "toku", level: "ok", last_finished_at: null, age_hours: 2 }]);
    render(<SummaryView />);
    await ready();
    expect(screen.queryByText(/Dato al/)).toBeNull();
  });
});

describe("Resumen unificado: salud de canal", () => {
  it("pide /sync-runs/health y muestra un indicador compacto por canal del resumen", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    const health = await screen.findByRole("region", { name: "Sincronización por canal" });
    expect(calls.some((url) => url.pathname === "/api/v1/sync-runs/health")).toBe(true);
    expect(within(health).getByText("VirtualPOS")).toBeTruthy();
    expect(within(health).getByText(/Sincronizado: hace 3 h/)).toBeTruthy();
    expect(within(health).getByText("TCH")).toBeTruthy();
    expect(within(health).queryByText("Toku")).toBeNull(); // sin dato de salud: no se pinta
  });

  it("si la salud no responde, la pantalla funciona igual y no pinta el indicador", async () => {
    installFetch(() => ({ body: rawSummary() }), []);
    render(<SummaryView />);
    await ready();
    expect(screen.queryByRole("region", { name: "Sincronización por canal" })).toBeNull();
  });
});

describe("Resumen unificado: estados", () => {
  it("cargando: tarjetas esqueleto y aviso accesible, sin gráficos", () => {
    installFetch(() => "pending");
    render(<SummaryView />);
    expect(screen.getByRole("status").textContent).toMatch(/Cargando/);
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(document.querySelectorAll(".summary-skeleton").length).toBeGreaterThan(0);
  });

  it("error: mensaje en español con «Reintentar», que vuelve a pedir y se recupera", async () => {
    let attempt = 0;
    installFetch(() => (++attempt === 1 ? { status: 500, body: {} } : { body: rawSummary() }));
    render(<SummaryView />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/servidor/i);
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    await ready();
    expect(summaryCalls()).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("422: muestra el mensaje en español del mes inválido", async () => {
    installFetch(() => ({ status: 422, body: { detail: { code: "invalid_month", message: "bad month" } } }));
    render(<SummaryView />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("El mes no es válido");
    expect(alert.textContent).not.toContain("bad month");
  });

  it("mes sin datos: aviso con acciones, tarjetas en «—» y sin gráficos", async () => {
    installFetch(() => ({ body: rawEmptyMonth("2027-01") }));
    render(<SummaryView />);
    await ready();
    const notice = screen.getByRole("status", { name: /sin datos/i });
    expect(notice.textContent).toContain("enero de 2027");
    expect(within(notice).getByRole("button", { name: "Ver el mes anterior" })).toBeTruthy();
    for (const label of KPI_LABELS) expect(within(card(label)).getByRole("img", { name: "sin datos" }).textContent).toBe("—");
    expect(screen.queryByRole("button", { name: "Ver datos" })).toBeNull();
    fireEvent.click(within(notice).getByRole("button", { name: "Ver el mes anterior" }));
    await waitFor(() => expect(summaryCalls()[1].searchParams.get("month")).toBe("2026-12"));
  });

  it("calidad de datos: avisa de las suscripciones sin fecha válida", async () => {
    installFetch(() => ({ body: rawSummary({ calidad_datos: { altas_sin_fecha: 2, bajas_sin_fecha: 1 } }) }));
    render(<SummaryView />);
    await ready();
    const note = screen.getByText(/sin fecha/i);
    expect(note.textContent).toMatch(/2/);
    expect(note.textContent).toMatch(/1/);
  });
});

describe("Resumen unificado: filtros", () => {
  it("la primera petición no envía parámetros (mes actual y todos los canales permitidos)", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(summaryCalls()).toHaveLength(1);
    expect(summaryCalls()[0].search).toBe("");
  });

  it("el filtro de canales ofrece solo los canales devueltos (según permisos)", async () => {
    installFetch(() => ({ body: rawSingleChannel("toku") }));
    render(<SummaryView />);
    await ready();
    const group = screen.getByRole("group", { name: "Canales" });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(1);
    const only = within(group).getByRole("checkbox", { name: "Toku" }) as HTMLInputElement;
    expect(only.checked).toBe(true);
    expect(only.disabled).toBe(true); // no se puede dejar el filtro vacío
  });

  it("desmarcar un canal vuelve a pedir con los canales restantes y mantiene la lista completa", async () => {
    installFetch((url) => ({ body: url.searchParams.get("channels") ? rawSingleChannel("toku") : rawSummary() }));
    render(<SummaryView />);
    await ready();
    const group = screen.getByRole("group", { name: "Canales" });
    fireEvent.click(within(group).getByRole("checkbox", { name: "VirtualPOS" }));
    await waitFor(() => expect(summaryCalls()).toHaveLength(2));
    expect(summaryCalls()[1].searchParams.get("channels")).toBe("toku,payku,tch");
    await ready();
    expect(within(screen.getByRole("group", { name: "Canales" })).getAllByRole("checkbox")).toHaveLength(4);
  });

  it("volver a marcar todos los canales pide sin el parámetro", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    const group = screen.getByRole("group", { name: "Canales" });
    fireEvent.click(within(group).getByRole("checkbox", { name: "Payku" }));
    await waitFor(() => expect(summaryCalls()).toHaveLength(2));
    await ready();
    fireEvent.click(within(screen.getByRole("group", { name: "Canales" })).getByRole("checkbox", { name: "Payku" }));
    await waitFor(() => expect(summaryCalls()).toHaveLength(3));
    expect(summaryCalls()[2].searchParams.has("channels")).toBe(false);
  });

  it("el selector de mes pide ese mes y «Mes actual» vuelve a pedir sin mes", async () => {
    installFetch((url) => ({ body: rawSummary({ month: url.searchParams.get("month") ?? "2026-10" }) }));
    render(<SummaryView />);
    await ready();
    const input = screen.getByLabelText("Mes") as HTMLInputElement;
    expect(input.value).toBe("2026-10");
    expect(screen.queryByRole("button", { name: "Mes actual" })).toBeNull();
    fireEvent.change(input, { target: { value: "2026-09" } });
    await waitFor(() => expect(summaryCalls()).toHaveLength(2));
    expect(summaryCalls()[1].searchParams.get("month")).toBe("2026-09");
    await screen.findByText(/septiembre de 2026/);
    fireEvent.click(screen.getByRole("button", { name: "Mes actual" }));
    await waitFor(() => expect(summaryCalls()).toHaveLength(3));
    expect(summaryCalls()[2].searchParams.has("month")).toBe(false);
  });

  it("un valor de mes vacío o incompleto no dispara una petición", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    fireEvent.change(screen.getByLabelText("Mes"), { target: { value: "" } });
    expect(summaryCalls()).toHaveLength(1);
  });
});

describe("Resumen unificado: encabezado", () => {
  it("título, mes en español y hora de cálculo", async () => {
    installFetch(() => ({ body: rawSummary() }));
    render(<SummaryView />);
    await ready();
    expect(screen.getByRole("heading", { level: 1, name: "Resumen" })).toBeTruthy();
    expect(screen.getByText(/octubre de 2026/)).toBeTruthy();
  });

  it("usa solo las series del endpoint: una sola petición al resumen", async () => {
    installFetch(() => ({ body: rawSummary() as RawSummary }));
    render(<SummaryView />);
    await ready();
    expect(summaryCalls()).toHaveLength(1);
  });
});
