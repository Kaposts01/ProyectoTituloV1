#!/usr/bin/env node
/**
 * Capturas de pantalla del SANDBOX del CRM con Playwright (Node). Solo lectura visual.
 *
 *   node scripts/visual/capture_sandbox.mjs login     # ventana visible; el USUARIO inicia sesion; guarda el estado
 *   node scripts/visual/capture_sandbox.mjs capture   # headless con ese estado; PNG + index.json
 *   node scripts/visual/capture_sandbox.mjs --help
 *
 * Playwright NO es dependencia del proyecto: vive fuera (por defecto en el scratchpad de la sesion, carpeta `pw`).
 * Se resuelve desde PLAYWRIGHT_NODE_DIR (carpeta que contiene node_modules/playwright). Ver scripts/visual/README.md.
 *
 * Guardas: solo http://localhost:5174; se abortan las peticiones a otros puertos de localhost (5173/8000 = produccion
 * local) y a hosts externos (salvo fuentes/estilos/imagenes pasivos por GET); se abortan TODAS las peticiones que
 * escriben (POST/PUT/PATCH/DELETE), de modo que ningun clic accidental pueda modificar datos. Salidas solo dentro del
 * scratchpad. El estado de sesion (cookie) nunca se imprime ni se guarda en el repositorio.
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const SCRATCH = "C:\\Users\\Usuario\\AppData\\Local\\Temp\\claude\\C--Users-Usuario-Downloads\\3494c0c2-73e4-5bbb-809f-eb0bb12b4d97\\scratchpad";
const VISUAL_ROOT = path.join(SCRATCH, "visual");
const STATE_FILE = path.join(VISUAL_ROOT, "state.json");
const ORIGIN = "http://localhost:5174";
const LOGIN_TIMEOUT_MS = 10 * 60 * 1000;

const VIEWPORTS = {
  desktop: { width: 1440, height: 900, isMobile: false, hasTouch: false },
  mobile: { width: 390, height: 844, isMobile: true, hasTouch: true },
};
const THEMES = ["light", "dark"];

const HELP = `Uso: node scripts/visual/capture_sandbox.mjs <login|capture> [opciones]

  login     Abre una ventana visible en ${ORIGIN}; inicie sesion a mano (espera hasta 10 min).
            Guarda el estado de sesion en ${STATE_FILE} (fuera del repo) y cierra.
  capture   Headless, con ese estado: recorre las pantallas en 2 viewports x 2 temas y guarda PNG + index.json
            en ${path.join(VISUAL_ROOT, "<timestamp>")}.

Opciones:
  --base-url <url>          Solo se acepta ${ORIGIN} (cualquier otra se rechaza).
  --only <a,b,...>          Solo esas pantallas (nombres de la lista; --list las muestra).
  --viewports <desktop,mobile>   Por defecto ambos.
  --themes <light,dark>     Por defecto ambos.
  --screen-timeout-ms <n>   Tope por pantalla (defecto 60000).
  --list                    Lista las pantallas y sale.
  --help                    Esta ayuda.

Variable: PLAYWRIGHT_NODE_DIR = carpeta con node_modules/playwright (defecto: ${path.join(SCRATCH, "pw")}).
Salida: 0 ok; 1 hubo pantallas con error; 2 argumentos/guardas; 3 falta estado de sesion; 4 Playwright/navegador no disponible.`;

// ----------------------------- utilidades -----------------------------

function fail(code, message) {
  console.error(`ERROR: ${message}`);
  process.exit(code);
}

function parseArgs(argv) {
  const out = { mode: null, baseUrl: ORIGIN, only: null, viewports: Object.keys(VIEWPORTS), themes: THEMES, screenTimeout: 60000, list: false, help: false };
  const args = [...argv];
  while (args.length) {
    const a = args.shift();
    const val = () => {
      const v = args.shift();
      if (v === undefined) fail(2, `Falta el valor de ${a}.`);
      return v;
    };
    if (a === "login" || a === "capture") out.mode = a;
    else if (a === "--help" || a === "-h") out.help = true;
    else if (a === "--list") out.list = true;
    else if (a === "--base-url") out.baseUrl = val();
    else if (a === "--only") out.only = val().split(",").map((s) => s.trim()).filter(Boolean);
    else if (a === "--viewports") out.viewports = val().split(",").map((s) => s.trim());
    else if (a === "--themes") out.themes = val().split(",").map((s) => s.trim());
    else if (a === "--screen-timeout-ms") out.screenTimeout = Number(val());
    else fail(2, `Argumento desconocido: ${a}. Use --help.`);
  }
  return out;
}

function assertBaseUrl(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch {
    fail(2, `URL base invalida: ${raw}`);
  }
  if (u.origin !== ORIGIN) {
    fail(2, `URL base rechazada (${u.origin}). Solo se permite ${ORIGIN} (sandbox). Nunca 5173/8000 ni hosts externos.`);
  }
}

function insideScratch(p) {
  const rel = path.relative(SCRATCH, path.resolve(p));
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
}

function safeWrite(file, data) {
  if (!insideScratch(file)) fail(2, `Escritura fuera del scratchpad rechazada: ${file}`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
}

function cleanUrl(raw) {
  try {
    const u = new URL(raw);
    return `${u.origin}${u.pathname}`; // sin query ni fragmento
  } catch {
    return String(raw).slice(0, 120);
  }
}

function scrub(text) {
  return String(text ?? "")
    .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+/g, "[jwt]")
    .replace(/([?&][^=\s]+)=[^&\s]*/g, "$1=[x]")
    .replace(/(cookie|authorization|token|secret|password)\s*[:=]\s*\S+/gi, "$1=[x]")
    .slice(0, 240);
}

