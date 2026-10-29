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

const themesAll = { claro: lightTokens, oscuro: darkTokens } as const;
const hexOf = (t: Record<string, string>, name: string) => {
  const v = resolve(t, name);
  if (!/^#[0-9a-f]{6}$/i.test(v)) throw new Error(`${name} debe ser hex de 6 digitos, es ${v}`);
  return v;
};

describe("D1 menu azul marino: items, estados y marca >= 4.5:1", () => {
  it("el fondo del menu es azul marino (canal azul domina sobre rojo y verde) en ambos temas", () => {
    for (const t of Object.values(themesAll)) {
      const h = hexOf(t, "--bg-sidebar").slice(1);
      const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
      expect(b).toBeGreaterThan(g);
      expect(b).toBeGreaterThan(r);
    }
    expect(lightTokens["--bg-sidebar"]).toMatch(/^#111727/);
  });
  for (const [name, t] of Object.entries(themesAll)) {
    it(`${name}: texto de item sobre el menu, en hover y activo >= 4.5:1`, () => {
      const bg = hexOf(t, "--bg-sidebar");
      expect(ratio(hexOf(t, "--sidebar-text"), bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--sidebar-text-strong"), bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--sidebar-active-text"), hexOf(t, "--sidebar-active-bg"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--sidebar-label"), hexOf(t, "--sidebar-active-bg"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--sidebar-brand-text"), hexOf(t, "--sidebar-brand-bg"))).toBeGreaterThanOrEqual(4.5);
    });
    it(`${name}: el item activo se distingue del fondo del menu`, () => {
      expect(ratio(hexOf(t, "--sidebar-active-bg"), hexOf(t, "--bg-sidebar"))).toBeGreaterThan(1.1);
    });
  }
  it("el CSS del menu usa tokens, no colores teal fijos", () => {
    expect(finalDecl(allCss, ".sidebar-item.active", "background")).toBe("var(--sidebar-active-bg)");
    expect(finalDecl(allCss, ".sidebar-item", "color")).toBe("var(--sidebar-text)");
    expect(finalDecl(allCss, ".sidebar-item:hover", "background")).toBe("var(--sidebar-hover-bg)");
    expect(finalDecl(allCss, ".sidebar-brand span", "background")).toBe("var(--sidebar-brand-bg)");
    expect(finalDecl(allCss, ".sidebar-item.active", "font-weight")).toBe("700");
    const sidebarBlock = appCss.slice(appCss.indexOf("/* ── Sidebar azul marino"), appCss.indexOf("/* ── Provider group headings"));
    expect(sidebarBlock).not.toMatch(/#2a7a64|#1a3d47|#091418/i);
  });
});

describe("D19 paleta de series --series-N", () => {
  const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6"];
  for (const [name, t] of Object.entries(themesAll)) {
    it(`${name}: cada serie (marca) >= 3:1 sobre --bg-surface`, () => {
      const surface = hexOf(t, "--bg-surface");
      for (const s of SERIES) expect(ratio(hexOf(t, s), surface), `${s} ${name}`).toBeGreaterThanOrEqual(3);
    });
    it(`${name}: las series son todas distintas`, () => {
      const vals = SERIES.map((s) => hexOf(t, s).toLowerCase());
      expect(new Set(vals).size).toBe(SERIES.length);
    });
    it(`${name}: linea de referencia >= 3:1 sobre la superficie y relleno de barra de progreso visible`, () => {
      const surface = hexOf(t, "--bg-surface");
      expect(ratio(hexOf(t, "--chart-ref"), surface)).toBeGreaterThanOrEqual(3);
      expect(ratio(hexOf(t, "--progress-fill"), surface)).toBeGreaterThanOrEqual(3);
    });
  }
  it("series 1 y 2 son violeta e indigo (referencia de inspiracion)", () => {
    const hue = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
      const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return ((h * 60) + 360) % 360;
    };
    for (const t of Object.values(themesAll)) {
      expect(hue(hexOf(t, "--series-1"))).toBeGreaterThan(250);
      expect(hue(hexOf(t, "--series-1"))).toBeLessThan(275);
      expect(hue(hexOf(t, "--series-2"))).toBeGreaterThan(228);
      expect(hue(hexOf(t, "--series-2"))).toBeLessThan(250);
    }
  });
});

describe("chips de meta, delta y semaforo", () => {
  for (const [name, t] of Object.entries(themesAll)) {
    it(`${name}: chips «en meta / lejos de meta / sin meta» con texto >= 4.5:1`, () => {
      for (const k of ["ok", "off", "none"]) {
        expect(ratio(hexOf(t, `--chip-${k}-text`), hexOf(t, `--chip-${k}-bg`)), `chip ${k}`).toBeGreaterThanOrEqual(4.5);
      }
    });
    it(`${name}: delta (texto) >= 4.5:1 sobre --bg-surface`, () => {
      for (const k of ["up", "down", "flat"]) expect(ratio(hexOf(t, `--delta-${k}`), hexOf(t, "--bg-surface")), `delta ${k}`).toBeGreaterThanOrEqual(4.5);
    });
    it(`${name}: semaforo semantico (marcas) >= 3:1 sobre --bg-surface`, () => {
      for (const k of ["paid", "rejected", "pending"]) expect(ratio(hexOf(t, `--status-${k}`), hexOf(t, "--bg-surface")), `status ${k}`).toBeGreaterThanOrEqual(3);
    });
    it(`${name}: tarjeta destacada: texto y subtexto >= 4.5:1, barra >= 3:1`, () => {
      const bg = hexOf(t, "--kpi-hero-bg");
      expect(ratio(hexOf(t, "--kpi-hero-text"), bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--kpi-hero-muted"), bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(hexOf(t, "--kpi-hero-fill"), bg)).toBeGreaterThanOrEqual(3);
      expect(ratio(hexOf(t, "--kpi-hero-fill"), hexOf(t, "--kpi-hero-track"))).toBeGreaterThanOrEqual(1.5);
    });
  }
});
