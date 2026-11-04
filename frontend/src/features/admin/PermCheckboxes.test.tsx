import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PermCheckboxes } from "./PermCheckboxes";
import { groupPermissions } from "../shared/utils";

afterEach(cleanup);

describe("groupPermissions", () => {
  it("agrupa por módulo en el orden fijo y omite los grupos vacíos", () => {
    const groups = groupPermissions([
      { code: "tch.clientes.view", description: "Ver clientes TCH" },
      { code: "users.manage", description: "Administrar usuarios" },
      { code: "dashboard.view", description: "Ver dashboard global" },
      { code: "virtualpos.plans.view", description: "Ver planes VirtualPOS" },
      { code: "sync.run", description: "Ejecutar sincronizaciones por canal" },
      { code: "etl.run", description: "Ejecutar ETL y sincronización completa" },
    ]);
    expect(groups.map((g) => g.group)).toEqual(["Administración", "General", "VirtualPOS", "TCH", "Sincronización"]);
    expect(groups.find((g) => g.group === "Sincronización")?.permissions.map((p) => p.code)).toEqual(["sync.run", "etl.run"]);
  });

  it("los nombres de grupo están en español", () => {
    const codes = ["users.manage", "dashboard.view", "virtualpos.x", "toku.x", "payku.x", "tch.x", "etl.x"];
    const names = groupPermissions(codes.map((code) => ({ code, description: "x" }))).map((g) => g.group);
    expect(names).toEqual(["Administración", "General", "VirtualPOS", "Toku", "Payku", "TCH", "Sincronización"]);
  });
});

describe("PermCheckboxes", () => {
  const groups = [{ group: "General", permissions: [{ code: "dashboard.view", description: "Ver dashboard global" }, { code: "zz.nuevo", description: "" }] }];

  it("muestra la descripción en español y, si falta, «Permiso (código)» en vez de nada", () => {
    render(<PermCheckboxes groups={groups} checkedCodes={["dashboard.view"]} />);
    fireEvent.click(screen.getByRole("button", { name: /General \(2\)/ }));
    expect(screen.getByLabelText("Ver dashboard global")).toBeChecked();
    expect(screen.getByLabelText("Permiso (zz.nuevo)")).not.toBeChecked();
  });
});

describe("descripciones de permisos del backend", () => {
  const path = resolve(process.cwd(), "..", "app", "services", "rbac.py");

  it.skipIf(!existsSync(path))("todas las descripciones sembradas están en español (sin palabras inglesas comunes)", () => {
    const source = readFileSync(path, "utf8").split("\r\n").join("\n");
    const block = source.slice(source.indexOf("PERMISSIONS: dict[str, str] = {"), source.indexOf("\n}\n", source.indexOf("PERMISSIONS: dict[str, str] = {")));
    const descriptions = [...block.matchAll(/^\s+"[\w.]+":\s*"([^"]+)",?$/gm)].map((m) => m[1]);
    expect(descriptions.length).toBeGreaterThan(40);
    const english = /\b(the|and|view|manage|create|edit|delete|run|for|can|of|to|all|users|import|export|approve|request)\b/i;
    expect(descriptions.filter((d) => english.test(d))).toEqual([]);
  });
});