async function loadPlaywright() {
  const dir = process.env.PLAYWRIGHT_NODE_DIR || path.join(SCRATCH, "pw");
  try {
    const req = createRequire(path.join(dir, "noop.cjs"));
    return req("playwright");
  } catch {
    fail(4, `No se pudo cargar 'playwright' desde ${dir}. Defina PLAYWRIGHT_NODE_DIR con la carpeta que contiene node_modules/playwright.`);
  }
}

async function launch(chromium, headless) {
  try {
    return await chromium.launch({ headless });
  } catch (first) {
    try {
      return await chromium.launch({ headless, channel: "chrome" });
    } catch {
      fail(4, `No se pudo abrir Chromium (${scrub(first.message).split("\n")[0]}). Revise %LOCALAPPDATA%\\ms-playwright o instale Chrome.`);
    }
  }
}

/** Guarda de red del contexto: bloquea otros puertos de localhost, navegacion externa y cualquier escritura. */
async function installGuards(context, bucketRef, { allowLogin = false } = {}) {
  await context.route("**/*", async (route) => {
    const req = route.request();
    let u;
    try {
      u = new URL(req.url());
    } catch {
      return route.continue();
    }
    if (u.protocol === "data:" || u.protocol === "blob:" || u.protocol === "about:") return route.continue();
    const note = (why) => bucketRef.current?.blocked.push({ why, method: req.method(), url: cleanUrl(req.url()) });
    const sameOrigin = u.origin === ORIGIN;
    const localhostLike = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(u.hostname);
    if (localhostLike && !sameOrigin) {
      note("localhost distinto de 5174");
      return route.abort("blockedbyclient");
    }
    if (!sameOrigin) {
      const passive = req.method() === "GET" && !req.isNavigationRequest() && ["font", "stylesheet", "image"].includes(req.resourceType());
      if (passive) return route.continue();
      note("host externo");
      return route.abort("blockedbyclient");
    }
    // Unica escritura permitida, y solo en el modo `login` (el usuario inicia sesion el mismo): POST /api/v1/auth/login.
    if (allowLogin && req.method() === "POST" && u.pathname === "/api/v1/auth/login") return route.continue();
    if (!["GET", "HEAD", "OPTIONS"].includes(req.method())) {
      note("escritura bloqueada (solo lectura visual)");
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
}

// ----------------------------- modo login -----------------------------

async function runLogin(pw) {
  if (!insideScratch(STATE_FILE)) fail(2, "Ruta de estado fuera del scratchpad.");
  fs.mkdirSync(VISUAL_ROOT, { recursive: true });
  const browser = await launch(pw.chromium, false);
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "es-CL" });
  await installGuards(context, { current: null }, { allowLogin: true });
  const page = await context.newPage();
  await page.goto(ORIGIN, { waitUntil: "domcontentloaded", timeout: 30000 });
  console.log(`Ventana abierta en ${ORIGIN}. Inicie sesion (espero hasta 10 minutos)...`);
  try {
    // La UI autenticada monta `.app-layout` (sidebar + contenido); la pantalla de login monta `.login-shell`.
    await page.waitForSelector(".app-layout", { state: "attached", timeout: LOGIN_TIMEOUT_MS });
  } catch {
    await browser.close().catch(() => {});
    fail(1, "No se detecto una sesion iniciada (tiempo agotado o ventana cerrada). No se guardo estado.");
  }
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  await context.storageState({ path: STATE_FILE });
  await browser.close();
  console.log(`Sesion detectada. Estado guardado en ${STATE_FILE} (no se imprime su contenido).`);
}

// ----------------------------- pantallas -----------------------------

/** Clics permitidos: solo navegacion y apertura de dialogos; nunca confirmar ni enviar. */
const ACTION_GROUP = '[role="group"][aria-label="Acciones de la solicitud"]';

async function openPendingTab(page) {
  await page.getByRole("tab", { name: /^Pendientes/ }).click();
}

async function selectRow(page, sub) {
  const row = page.locator(`button.bx-row-btn[aria-label*="${sub}"]`).first();
  await row.waitFor({ state: "visible", timeout: 20000 });
  await row.click();
  await page.locator(".bx-detail h2", { hasText: sub }).waitFor({ state: "visible", timeout: 20000 });
  await page.waitForFunction(() => !document.querySelector(".bx-detail")?.innerText.includes("Cargando detalle"), null, { timeout: 20000 });
}

/** nombre -> { label, path, mobileOnly?, steps(page) }. `steps` solo navega/abre; jamas confirma. */
const SCREENS = [
  { name: "dashboard-general", label: "Dashboard general", path: "/central/resumen" },
  { name: "dashboard-virtualpos", label: "Dashboard VirtualPOS", path: "/virtualpos/resumen" },
  { name: "dashboard-toku", label: "Dashboard Toku", path: "/toku/resumen" },
  { name: "dashboard-payku", label: "Dashboard Payku", path: "/payku/resumen" },
  { name: "dashboard-tch", label: "Dashboard TCH", path: "/tch/resumen" },
  { name: "recuperador-vp", label: "Recuperador VirtualPOS", path: "/virtualpos/recuperador-socios" },
  { name: "cambios-pendientes", label: "Cambios de cobro: Pendientes", path: "/general/cambios-de-cobro", steps: async (p) => { await openPendingTab(p); await p.locator("table.bx-table").waitFor({ timeout: 20000 }); } },
  { name: "cambios-historial", label: "Cambios de cobro: Historial", path: "/general/cambios-de-cobro", steps: async (p) => { await p.getByRole("tab", { name: /^Historial/ }).click(); await p.locator("table.bx-table").waitFor({ timeout: 20000 }); } },
  { name: "cambios-renovaciones", label: "Cambios de cobro: Renovaciones", path: "/general/cambios-de-cobro", steps: async (p) => { await p.getByRole("tab", { name: /^Renovaciones/ }).click(); await p.locator("#bx-tabpanel").waitFor(); } },
  { name: "cambios-detalle-aprobada-advertencias", label: "Detalle DEMO-SUB-003 (aprobada, kept_due_today, warnings)", path: "/general/cambios-de-cobro", steps: async (p) => { await openPendingTab(p); await selectRow(p, "DEMO-SUB-003"); } },
  // Una solicitud «fallida» figura en Pendientes (requiere accion), no en Historial.
  { name: "cambios-detalle-fallida", label: "Detalle DEMO-SUB-005 (fallida, E-113)", path: "/general/cambios-de-cobro", steps: async (p) => { await openPendingTab(p); await selectRow(p, "DEMO-SUB-005"); } },
  { name: "cambios-detalle-ejecutada-revision", label: "Detalle DEMO-SUB-011 (ejecutada, revision manual)", path: "/general/cambios-de-cobro", steps: async (p) => { await p.getByRole("tab", { name: /^Historial/ }).click(); await selectRow(p, "DEMO-SUB-011"); } },
  { name: "dialogo-nueva-solicitud", label: "Dialogo Nueva solicitud (sin enviar)", path: "/general/cambios-de-cobro", viewportOnly: true, steps: async (p) => { await p.getByRole("button", { name: "Nueva solicitud", exact: true }).click(); await p.locator('[role="dialog"]').waitFor({ timeout: 20000 }); } },
  {
    name: "dialogo-aprobar", label: "Dialogo Aprobar con comentario (sin confirmar)", path: "/general/cambios-de-cobro", viewportOnly: true,
    steps: async (p) => {
      await openPendingTab(p);
      await selectRow(p, "DEMO-SUB-001");
      const btn = p.locator(ACTION_GROUP).getByRole("button", { name: "Aprobar", exact: true });
      await btn.waitFor({ timeout: 20000 });
      await btn.click(); // solo abre el dialogo; el boton de confirmar NO se pulsa
      const dlg = p.locator('[role="dialog"]');
      await dlg.waitFor({ timeout: 20000 });
      await dlg.locator("textarea").fill("Comentario de ejemplo (la accion no se envia)");
    },
  },
  {
    name: "dialogo-rechazar", label: "Dialogo Rechazar con comentario (sin confirmar)", path: "/general/cambios-de-cobro", viewportOnly: true,
    steps: async (p) => {
      await openPendingTab(p);
      await selectRow(p, "DEMO-SUB-001");
      await p.locator(ACTION_GROUP).getByRole("button", { name: "Rechazar", exact: true }).click();
      const dlg = p.locator('[role="dialog"]');
      await dlg.waitFor({ timeout: 20000 });
      await dlg.locator("textarea").fill("Motivo de ejemplo (la accion no se envia)");
    },
  },
  { name: "admin-politica-aprobaciones", label: "Administracion: Aprobaciones (politica)", path: "/admin/usuarios", steps: async (p) => { await p.getByRole("button", { name: "Aprobaciones", exact: true }).click(); await p.getByRole("heading", { level: 1, name: /Aprobaciones de cambios de cobro/ }).waitFor({ timeout: 20000 }); } },
  { name: "admin-scheduler", label: "Administracion: panel del scheduler", path: "/admin/sincronizaciones" },
  { name: "menu-lateral-movil", label: "Menu lateral movil abierto", path: "/central/resumen", mobileOnly: true, viewportOnly: true, steps: async (p) => { await p.locator("button.burger-btn").click(); await p.locator("aside.sidebar.open, .sidebar.open").first().waitFor({ timeout: 10000 }); } },
];

// ----------------------------- esperas -----------------------------

async function settle(page, notes, first = false) {
  if (first) {
    await page.locator(".app-layout, .login-shell").first().waitFor({ state: "attached", timeout: 30000 });
    if ((await page.locator(".login-shell").count()) > 0 && (await page.locator(".app-layout").count()) === 0) {
      throw new Error("SESION_INVALIDA: la app muestra el login (estado caducado o backend reiniciado). Ejecute `login` de nuevo.");
    }
  }
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => notes.push("networkidle no alcanzado (10 s)"));
  await page
    .waitForFunction(() => !/Cargando|Verificando sesi/i.test(document.body.innerText), null, { timeout: 20000 })
    .catch(() => notes.push("texto 'Cargando' aun visible tras 20 s"));
  await page.evaluate(() => document.fonts?.ready).catch(() => {});
}

