import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { paykuColumns, tokuColumns, tokuRelatedColumns, virtualPosColumns } from "./columns";
import { filterFieldForColumn, virtualPosFieldForColumn } from "./constants";
import type { TableColumn } from "../shared/types";

/**
 * Paso 2: el filtro y el orden de una columna se resuelven por su CLAVE estable (`key`), nunca por el texto del
 * rótulo. Las claves conservan el texto que tenía el rótulo antes de la traducción porque `?orden=` de la URL
 * las guarda («Telefono», «F. Cancelacion», «Email»): cambiarlas rompería enlaces guardados.
 *
 * TABLA DORADA: columna -> campo de filtro, capturada con el comportamiento anterior al cambio.
 */
const GOLDEN: Record<string, Record<string, Record<string, string | null>>> = {
  "virtualpos": {
    "client": {
      "RUT": "social_id",
      "Nombre": "name",
      "Email": "email",
      "Telefono": "phone_number",
      "Plataforma": null,
      "Estado": "status",
      "Acciones": null
    },
    "plan": {
      "Nombre": "name",
      "Monto": "amount",
      "Subscripciones": null,
      "Activas": null,
      "Cobrables": null,
      "Renovacion": "automatic_renewal",
      "Estado": "is_active",
      "Activo en POS": "show_in_terminal",
      "Plataforma": null
    },
    "subscription": {
      "RUT cliente": "social_id",
      "Estado": "status",
      "Estado sec.": "secondary_status",
      "Monto": "amount",
      "F. Inicio": "suscription_date",
      "F. Cancelacion": "canceled_at",
      "Último cobro": null,
      "Plataforma": null,
      "Acciones": null
    },
    "charge": {
      "ID subscripción": "subscription_id",
      "Cliente": null,
      "RUT cliente": null,
      "Fecha de cargo": "charge_date",
      "Estado": "status",
      "Monto": "amount",
      "Plataforma": null,
      "Acciones": null
    },
    "payment": {
      "RUT cliente": "social_id",
      "Cliente": null,
      "F. Pago": "authorized_at",
      "Monto": "amount",
      "Estado": "status",
      "Plataforma": null,
      "Acciones": null
    }
  },
  "toku": {
    "customer": {
      "RUT": "government_id",
      "Nombre": "name",
      "Mail": "mail",
      "Telefono": "phone_number",
      "Acciones": null
    },
    "subscription": {
      "RUT cliente": "client_rut",
      "Cliente": "client_name",
      "Monto": "amount",
      "Estado": "status",
      "Estado sec.": "secondary_status",
      "Último cobro": null,
      "F. Inicio": "anchor",
      "F. Cancelacion": "end_date",
      "Acciones": null
    },
    "payment_method": {
      "ID": "id",
      "Estado": "status",
      "F. Creacion": "created_at",
      "Cliente": "customer_id",
      "Marca": "card_brand",
      "Terminacion": "last_digits",
      "Banco": "bank_name",
      "Tipo tarjeta": "card_type",
      "Subscripciones": null,
      "Acciones": null
    },
    "invoice": {
      "RUT cliente": "client_rut",
      "Cliente": "client_name",
      "Monto": "amount",
      "Pagado": "is_paid",
      "Estado": "status",
      "Fecha limite": "due_date",
      "Acciones": null
    },
    "transaction": {
      "RUT cliente": "client_rut",
      "Cliente": "client_name",
      "Monto": "amount",
      "Fecha transaccion": "transaction_date"
    }
  },
  "payku": {
    "client": {
      "ID": "id",
      "RUT": "rut",
      "Nombre": "name",
      "Email": "email",
      "Telefono": "phone",
      "Acciones": null
    },
    "plan": {
      "ID": "id",
      "Estado": "status",
      "Nombre": "name",
      "Subscripciones activas": null,
      "Subscripciones cobrables": null
    },
    "subscription": {
      "ID": "id",
      "Estado": "status",
      "Estado sec.": null,
      "Último cobro": null,
      "RUT": "rut",
      "F. Inicio": "start",
      "F. Cancelacion": "end",
      "Acciones": null
    },
    "transaction": {
      "ID": "id",
      "Estado": "status",
      "ID subscripciones": "subscriptions",
      "Monto": "amount",
      "F. Pago": "created_at"
    }
  }
};

