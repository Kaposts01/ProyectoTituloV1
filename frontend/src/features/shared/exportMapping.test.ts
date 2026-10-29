import { describe, expect, it } from "vitest";
import { consolidatedExportTarget, exportViewPermission, stagingExportTarget, tchExportTarget } from "./exportMapping";

const base = { filterField: "", filterQuery: "", vpColumnFilters: {} };

describe("stagingExportTarget", () => {
  it("mapea recurso y canal a entidad y permiso de vista", () => {
    expect(stagingExportTarget({ source: "toku", resource: "invoice", ...base })).toMatchObject({ entity: "cobros", canal: "toku", viewPermission: "toku.invoices.view" });
    expect(stagingExportTarget({ source: "toku", resource: "transaction", ...base })).toMatchObject({ entity: "pagos", viewPermission: "toku.transactions.view" });
    expect(stagingExportTarget({ source: "payku", resource: "client", ...base })).toMatchObject({ entity: "clientes", canal: "payku", viewPermission: "payku.clients.view" });
    expect(stagingExportTarget({ source: "virtualpos", resource: "charge", vpPlatform: "virtualpos2", ...base })).toMatchObject({ entity: "cobros", canal: "virtualpos2", viewPermission: "virtualpos.charges.view" });
    expect(stagingExportTarget({ source: "virtualpos", resource: "payment", vpPlatform: "all", ...base })?.canal).toBe("virtualpos");
  });

  it("no exporta planes ni métodos de pago", () => {
    expect(stagingExportTarget({ source: "virtualpos", resource: "plan", ...base })).toBeNull();
    expect(stagingExportTarget({ source: "payku", resource: "plan", ...base })).toBeNull();
    expect(stagingExportTarget({ source: "toku", resource: "payment_method", ...base })).toBeNull();
  });

  it("traduce la búsqueda por campo (Toku/Payku) a filter_field y query del contrato", () => {
    const t = stagingExportTarget({ source: "toku", resource: "customer", ...base, filterField: "government_id", filterQuery: " 11111111-1 " });
    expect(t?.params).toEqual({ filter_field: "rut", query: "11111111-1" });
    expect(t?.ignored).toEqual([]);
    const p = stagingExportTarget({ source: "payku", resource: "client", ...base, filterField: "phone", filterQuery: "123" });
    expect(p?.params).toEqual({ filter_field: "phone", query: "123" });
  });

  it("el filtro de estado va como `status`", () => {
    const t = stagingExportTarget({ source: "toku", resource: "subscription", ...base, filterField: "status", filterQuery: "ACTIVE" });
    expect(t?.params).toEqual({ status: "ACTIVE" });
  });

  it("avisa de los filtros que el contrato no puede aplicar", () => {
    const t = stagingExportTarget({ source: "toku", resource: "invoice", ...base, filterField: "client_rut", filterQuery: "xx" });
    expect(t?.params).toEqual({});
    expect(t?.ignored).toHaveLength(1);
    const amount = stagingExportTarget({ source: "payku", resource: "transaction", ...base, filterField: "amount", filterQuery: "10" });
    expect(amount?.ignored[0]).toContain("monto");
  });

  it("VirtualPOS: filtros por columna, rango de montos y fechas", () => {
    const t = stagingExportTarget({
      source: "virtualpos", resource: "charge", vpPlatform: "virtualpos1", filterField: "", filterQuery: "",
      vpColumnFilters: { subscription_id: "sub-9", status: "PAGADO", amount_min: "100", amount_max: " 900 ", date_from: "2025-01-01", date_to: "2025-01-31", vacio: "  " },
    });
    expect(t?.canal).toBe("virtualpos1");
    expect(t?.params).toEqual({ filter_field: "subscription_id", query: "sub-9", status: "PAGADO", amount_min: "100", amount_max: "900", date_from: "2025-01-01", date_to: "2025-01-31" });
    expect(t?.ignored).toEqual([]);
  });

  it("VirtualPOS: solo cabe una búsqueda de texto; el resto se avisa", () => {
    const t = stagingExportTarget({
      source: "virtualpos", resource: "client", vpPlatform: "all", filterField: "", filterQuery: "",
      vpColumnFilters: { social_id: "1", name: "ab" },
    });
    expect(t?.params).toEqual({ filter_field: "rut", query: "1" });
    expect(t?.ignored).toHaveLength(1);
  });

  it("clientes no admite montos: se avisan en lugar de provocar un 422", () => {
    const t = stagingExportTarget({ source: "virtualpos", resource: "client", ...base, vpColumnFilters: { amount_min: "5" } });
    expect(t?.params.amount_min).toBeUndefined();
    expect(t?.ignored).toHaveLength(1);
  });

  it("VirtualPOS pagos: la búsqueda por RUT no existe en el contrato", () => {
    const t = stagingExportTarget({ source: "virtualpos", resource: "payment", ...base, vpColumnFilters: { social_id: "1-9" } });
    expect(t?.params).toEqual({});
    expect(t?.ignored).toHaveLength(1);
  });
});

describe("consolidatedExportTarget", () => {
  it("usa los mismos campos del contrato y omite una búsqueda vacía", () => {
    expect(consolidatedExportTarget("clientes", "email", " a@b.invalid ").params).toEqual({ filter_field: "email", query: "a@b.invalid" });
    expect(consolidatedExportTarget("suscripciones", "all", "").params).toEqual({});
    expect(consolidatedExportTarget("suscripciones", "status", "x").canal).toBeUndefined();
  });
});

describe("tchExportTarget", () => {
  it("transacciones se exporta como cobros y el período se traduce al mes completo", () => {
    const t = tchExportTarget("transactions", { period: "2024-02" });
    expect(t).toMatchObject({ entity: "cobros", canal: "tch", viewPermission: "tch.transacciones.view" });
    expect(t.params).toEqual({ date_from: "2024-02-01", date_to: "2024-02-29" });
  });
  it("clientes por nombre y suscripciones por estado", () => {
    expect(tchExportTarget("clients", { name: " ana " }).params).toEqual({ filter_field: "name", query: "ana" });
    expect(tchExportTarget("subscriptions", { status: "VIGENTE" }).params).toEqual({ status: "VIGENTE" });
    expect(tchExportTarget("subscriptions", {}).params).toEqual({});
  });
});

describe("exportViewPermission", () => {
  it("sigue la tabla del contrato, incluidas las combinaciones sin permiso", () => {
    expect(exportViewPermission("virtualpos1", "clientes")).toBe("virtualpos.clients.view");
    expect(exportViewPermission("payku", "cobros")).toBeNull();
    expect(exportViewPermission("tch", "pagos")).toBeNull();
    expect(exportViewPermission("tch", "cobros")).toBe("tch.transacciones.view");
  });
});
