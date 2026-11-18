import { describe, expect, it } from "vitest";
import { menuGroups } from "./navigation";
import { pageLocation } from "./pageNavigation";
import type { AppRoute } from "./routes";

const all = () => true;
describe("Orientación de páginas", () => {
  it("comparte nombres y grupos con cada destino del menú principal", () => {
    for (const group of menuGroups) for (const item of group.items) {
      const action = item.action;
      const route: AppRoute = action.kind === "central" || action.kind === "admin" ? action
        : { kind: action.kind === "billing" ? "billingChanges" : action.kind };
      const page = pageLocation(route, all);
      expect(page.title).toBe(item.label);
      expect(page.crumbs.at(-1)).toEqual({ label: item.label });
      if (group.label) expect(page.crumbs.some((c) => c.label === group.label)).toBe(true);
    }
  });
  it("el detalle tiene enlaces al resumen del canal y a su listado, sin identificadores personales", () => {
    const page = pageLocation({ kind: "record", source: "toku", resource: "customer", externalId: "PRIVATE-RECORD" }, all);
    expect(page.crumbs).toEqual([
      { label: "Dashboard", href: "/central/resumen" }, { label: "Detalle por canal" },
      { label: "Toku", href: "/toku/resumen" }, { label: "Clientes", href: "/toku/clientes" },
      { label: "Detalle de cliente" },
    ]);
    expect(page.title).toBe("Detalle de cliente · Toku");
    expect(JSON.stringify(page)).not.toContain("PRIVATE-RECORD");
  });
  it("no ofrece enlaces a destinos que el usuario no tiene autorizados", () => {
    const page = pageLocation({ kind: "record", source: "payku", resource: "subscription", externalId: "PRIVATE" },
      (r) => r.kind === "resource");
    expect(page.crumbs).toEqual([{ label: "Detalle por canal" }, { label: "Payku" },
      { label: "Suscripciones", href: "/payku/suscripciones" }, { label: "Detalle de suscripción" }]);
  });
  it("TCH distingue la ficha navegable de los detalles internos sin exponer sus datos", () => {
    const route: AppRoute = { kind: "tchSubscription", fileNumber: 98765 };
    expect(pageLocation(route, all).title).toBe("Detalle de suscripción · TCH");
    expect(JSON.stringify(pageLocation(route, all))).not.toContain("98765");
    const page = pageLocation({ kind: "tch", view: "clients" }, all, "client-detail");
    expect(page.crumbs.slice(-2)).toEqual([{ label: "Clientes", href: "/tch/clientes" }, { label: "Detalle de cliente" }]);
  });
  it("editar perfil permite regresar a Mi perfil", () => {
    expect(pageLocation({ kind: "profile", view: "edit" }, all).crumbs.slice(-2)).toEqual([
      { label: "Mi perfil", href: "/mi-perfil" }, { label: "Editar perfil" },
    ]);
  });
});