const columnsOf = (source: string, resource: string): TableColumn[] =>
  source === "virtualpos" ? virtualPosColumns(resource) : source === "toku" ? tokuColumns(resource) : paykuColumns(resource);

describe("columnas con clave estable", () => {
  it("toda columna tiene una clave no vacía, única dentro de su tabla", () => {
    for (const [source, resources] of Object.entries(GOLDEN)) {
      for (const resource of Object.keys(resources)) {
        const keys = columnsOf(source, resource).map((c) => c.key);
        expect(keys.every((k) => typeof k === "string" && k.length > 0), `${source}/${resource}`).toBe(true);
        expect(new Set(keys).size, `${source}/${resource}`).toBe(keys.length);
      }
    }
    for (const resource of ["customer", "subscription", "payment_method", "invoice", "transaction", "plan"]) {
      expect(tokuRelatedColumns(resource).every((c) => c.key), `relacionadas ${resource}`).toBe(true);
    }
  });

  it("las claves y el campo de filtro que resuelven coinciden con la tabla dorada", () => {
    for (const [source, resources] of Object.entries(GOLDEN)) {
      for (const [resource, expected] of Object.entries(resources)) {
        const actual = Object.fromEntries(columnsOf(source, resource).map((c) => [c.key, filterFieldForColumn(source, resource, c.key)]));
        expect(actual, `${source}/${resource}`).toEqual(expected);
      }
    }
  });

  it("cambiar el texto del rótulo no cambia el campo de filtro ni el de orden", () => {
    for (const [source, resources] of Object.entries(GOLDEN)) {
      for (const [resource, expected] of Object.entries(resources)) {
        const relabelled = columnsOf(source, resource).map((c) => ({ ...c, label: `Rótulo nuevo de ${c.label}` }));
        const actual = Object.fromEntries(relabelled.map((c) => [c.key, filterFieldForColumn(source, resource, c.key)]));
        expect(actual, `${source}/${resource}`).toEqual(expected);
      }
    }
  });

  it("el rótulo de VirtualPOS ya no es la llave de vpColumnFields", () => {
    expect(virtualPosFieldForColumn("client", "Telefono")).toBe("phone_number");
    expect(virtualPosFieldForColumn("client", "Teléfono")).toBeNull();
    expect(virtualPosFieldForColumn("client", "Correo electrónico")).toBeNull();
    expect(virtualPosFieldForColumn("client", "Email")).toBe("email");
  });

  it("la clave de la columna de correo conserva el valor de `?orden=` de los enlaces guardados", () => {
    expect(virtualPosColumns("client").find((c) => c.label === "Correo electrónico")?.key).toBe("Email");
    expect(tokuColumns("customer").find((c) => c.label === "Correo electrónico")?.key).toBe("Mail");
    expect(paykuColumns("client").find((c) => c.label === "Correo electrónico")?.key).toBe("Email");
  });
});

describe("la lista de registros no decide por el texto del rótulo", () => {
  const source = readFileSync(resolve(process.cwd(), "src/features/provider/StagingRecordsList.tsx"), "utf8");

  it("no compara column.label ni lo pasa a las funciones de filtro", () => {
    expect(source).not.toMatch(/column\.label\s*===/);
    expect(source).not.toMatch(/(filterFieldForColumn|virtualPosFieldForColumn)\([^)]*column\.label/);
    expect(source).not.toMatch(/setSortColumn\(column\.label\)/);
    expect(source).not.toMatch(/sortColumn\s*===\s*column\.label/);
  });
});
