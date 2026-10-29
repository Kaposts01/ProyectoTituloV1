import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const indexCss = readFileSync("src/index.css", "utf8");
const appCss = readFileSync("src/App.css", "utf8");
const stagingCss = readFileSync("src/Staging.css", "utf8");
// Orden de import real (AppCore.tsx): App.css y luego Staging.css.
const allCss = `${appCss}\n${stagingCss}`;

/** Bloques `selector { cuerpo }` de nivel superior y de @media (sin anidar mas), en orden de aparicion. */
function rules(css: string): Array<{ selector: string; body: string }> {
  const out: Array<{ selector: string; body: string }> = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) out.push({ selector: m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim(), body: m[2] });
  return out;
}
/** Cuerpos de todas las reglas cuyo selector (lista separada por coma) contiene exactamente `sel`. */
function bodiesFor(css: string, sel: string): string[] {
  return rules(css).filter((r) => r.selector.split(",").map((s) => s.trim()).includes(sel)).map((r) => r.body);
}
function declsOf(body: string): Record<string, string> {
  const d: Record<string, string> = {};
  for (const part of body.split(";")) {
    const i = part.indexOf(":");
    if (i > 0) d[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return d;
}
/** Valor final de `prop` para `sel` tras aplicar todas las reglas en orden. */
function finalDecl(css: string, sel: string, prop: string): string | undefined {
  let v: string | undefined;
  for (const b of bodiesFor(css, sel)) { const d = declsOf(b); if (d[prop] !== undefined) v = d[prop]; }
  return v;
}

function tokens(block: string): Record<string, string> {
  const t: Record<string, string> = {};
  for (const m of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) t[m[1]] = m[2].trim();
  return t;
}
const darkAt = indexCss.indexOf('html[data-theme="dark"]');
const lightTokens = tokens(indexCss.slice(0, darkAt));
const darkTokens = { ...lightTokens, ...tokens(indexCss.slice(darkAt)) };

function resolve(t: Record<string, string>, name: string, depth = 0): string {
  const v = t[name];
  if (v === undefined) throw new Error(`token ${name} no definido`);
  const ref = /^var\((--[\w-]+)\)$/.exec(v);
  if (ref && depth < 8) return resolve(t, ref[1], depth + 1);
  return v;
}
function lum(hex: string): number {
  const h = hex.replace("#", "");
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("C1 ancho fijo del menu lateral", () => {
  it("define --sidebar-w: 220px", () => {
    expect(lightTokens["--sidebar-w"]).toBe("220px");
  });
  it("el aside usa solo la variable, sin encogerse (flex-shrink 0) y sin auto/max-content", () => {
    const bodies = bodiesFor(allCss, ".sidebar");
    expect(bodies.length).toBeGreaterThan(0);
    for (const b of bodies) {
      const d = declsOf(b);
      // unico ancho distinto permitido: el cajon movil (position: fixed, fuera del flujo)
      if (d.width !== undefined) expect(d.width).toMatch(/^(var\(--sidebar-w\)|260px)$/);
    }
    const desktop = bodies.map(declsOf).filter((d) => d.width === "var(--sidebar-w)");
    expect(desktop.length).toBeGreaterThan(0);
    expect(finalDecl(appCss, ".sidebar", "flex")).toBe("0 0 var(--sidebar-w)");
    // la primera regla (escritorio) fija min-width; el cajon movil (fixed) lo libera despues
    expect(declsOf(bodiesFor(appCss, ".sidebar")[0])["min-width"]).toBe("var(--sidebar-w)");
  });
  it("ninguna columna del layout es auto/max-content: la app es flex con contenido que puede encoger", () => {
    expect(finalDecl(appCss, ".app-shell", "min-width")).toBe("0");
    expect(finalDecl(appCss, ".app-layout", "display")).toBe("flex");
    expect(appCss).not.toMatch(/\.app-layout\s*\{[^}]*grid-template-columns/);
  });
  it("las pantallas con scroll interno no empujan al menu (contenedores con min-width 0)", () => {
    expect(finalDecl(appCss, ".app-shell", "flex")).toMatch(/^1 1 0(%|px)?$/);
  });
});

describe("C2 contraste WCAG AA del menu y las pestañas", () => {
  const themes = { claro: lightTokens, oscuro: darkTokens } as const;
  for (const [name, t] of Object.entries(themes)) {
    it(`${name}: etiqueta de grupo del menu >= 4.5:1 sobre --bg-sidebar`, () => {
      expect(ratio(resolve(t, "--sidebar-label"), resolve(t, "--bg-sidebar"))).toBeGreaterThanOrEqual(4.5);
    });
    it(`${name}: etiqueta de grupo activa/hover >= 4.5:1 sobre --bg-sidebar`, () => {
      expect(ratio(resolve(t, "--sidebar-label-active"), resolve(t, "--bg-sidebar"))).toBeGreaterThanOrEqual(4.5);
    });
    it(`${name}: pestaña activa (texto sobre fondo) >= 4.5:1`, () => {
      expect(ratio(resolve(t, "--pill-active-text"), resolve(t, "--pill-active-bg"))).toBeGreaterThanOrEqual(4.5);
    });
    it(`${name}: pestaña en hover (texto sobre --bg-hover) >= 4.5:1`, () => {
      expect(ratio(resolve(t, "--text-1"), resolve(t, "--bg-hover"))).toBeGreaterThanOrEqual(4.5);
    });
  }
  it("las etiquetas de grupo aplican los tokens (la regla final gana en Staging.css)", () => {
    expect(finalDecl(allCss, ".channel-dashboard", "color")).toBe("var(--sidebar-label)");
    expect(finalDecl(allCss, ".channel-dashboard.active", "color")).toBe("var(--sidebar-label-active)");
    expect(finalDecl(allCss, ".channel-dashboard:hover", "color")).toBe("var(--sidebar-label-active)");
  });
  it("el grupo activo no depende solo del color: lleva subrayado", () => {
    expect(finalDecl(allCss, ".channel-dashboard.active", "text-decoration")).toMatch(/underline/);
  });
  it("pestañas channel-btn: activa y activa+hover usan los tokens; hover no usa un fallback casi blanco", () => {
    expect(finalDecl(appCss, ".channel-btn.active", "background")).toBe("var(--pill-active-bg)");
    expect(finalDecl(appCss, ".channel-btn.active", "color")).toBe("var(--pill-active-text)");
    expect(finalDecl(appCss, ".channel-btn.active:hover:not(:disabled)", "background")).toBe("var(--pill-active-bg)");
    expect(finalDecl(appCss, ".channel-btn.active:hover:not(:disabled)", "color")).toBe("var(--pill-active-text)");
    expect(finalDecl(appCss, ".channel-btn:hover:not(:disabled)", "background")).toBe("var(--bg-hover)");
    expect(appCss).not.toMatch(/--surface-hover/);
  });
  it("pestaña activa tiene marca no cromática (peso/borde)", () => {
    expect(finalDecl(appCss, ".channel-btn.active", "font-weight")).toBe("700");
  });
});

describe("C6 boton de despliegue + / −", () => {
  it("glifo centrado y area clicable ampliada", () => {
    const d = (p: string) => finalDecl(allCss, ".sidebar-expand", p);
    expect(d("display")).toBe("grid");
    expect(d("place-items")).toBe("center");
    expect(d("line-height")).toBe("1");
    expect(d("position")).toBe("relative");
    expect(d("background")).toBe("transparent");
    expect(allCss).toMatch(/\.sidebar-expand::after\s*\{[^}]*inset:\s*-/);
  });
  it("en movil el boton mide 44px", () => {
    const mobile = allCss.slice(allCss.indexOf("@media (max-width: 800px)"));
    expect(mobile).toMatch(/\.sidebar-expand\s*\{[^}]*width:\s*44px;[^}]*height:\s*44px/);
  });
});

describe("C5 escala tipografica de encabezados (DESIGN.md: display 22px/700)", () => {
  it("define tokens de escala y h1/h2 de pagina los usan", () => {
    expect(lightTokens["--fs-display"]).toBe("22px");
    expect(finalDecl(allCss, "h1", "font-size")).toBe("var(--fs-display)");
    expect(finalDecl(allCss, "h2", "font-size")).toBe("var(--fs-display)");
    expect(finalDecl(allCss, "h3", "font-size")).toBe("var(--fs-h3)");
    expect(finalDecl(allCss, "h2", "font-weight")).toBe("700");
  });
  it("el hero de canal no usa un clamp mayor que la escala", () => {
    expect(finalDecl(allCss, ".channel-hero h2", "font-size")).toBeUndefined();
  });
  it("la etiqueta superior es mayuscula con tracking", () => {
    expect(finalDecl(allCss, ".eyebrow", "text-transform")).toBe("uppercase");
    expect(finalDecl(allCss, ".eyebrow", "letter-spacing")).toBeDefined();
  });
});