async function applyThemeCheck(page, theme, entry) {
  // La app aplica data-theme solo al alternar el tema (el efecto depende de `theme`, no de la sesion), asi que tras una
  // carga fresca el atributo puede faltar aunque localStorage tenga el tema. Se fuerza como lo haria el boton y se verifica.
  let attr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  if (attr !== theme) {
    await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
    entry.themeForced = true;
    attr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  }
  entry.themeApplied = attr === theme;
  if (!entry.themeApplied) throw new Error(`El tema ${theme} no quedo aplicado (data-theme=${attr}).`);
}

async function stableShot(page, file, entry, fullPage = true) {
  // Los dialogos y el menu movil son elementos `position: fixed`: en una captura de pagina completa el velo y el menu
  // quedan mal compuestos (aparecen a mitad de pagina). Esas pantallas se capturan como ventana (`viewportOnly`).
  const opts = { fullPage, animations: "disabled", caret: "hide" };
  let prev = await page.screenshot(opts);
  entry.stable = false;
  for (let i = 0; i < 4; i += 1) {
    await page.waitForTimeout(350); // sondeo de estabilidad visual (graficos animados), no una espera de carga
    const cur = await page.screenshot(opts);
    const same = prev.equals(cur);
    prev = cur;
    if (same) { entry.stable = true; break; }
  }
  safeWrite(file, prev);
}

