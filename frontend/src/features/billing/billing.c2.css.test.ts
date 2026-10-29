import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Se leen como texto plano desde disco (el pipeline CSS de vitest no entrega el contenido con ?raw).
const read = (rel: string) => readFileSync(resolve(process.cwd(), "src", rel), "utf8");
const billing = read("features/billing/billing.css");
const indexCss = read("index.css");

/** Reglas «selector { cuerpo }» de un CSS plano (suficiente para billing.css; las @media se leen como reglas sueltas). */
function rules(css: string): Array<{ selector: string; body: string }> {
  const out: Array<{ selector: string; body: string }> = [];
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const re = /([^{}@;]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(clean))) out.push({ selector: m[1].trim(), body: m[2] });
  return out;
}
const ruleFor = (css: string, selector: string) => rules(css).filter((r) => r.selector.split(",").map((s) => s.trim()).includes(selector));

function tokens(css: string, opener: RegExp): Record<string, string> {
  const m = opener.exec(css);
  if (!m) return {};
  const end = css.indexOf("}", m.index);
  const out: Record<string, string> = {};
  for (const d of css.slice(m.index + m[0].length, end).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim();
  return out;
}
const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
function lum(hex: string) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => lin(parseInt(h.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a: string, b: string) => { const x = lum(a); const y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const light: Record<string, string> = { ...tokens(indexCss, /:root\s*\{/), ...tokens(billing, /:root\s*\{/) };
const dark: Record<string, string> = { ...light, ...tokens(indexCss, /html\[data-theme="dark"\]\s*\{/), ...tokens(billing, /html\[data-theme="dark"\]\s*\{/) };

describe("D3 contraste de insignias y textos (leído de los tokens)", () => {
  const textPairs: Array<[string, string, string]> = [
    ["ok", "--bx-ok-text", "--bx-ok-bg"], ["warning", "--bx-warn-text", "--bx-warn-bg"], ["error", "--bx-err-text", "--bx-err-bg"],
    ["neutral", "--bx-neutral-text", "--bx-neutral-bg"], ["hora de la línea de tiempo", "--text-2", "--bg-surface"],
  ];
  for (const [name, theme] of [["claro", light], ["oscuro", dark]] as const) {
    for (const [label, fg, bg] of textPairs) {
      it(`${label} en ${name} >= 4,5:1`, () => {
        expect(theme[fg], fg).toBeTruthy();
        expect(theme[bg], bg).toBeTruthy();
        expect(ratio(theme[fg], theme[bg])).toBeGreaterThanOrEqual(4.5);
      });
    }
    it(`conector y punto de la línea de tiempo en ${name} >= 3:1 sobre la superficie`, () => {
      expect(theme["--bx-line"], "--bx-line").toBeTruthy();
      expect(theme["--bx-dot"], "--bx-dot").toBeTruthy();
      expect(ratio(theme["--bx-line"], theme["--bg-surface"])).toBeGreaterThanOrEqual(3);
      expect(ratio(theme["--bx-dot"], theme["--bg-surface"])).toBeGreaterThanOrEqual(3);
    });
  }
  it("el texto neutro sube a >= 7:1 (margen sobre 4,5) en ambos temas", () => {
    expect(ratio(light["--bx-neutral-text"], light["--bx-neutral-bg"])).toBeGreaterThanOrEqual(7);
    expect(ratio(dark["--bx-neutral-text"], dark["--bx-neutral-bg"])).toBeGreaterThanOrEqual(7);
  });
});

describe("D2 línea de tiempo", () => {
  const tl = rules(billing).filter((r) => r.selector.includes(".bx-timeline"));
  it("no usa border-left ni border-inline-start en ninguna regla de la timeline", () => {
    expect(tl.length).toBeGreaterThan(0);
    for (const r of tl) expect(r.body + r.selector, r.selector).not.toMatch(/border-(left|inline-start)/);
  });
  it("tiene un conector continuo de 2px y un punto circular con relleno de token por evento", () => {
    const line = ruleFor(billing, ".bx-timeline::before")[0];
    expect(line?.body).toMatch(/width:\s*2px/);
    expect(line?.body).toMatch(/background:\s*var\(--bx-line\)/);
    const dot = ruleFor(billing, ".bx-timeline li::before")[0];
    expect(dot?.body).toMatch(/border-radius:\s*50%/);
    expect(dot?.body).toMatch(/background:\s*var\(--bx-dot\)/);
  });
  it("la hora es mono, de 12px y con color de texto secundario", () => {
    const t = ruleFor(billing, ".bx-timeline .bx-ev-time")[0];
    expect(t?.body).toMatch(/font-size:\s*12px/);
    expect(t?.body).toMatch(/color:\s*var\(--text-2\)/);
  });
});

describe("D5 separación del detalle", () => {
  it("el detalle lleva separador superior y espacio; la fila seleccionada no usa borde izquierdo", () => {
    const d = ruleFor(billing, ".bx-detail")[0];
    expect(d?.body).toMatch(/border-top:/);
    expect(d?.body).toMatch(/margin-top:\s*(2[4-9]|[3-9]\d)px/);
    for (const r of rules(billing).filter((x) => x.selector.includes("data-selected"))) expect(r.body).not.toMatch(/border-(left|inline-start)/);
  });
});

describe("D7 política", () => {
  it("los campos de la rejilla se alinean arriba (no se estiran) y los grupos no tienen borde", () => {
    const label = ruleFor(billing, ".bx-form-grid > label")[0];
    expect(label?.body).toMatch(/align-content:\s*start/);
    const g = ruleFor(billing, ".bx-group")[0];
    expect(g?.body).toMatch(/border:\s*0/);
  });
});
