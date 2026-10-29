import { describe, expect, it } from "vitest";
import { detailChannels, filterMenu, menuGroups, visibleMenu, type DetailAction, type MenuAction } from "./navigation";
import { legacyRedirectPath, parseRoute, routePath, tchPermissionSegment, type AppRoute } from "./routes";

const canAll = () => true;
const canOnly = (...perms: string[]) => (p: string) => perms.includes(p);

const menuRoute = (a: MenuAction): AppRoute => {
  if (a.kind === "central") return { kind: "central", view: a.view };
  if (a.kind === "recovery") return { kind: "recovery" };
  if (a.kind === "billing") return { kind: "billingChanges" };
  if (a.kind === "cancellations") return { kind: "cancellations" };
  return { kind: "admin", view: a.view };
};
const detailRoute = (a: DetailAction): AppRoute => {
  if (a.kind === "channel") return { kind: "channel", source: a.source };
  if (a.kind === "section") return { kind: "resource", source: a.section.source, resource: a.section.resource };
  return { kind: "tch", view: a.view };
};

describe("agrupación del menú de un solo nivel (D29)", () => {
  it("grupos y ítems en el orden acordado, solo con vistas que existen", () => {
    const shape = visibleMenu(canAll).map((g) => [g.label, g.items.map((i) => i.label)]);
    expect(shape).toEqual([
      [null, ["Resumen"]],
      ["Cartera", ["Socios", "Suscripciones"]],
      ["Operación", ["Recuperador", "Cambios de cobro"]],
      ["Sistema", ["Sincronización", "Administración", "Reportes"]],
    ]);
  });

  it("Cobros e Identidad quedan fuera hasta que existan sus vistas (UX-09, UX-11)", () => {
    const labels = menuGroups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).not.toContain("Cobros");
    expect(labels).not.toContain("Identidad");
  });

  it("es de un solo nivel: ningún ítem lleva subítems y los rótulos no se repiten", () => {
    const labels = menuGroups.flatMap((g) => g.items.map((i) => i.label));
    expect(new Set(labels).size).toBe(labels.length);
    for (const item of menuGroups.flatMap((g) => g.items)) expect(Object.keys(item)).not.toContain("items");
  });

  it("cada ítem apunta a una ruta existente que parsea y es canónica (sin redirección)", () => {
    for (const item of menuGroups.flatMap((g) => g.items)) {
      const path = routePath(menuRoute(item.action));
      expect(parseRoute(path), path).not.toBeNull();
      expect(legacyRedirectPath(path), path).toBeNull();
    }
  });

  it("rutas de los ítems que cambian de nombre: Socios, Recuperador y Reportes conservan su URL", () => {
    const path = (id: string) => routePath(menuRoute(menuGroups.flatMap((g) => g.items).find((i) => i.id === id)!.action));
    expect(path("summary")).toBe("/central/resumen");
    expect(path("clients")).toBe("/central/clientes");
    expect(path("subscriptions")).toBe("/central/suscripciones");
    expect(path("recovery")).toBe("/virtualpos/recuperador-socios");
    expect(path("billing")).toBe("/general/cambios-de-cobro");
    expect(path("sync")).toBe("/admin/sincronizaciones");
    expect(path("admin")).toBe("/admin/usuarios");
    expect(path("report")).toBe("/central/reporte-automatico");
  });
});

