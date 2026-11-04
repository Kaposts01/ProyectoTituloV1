import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelChart } from "./ChannelChart";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) => (
      <div data-testid="rc">{cloneElement(children, { width: 600, height: 280 })}</div>
    ),
  };
});

afterEach(cleanup);

// Datos sintéticos. Un valor ausente (clave omitida) es «sin dato», no un 0.
const members = [{ key: "members", label: "Socios totales", color: "var(--series-1)" }];
const memberRows = [
  { year: 2026, month: 8, members: 10 },
  { year: 2026, month: 9, members: 12 },
  { year: 2026, month: 10 },
] as Array<{ year: number; month: number } & Record<string, number>>;

const bars = [
  { key: "activations", label: "Activaciones", color: "var(--series-1)" },
  { key: "cancellations", label: "Bajas", color: "var(--status-rejected)" },
];
const net = { key: "net", label: "Crecimiento neto", color: "var(--series-2)" };
const flowRows = [
  { year: 2026, month: 9, activations: 3, cancellations: 1, net: 2 },
  { year: 2026, month: 10, activations: 1, cancellations: 4, net: -3 },
];

describe("ChannelChart: área", () => {
  it("kind=\"area\" dibuja un área por serie", () => {
    const { container } = render(<ChannelChart series={members} data={memberRows} kind="area" mode="count" year={null} />);
    expect(container.querySelector(".recharts-area")).toBeTruthy();
    expect(container.querySelector(".recharts-bar")).toBeNull();
  });

  it("la tabla alternativa muestra «—» para el mes sin dato (no inventa un 0)", () => {
    render(<ChannelChart series={members} data={memberRows} kind="area" mode="count" year={null} showDataToggle ariaLabel="Socios" />);
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    const table = screen.getByRole("table");
    const lastRow = within(table).getAllByRole("row")[3];
    expect(within(lastRow).getAllByRole("cell")[0].textContent).toBe("—");
  });
});

describe("ChannelChart: barras con línea superpuesta", () => {
  it("overlayLine dibuja las barras y una línea encima", () => {
    const { container } = render(<ChannelChart series={bars} data={flowRows} kind="grouped" mode="count" year={null} overlayLine={net} />);
    expect(container.querySelector(".recharts-bar")).toBeTruthy();
    expect(container.querySelector(".recharts-line")).toBeTruthy();
  });

  it("la tabla alternativa incluye la columna de la línea, con negativos", () => {
    render(<ChannelChart series={bars} data={flowRows} kind="grouped" mode="count" year={null} overlayLine={net} showDataToggle ariaLabel="Flujo" />);
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Crecimiento neto" })).toBeTruthy();
    const lastRow = within(table).getAllByRole("row")[2];
    expect(within(lastRow).getAllByRole("cell").map((c) => c.textContent)).toEqual(["1", "4", "-3"]);
  });
});

describe("ChannelChart: apilado con meses sin dato", () => {
  const series = [
    { key: "a", label: "Canal A", color: "var(--series-1)" },
    { key: "b", label: "Canal B", color: "var(--series-2)" },
  ];
  const rows = [
    { year: 2026, month: 9, a: 100, b: 50 },
    { year: 2026, month: 10 },
  ] as Array<{ year: number; month: number } & Record<string, number>>;

  it("el total de un mes sin ningún dato es «—», no $0", () => {
    render(<ChannelChart series={series} data={rows} kind="stacked" mode="amount" year={null} showDataToggle ariaLabel="Ingreso" />);
    fireEvent.click(screen.getByRole("button", { name: "Ver datos" }));
    const table = screen.getByRole("table");
    const cells = within(within(table).getAllByRole("row")[2]).getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toEqual(["—", "—", "—"]);
    const first = within(within(table).getAllByRole("row")[1]).getAllByRole("cell").map((c) => c.textContent);
    expect(first).toEqual(["$100", "$50", "$150"]);
  });
});
