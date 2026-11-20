/** H1 (PERF-03): la atenuación de los gráficos que se redibujan no usa transición con prefers-reduced-motion. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("atenuación de gráficos y movimiento reducido", () => {
  const css = readFileSync(resolve(__dirname, "../../Staging.css"), "utf8");
  it("anima la opacidad solo fuera de prefers-reduced-motion", () => {
    expect(css).toMatch(/\.extended-charts\[data-stale\]\s*\{\s*opacity:\s*\.6;\s*transition:\s*opacity \.15s;\s*\}/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.extended-charts\[data-stale\]\s*\{\s*transition:\s*none;\s*\}\s*\}/);
  });
});