describe("permisos del menú", () => {
  it("sin permisos no hay ítems ni detalle", () => {
    expect(visibleMenu(canOnly())).toEqual([]);
    expect(detailChannels(canOnly())).toEqual([]);
  });

  it("dashboard.view habilita Resumen, Socios, Suscripciones y Reportes; no Operación ni Sistema", () => {
    const labels = visibleMenu(canOnly("dashboard.view")).flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toEqual(["Resumen", "Socios", "Suscripciones", "Reportes"]);
  });

  it("Operación y Sistema dependen de cada permiso; un grupo sin ítems visibles desaparece", () => {
    expect(visibleMenu(canOnly("virtualpos.recovery.view")).map((g) => [g.label, g.items.map((i) => i.label)])).toEqual([["Operación", ["Recuperador"]]]);
    expect(visibleMenu(canOnly("virtualpos.billing_changes.view")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Cambios de cobro"]);
    expect(visibleMenu(canOnly("sync.run")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Sincronización"]);
    expect(visibleMenu(canOnly("sync_runs.view")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Sincronización"]);
    expect(visibleMenu(canOnly("roles.manage")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Administración"]);
    expect(visibleMenu(canOnly("users.manage")).flatMap((g) => g.items.map((i) => i.label))).toEqual(["Administración"]);
  });

  it("el detalle por canal respeta los permisos de cada canal, como antes", () => {
    const names = (can: (p: string) => boolean) => detailChannels(can).map((c) => c.name);
    expect(names(canOnly("virtualpos.clients.view"))).toEqual(["VirtualPOS"]);
    expect(names(canOnly("toku.invoices.view", "payku.plans.view"))).toEqual(["Toku", "Payku"]);
    expect(names(canOnly("tch.dashboard.view"))).toEqual(["TCH"]);
    // TCH exige tch.dashboard.view aunque tenga permisos de lista (igual que el menú anterior)
    expect(names(canOnly("tch.clientes.view"))).toEqual([]);
    expect(names(canAll)).toEqual(["VirtualPOS", "Toku", "Payku", "TCH"]);
  });

  it("dentro de un canal solo salen las listas permitidas y siempre el resumen del canal", () => {
    const toku = detailChannels(canOnly("toku.customers.view", "toku.invoices.view")).find((c) => c.id === "toku")!;
    expect(toku.items.map((i) => i.label)).toEqual(["Resumen", "Clientes", "Deudas"]);
    const tch = detailChannels(canOnly("tch.dashboard.view", "tch.transacciones.view")).find((c) => c.id === "tch")!;
    expect(tch.items.map((i) => i.label)).toEqual(["Resumen", "Transacciones"]);
  });

  it("ninguna pantalla por canal queda inaccesible: el detalle cubre todas las rutas de lista y resumen de canal", () => {
    const paths = new Set(detailChannels(canAll).flatMap((c) => c.items.map((i) => routePath(detailRoute(i.action)))));
    const expected = [
      "/virtualpos/resumen", "/virtualpos/clientes", "/virtualpos/planes", "/virtualpos/suscripciones", "/virtualpos/cargos", "/virtualpos/transacciones",
      "/toku/resumen", "/toku/clientes", "/toku/suscripciones", "/toku/metodos-pago", "/toku/deudas", "/toku/transacciones",
      "/payku/resumen", "/payku/clientes", "/payku/planes", "/payku/suscripciones", "/payku/transacciones",
      "/tch/resumen", "/tch/clientes", "/tch/suscripciones", "/tch/transacciones",
    ];
    expect([...paths].sort()).toEqual([...expected].sort());
    for (const path of expected) {
      expect(parseRoute(path), path).not.toBeNull();
      expect(legacyRedirectPath(path), path).toBeNull();
    }
  });
});

describe("filtro del menú", () => {
  const full = () => ({ groups: visibleMenu(canAll), channels: detailChannels(canAll) });
  const run = (q: string) => {
    const { groups, channels } = full();
    return filterMenu(groups, channels, q);
  };

  it("sin texto no filtra", () => {
    const { groups, channels } = full();
    expect(run("  ")).toEqual({ groups, channels });
  });

  it("ignora tildes y mayúsculas", () => {
    expect(run("OPERACION").groups.map((g) => g.label)).toEqual(["Operación"]);
    expect(run("sincronizacion").groups.flatMap((g) => g.items.map((i) => i.label))).toEqual(["Sincronización"]);
  });

  it("encuentra ítems del detalle por canal por canal o por rótulo", () => {
    expect(run("toku").channels.map((c) => c.name)).toEqual(["Toku"]);
    expect(run("deudas").channels.flatMap((c) => c.items.map((i) => i.label))).toEqual(["Deudas"]);
    expect(run("zzz")).toEqual({ groups: [], channels: [] });
  });
});

describe("redirecciones de rutas viejas", () => {
  it("la ruta antigua de cambios de cobro redirige a /general/cambios-de-cobro", () => {
    expect(legacyRedirectPath("/virtualpos/cambios-de-cobro")).toBe("/general/cambios-de-cobro");
    expect(legacyRedirectPath("/virtualpos/cambios-de-cobro/")).toBe("/general/cambios-de-cobro");
  });

  it("una barra final resuelve a la misma pantalla del menú y del detalle (sin redirección)", () => {
    for (const path of ["/central/resumen", "/central/clientes", "/central/suscripciones", "/central/reporte-automatico", "/virtualpos/recuperador-socios", "/admin/usuarios", "/admin/sincronizaciones", "/toku/deudas", "/tch/transacciones", "/payku/planes"]) {
      expect(parseRoute(`${path}/`), path).toEqual(parseRoute(path));
      expect(legacyRedirectPath(`${path}/`), path).toBeNull();
      expect(legacyRedirectPath(path), path).toBeNull();
    }
  });

  it("las fichas por canal conservan su ruta (no se rompen enlaces profundos)", () => {
    expect(legacyRedirectPath("/virtualpos/clientes/abc123")).toBeNull();
    expect(parseRoute("/toku/clientes/cus_1")).toEqual({ kind: "record", source: "toku", resource: "customer", externalId: "cus_1" });
    expect(parseRoute("/tch/suscripciones/12")).toEqual({ kind: "tchSubscription", fileNumber: 12 });
  });

  it("rutas desconocidas no se redirigen (AppCore las manda a la pantalla permitida)", () => {
    for (const path of ["/", "/central", "/socios", "/cobros", "/resumen", "/identidad", "/toku/inexistente"]) {
      expect(parseRoute(path), path).toBeNull();
      expect(legacyRedirectPath(path), path).toBeNull();
    }
  });
});

describe("Resumen anterior (transitorio, fuera del menú; se retira con UX-15)", () => {
  it("/central/resumen-clasico resuelve a la vista clásica, es canónica y está distinta del Resumen del menú", () => {
    expect(parseRoute("/central/resumen-clasico")).toEqual({ kind: "central", view: "classic" });
    expect(routePath({ kind: "central", view: "classic" })).toBe("/central/resumen-clasico");
    expect(legacyRedirectPath("/central/resumen-clasico")).toBeNull();
    expect(parseRoute("/central/resumen")).toEqual({ kind: "central", view: "summary" });
  });

  it("no figura en el menú ni en el detalle por canal", () => {
    const paths = menuGroups.flatMap((g) => g.items.map((i) => routePath(menuRoute(i.action))));
    expect(paths).not.toContain("/central/resumen-clasico");
    expect(paths).toContain("/central/resumen");
  });
});

describe("rutas internas en inglés, URLs en español (paso 18)", () => {
  const pairs: Array<[string, AppRoute]> = [
    ["/tch/resumen", { kind: "tch", view: "summary" }],
    ["/tch/clientes", { kind: "tch", view: "clients" }],
    ["/tch/suscripciones", { kind: "tch", view: "subscriptions" }],
    ["/tch/transacciones", { kind: "tch", view: "transactions" }],
    ["/tch/suscripciones/12", { kind: "tchSubscription", fileNumber: 12 }],
    ["/admin/usuarios", { kind: "admin", view: "users" }],
    ["/admin/sincronizaciones", { kind: "admin", view: "sync" }],
  ];
  it.each(pairs)("%s ida y vuelta con la ruta interna", (path, route) => {
    expect(parseRoute(path)).toEqual(route);
    expect(routePath(route)).toBe(path);
    expect(legacyRedirectPath(path)).toBeNull();
  });
  it("el permiso de cada lista de TCH conserva el segmento en español (contrato con el backend)", () => {
    expect(tchPermissionSegment("clients")).toBe("clientes");
    expect(tchPermissionSegment("subscriptions")).toBe("suscripciones");
    expect(tchPermissionSegment("transactions")).toBe("transacciones");
  });
  it("las URLs en inglés de las vistas internas no existen", () => {
    for (const path of ["/tch/clients", "/tch/transactions", "/admin/users", "/admin/sync"]) expect(parseRoute(path), path).toBeNull();
  });
});