function withTimeout(promise, ms, label) {
  let t;
  const timer = new Promise((_, rej) => { t = setTimeout(() => rej(new Error(`Tiempo agotado (${ms} ms) en ${label}`)), ms); });
  return Promise.race([promise, timer]).finally(() => clearTimeout(t));
}

// ----------------------------- modo capture -----------------------------

async function runCapture(pw, opts) {
  if (!fs.existsSync(STATE_FILE)) {
    fail(3, `No hay estado de sesion (${STATE_FILE}). Ejecute primero: node scripts/visual/capture_sandbox.mjs login`);
  }
  const chosen = SCREENS.filter((s) => !opts.only || opts.only.includes(s.name));
  if (chosen.length === 0) fail(2, "Ninguna pantalla coincide con --only. Use --list.");
  for (const v of opts.viewports) if (!VIEWPORTS[v]) fail(2, `Viewport desconocido: ${v}`);
  for (const t of opts.themes) if (!THEMES.includes(t)) fail(2, `Tema desconocido: ${t}`);

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
  const runDir = path.join(VISUAL_ROOT, stamp);
  if (!insideScratch(runDir)) fail(2, "Directorio de salida fuera del scratchpad.");
  fs.mkdirSync(runDir, { recursive: true });

  const browser = await launch(pw.chromium, true);
  const index = { generated_at: new Date().toISOString(), base_url: ORIGIN, run_dir: runDir, entries: [] };
  const bucketRef = { current: null };
  const flush = () => safeWrite(path.join(runDir, "index.json"), JSON.stringify(index, null, 2));

  for (const vpName of opts.viewports) {
    for (const theme of opts.themes) {
      const vp = VIEWPORTS[vpName];
      const context = await browser.newContext({
        storageState: STATE_FILE,
        viewport: { width: vp.width, height: vp.height },
        isMobile: vp.isMobile,
        hasTouch: vp.hasTouch,
        deviceScaleFactor: 1,
        locale: "es-CL",
        timezoneId: "America/Santiago",
        colorScheme: theme,
      });
      await installGuards(context, bucketRef);
      await context.addInitScript((t) => {
        try { localStorage.setItem("crm-theme", t); } catch { /* sin almacenamiento */ }
      }, theme);

      for (const screen of chosen) {
        const file = path.join(runDir, `${screen.name}__${vpName}__${theme}.png`);
        const entry = {
          name: screen.name, label: screen.label, viewport: vpName, theme, path: screen.path, file,
          status: "ok", error: null, notes: [], consoleErrors: [], pageErrors: [], httpErrors: [], blockedRequests: [], durationMs: 0,
        };
        if (screen.mobileOnly && vpName !== "mobile") {
          entry.status = "omitida";
          entry.error = "solo aplica al viewport movil";
          entry.file = null;
          index.entries.push(entry);
          flush();
          continue;
        }
        const started = Date.now();
        const bucket = { blocked: entry.blockedRequests };
        bucketRef.current = bucket;
        const page = await context.newPage();
        page.setDefaultTimeout(20000);
        page.on("console", (m) => { if (m.type() === "error") entry.consoleErrors.push({ text: scrub(m.text()), at: cleanUrl(m.location()?.url ?? "") }); });
        page.on("pageerror", (e) => entry.pageErrors.push(scrub(e.message)));
        page.on("response", (r) => { if (r.status() >= 400) entry.httpErrors.push({ status: r.status(), method: r.request().method(), url: cleanUrl(r.url()) }); });
        try {
          await withTimeout((async () => {
            await page.goto(`${ORIGIN}${screen.path}`, { waitUntil: "domcontentloaded", timeout: 30000 });
            await settle(page, entry.notes, true);
            if (screen.steps) {
              await screen.steps(page);
              await settle(page, entry.notes);
            }
            await applyThemeCheck(page, theme, entry);
            await stableShot(page, file, entry, !screen.viewportOnly);
          })(), opts.screenTimeout, screen.name);
        } catch (err) {
          entry.status = "error";
          entry.error = scrub(String(err?.message ?? err).split("\n")[0]);
          try { // captura parcial para diagnostico
            await page.screenshot({ path: file, fullPage: false, timeout: 8000 });
            entry.partial = true;
          } catch { entry.file = null; }
        } finally {
          entry.durationMs = Date.now() - started;
          bucketRef.current = null;
          await page.close().catch(() => {});
        }
        index.entries.push(entry);
        flush();
        console.log(`${entry.status.padEnd(7)} ${screen.name} ${vpName} ${theme}${entry.error ? ` -> ${entry.error}` : ""}`);
      }
      await context.close();
    }
  }
  await browser.close();
  flush();
  const bad = index.entries.filter((e) => e.status === "error").length;
  console.log(`Listo: ${index.entries.length} entradas (${bad} con error). Indice: ${path.join(runDir, "index.json")}`);
  process.exit(bad ? 1 : 0);
}

// ----------------------------- main -----------------------------

const opts = parseArgs(process.argv.slice(2));
if (opts.help || (!opts.mode && !opts.list)) {
  console.log(HELP);
  process.exit(opts.help ? 0 : 2);
}
assertBaseUrl(opts.baseUrl);
if (opts.list) {
  for (const s of SCREENS) console.log(`${s.name}${s.mobileOnly ? " (solo movil)" : ""}  ${s.path}  ${s.label}`);
  process.exit(0);
}
if (opts.mode === "capture" && !fs.existsSync(STATE_FILE)) {
  fail(3, `No hay estado de sesion (${STATE_FILE}). Ejecute primero: node scripts/visual/capture_sandbox.mjs login`);
}
const pw = await loadPlaywright();
if (opts.mode === "login") await runLogin(pw);
else await runCapture(pw, opts);
