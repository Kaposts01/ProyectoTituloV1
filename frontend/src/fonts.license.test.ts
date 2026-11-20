/** H6 (PERF-03): las fuentes de Fontshare van sin modificar y con el texto completo de la licencia ITF FFL al lado. */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const fonts = resolve(__dirname, "../public/fonts");
const read = (name: string) => readFileSync(resolve(fonts, name), "utf8");

describe("fuentes autoalojadas y licencia ITF", () => {
  it("usa los woff2 variables originales (sin el sufijo -latin de los recortados) en CSS y precarga", () => {
    const css = readFileSync(resolve(__dirname, "fonts.css"), "utf8");
    const html = readFileSync(resolve(__dirname, "../index.html"), "utf8");
    for (const name of ["cabinet-grotesk-variable.woff2", "general-sans-variable.woff2"]) {
      expect(existsSync(resolve(fonts, name))).toBe(true);
      expect(css).toContain(`/fonts/${name}`);
      expect(html).toContain(`/fonts/${name}`);
      expect(readFileSync(resolve(fonts, name)).subarray(0, 4).toString("latin1")).toBe("wOF2");
    }
    expect(existsSync(resolve(fonts, "cabinet-grotesk-latin.woff2"))).toBe(false);
    expect(existsSync(resolve(fonts, "general-sans-latin.woff2"))).toBe(false);
  });

  it("incluye el texto completo de la ITF FFL, con la cláusula de subconjuntos y el permiso de autoalojar", () => {
    const text = read("LICENSE-Fontshare-ITF.txt");
    expect(text).toContain("ITF Free Font License");
    expect(text).toContain("01 GRANT OF LICENSE");
    expect(text).toContain("You may self-host the Font Software");
    expect(text).toContain("02 LIMITATIONS OF USAGE");
    expect(text).toContain("subsetting");
    expect(text).toContain("09 FINAL PROVISIONS");
  });
});
