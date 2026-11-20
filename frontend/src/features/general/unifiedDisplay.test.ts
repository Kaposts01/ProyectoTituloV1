import { expect, it } from "vitest";
import { day } from "./unifiedDisplay";

it("muestra fechas de calendario chilenas sin convertirlas a otra zona horaria", () => {
  expect(day("2026-11-05")).toBe("05-11-2026");
  expect(day("2026-11-05T00:00:00Z")).toBe("05-11-2026");
  expect(day("2024-02-29")).toBe("29-02-2024");
  expect(day(null)).toBe("—");
  expect(day("fecha no informada")).toBe("fecha no informada");
});
