import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelChart } from "./ChannelChart";
import { buildChartRows } from "./chartRows";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => <div data-testid="rc">{children}</div>,
  };
});

afterEach(cleanup);

const series = [{ key: "count", label: "Cantidad", color: "#2a7a64" }];
const data = [
  { year: 2025, month: 3, count: 30 },
  { year: 2024, month: 12, count: 5 },
  { year: 2025, month: 1, count: 10 },
];

describe("buildChartRows", () => {
  it("filtra por año y ordena por mes con etiqueta corta", () => {
    const rows = buildChartRows(data, 2025);
    expect(rows.map((r) => r.month)).toEqual([1, 3]);
    expect(rows.map((r) => r.label)).toEqual(["Ene", "Mar"]);
  });

  it("con year=null conserva todo, ordena por año y etiqueta 'Ene 25'", () => {
    const rows = buildChartRows(data, null);
    expect(rows.map((r) => r.label)).toEqual(["Dic 24", "Ene 25", "Mar 25"]);
  });

  it("devuelve vacío para un año sin datos", () => {
    expect(buildChartRows(data, 2030)).toEqual([]);
  });
});

describe("ChannelChart", () => {
  it("muestra 'Sin datos' con data vacía", () => {
    render(<ChannelChart series={series} data={[]} kind="bar" mode="count" year={2025} />);
    expect(screen.getByText("Sin datos para el período.")).toBeInTheDocument();
  });

  it("muestra 'Sin datos' para un año sin datos", () => {
    render(<ChannelChart series={series} data={data} kind="bar" mode="count" year={2030} />);
    expect(screen.getByText("Sin datos para el período.")).toBeInTheDocument();
    expect(screen.queryByTestId("rc")).not.toBeInTheDocument();
  });

  it("renderiza cada tipo con role img y etiqueta", () => {
    for (const kind of ["bar", "stacked", "line"] as const) {
      const { unmount } = render(<ChannelChart series={series} data={data} kind={kind} mode="count" year={2025} ariaLabel="Mi gráfico" />);
      expect(screen.getByRole("img", { name: "Mi gráfico" })).toBeInTheDocument();
      expect(screen.getByTestId("rc")).toBeInTheDocument();
      unmount();
    }
  });
});
