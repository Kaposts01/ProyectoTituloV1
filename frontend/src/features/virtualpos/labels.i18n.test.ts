import { describe, expect, it } from "vitest";
import { paykuColumns, tokuColumns, tokuRelatedColumns, virtualPosColumns } from "./columns";
import { filterFieldForColumn, stagingFilters, virtualPosClientEditFields, virtualPosFieldForColumn, virtualPosSubscriptionCreateFields } from "./constants";

const ENGLISH = /^(Email|Mail|Status|ID Sub)\b/;

describe("rótulos de columnas y filtros sin inglés", () => {
  it("ninguna columna de VirtualPOS, Toku o Payku usa «Email», «Mail», «Status» ni «ID Sub»", () => {
    const labels: string[] = [];
    for (const r of ["client", "plan", "subscription", "charge", "payment"]) labels.push(...virtualPosColumns(r).map((c) => c.label));
    for (const r of ["customer", "subscription", "payment_method", "invoice", "transaction"]) labels.push(...tokuColumns(r).map((c) => c.label), ...tokuRelatedColumns(r).map((c) => c.label));
    for (const r of ["client", "plan", "subscription", "transaction"]) labels.push(...paykuColumns(r).map((c) => c.label));
    expect(labels.filter((l) => ENGLISH.test(l))).toEqual([]);
    expect(labels).toContain("Correo electrónico");
  });

  it("filtros y formularios tampoco", () => {
    const labels = Object.values(stagingFilters).flatMap((resources) => Object.values(resources).flat().map((o) => o.label));
    labels.push(...virtualPosClientEditFields.map((f) => f.label), ...virtualPosSubscriptionCreateFields.map((f) => f.label));
    expect(labels.filter((l) => ENGLISH.test(l))).toEqual([]);
  });

  it("el filtro y el orden por la columna de correo siguen resolviendo el mismo campo (por clave, no por rótulo)", () => {
    const key = (cols: { key: string; label: string }[]) => cols.find((c) => c.label === "Correo electrónico")!.key;
    expect(virtualPosFieldForColumn("client", key(virtualPosColumns("client")))).toBe("email");
    expect(filterFieldForColumn("virtualpos", "client", key(virtualPosColumns("client")))).toBe("email");
    expect(filterFieldForColumn("payku", "client", key(paykuColumns("client")))).toBe("email");
    expect(filterFieldForColumn("toku", "customer", key(tokuColumns("customer")))).toBe("mail");
  });
});
