import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({
  getJson: vi.fn(async () => ({ items: [], total: 1234, offset: 0, limit: 50 })),
  postJson: vi.fn(),
  downloadFile: vi.fn(),
  friendlyError: (_e: unknown, f: string) => f,
}));

import { RecoveryPanel } from "./RecoveryPanel";
import { RecoveryTable } from "./RecoveryTable";
import { EMPTY_FILTERS, canExport, exportTarget, filtersToParams, listPath } from "./recoveryQuery";

const filters = { ...EMPTY_FILTERS, account: "virtualpos2", rejectionCode: " 51 ", minAmount: "1000", maxAmount: "5000", secondaryStatus: "incobrable", rejectedFrom: "2026-01-01", rejectedTo: "2026-02-01", dateFrom: "2026-03-01" };

describe("filtersToParams", () => {
  it("omite valores vacios", () => {
    expect(filtersToParams("retry", "inactiva", EMPTY_FILTERS).toString()).toBe("bucket=retry");
  });
  it("mapea los filtros nuevos en cargos rechazados", () => {
    const p = filtersToParams("retry", "inactiva", filters);
    expect(Object.fromEntries(p)).toEqual({
      bucket: "retry", date_from: "2026-03-01", account: "virtualpos2", rejection_code: "51", min_amount: "1000", max_amount: "5000",
      secondary_status: "incobrable", rejected_from: "2026-01-01", rejected_to: "2026-02-01",
    });
  });
  it("en socios cancelados envia grupo y no filtros de rechazo", () => {
    const p = filtersToParams("cancelled", "incobrable", filters);
    expect(p.get("group")).toBe("incobrable");
    expect(p.get("account")).toBe("virtualpos2");
    expect(p.has("rejection_code")).toBe(false);
    expect(p.has("secondary_status")).toBe(false);
  });
  it("descarta montos invalidos y no envia filtros al historial", () => {
    expect(filtersToParams("retry", "inactiva", { ...EMPTY_FILTERS, minAmount: "abc", maxAmount: "-3" }).toString()).toBe("bucket=retry");
    expect(filtersToParams("history", "inactiva", filters).toString()).toBe("date_from=2026-03-01");
  });
});

describe("listPath y exportTarget", () => {
  it("construye la URL de listado con paginacion", () => {
    const url = listPath({ tab: "retry", group: "inactiva", filters }, 50, 50);
    expect(url.startsWith("/api/v1/recovery/rejected?")).toBe(true);
    expect(url).toContain("offset=50&limit=50");
    expect(url).toContain("account=virtualpos2");
  });
  it("card-expirations no recibe bucket", () => {
    expect(listPath({ tab: "card", group: "inactiva", filters: EMPTY_FILTERS })).toBe("/api/v1/recovery/card-expirations?offset=0&limit=50");
  });
  it("export de grupo con filtros activos, sin paginacion", () => {
    const t = exportTarget({ tab: "cancelled", group: "incobrable", filters })!;
    expect(t.filename).toBe("socios-incobrable.csv");
    expect(t.path.startsWith("/api/v1/recovery/group/export?group=incobrable")).toBe(true);
    expect(t.path).toContain("min_amount=1000");
    expect(t.path).not.toContain("offset");
  });
  it("export de rechazados usa bucket y no existe para el historial", () => {
    expect(exportTarget({ tab: "card", group: "inactiva", filters: EMPTY_FILTERS })!.path).toBe("/api/v1/recovery/rejected/export?bucket=card");
    expect(exportTarget({ tab: "retry", group: "inactiva", filters: EMPTY_FILTERS })!.filename).toBe("cargos-rechazados-retry.csv");
    expect(exportTarget({ tab: "history", group: "inactiva", filters: EMPTY_FILTERS })).toBeNull();
  });
});

describe("permiso de exportacion", () => {
  it("depende de virtualpos.recovery.export", () => {
    expect(canExport((p) => p === "virtualpos.recovery.export")).toBe(true);
    expect(canExport((p) => p === "virtualpos.recovery.view")).toBe(false);
  });
  it("el boton solo aparece con permiso", async () => {
    const withPerm = render(<RecoveryPanel channel="virtualpos" can={() => true} />);
    (await screen.findAllByText("Buscar"))[0].click();
    expect(await screen.findByText(/Exportar CSV/)).toBeTruthy();
    expect(screen.getByText(/datos personales/)).toBeTruthy();
    expect(screen.getByText(/queda registrada/)).toBeTruthy();
    withPerm.unmount();
    const noPerm = render(<RecoveryPanel channel="virtualpos" can={(p) => p === "virtualpos.recovery.view"} />);
    (await screen.findAllByText("Buscar"))[0].click();
    await screen.findByText("Sin registros para los filtros seleccionados.");
    expect(screen.queryByText(/Exportar CSV/)).toBeNull();
    noPerm.unmount();
  });
});

describe("RecoveryTable", () => {
  it("renderiza columnas nuevas con montos en mono", () => {
    const item = { source: "virtualpos1", account: "virtualpos1", external_id: "c1", subscription_id: "s1", client_name: "Cliente X", monto: 12500, monto_vigente: 9900, rejection_code: "51", rejection_reason: "Fondos insuficientes", rejection_at: "2026-02-03", charge_date: "2026-02-03" };
    render(<RecoveryTable tab="retry" group="inactiva" items={[item]} selected={new Set()} submitting={false} canRetry canChangeCard={false} onToggle={() => {}} onToggleAll={() => {}} onRetry={() => {}} onCardLink={() => {}} />);
    for (const h of ["Cuenta", "Monto vigente (último cobrado)", "Motivo de rechazo", "Fecha de rechazo", "Código"]) expect(screen.getByText(h)).toBeTruthy();
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("$12.500").className).toContain("mono");
    expect(within(row).getByText("$9.900").className).toContain("mono");
    expect(within(row).getByText("51").className).toContain("mono");
    expect(within(row).getByText("Fondos insuficientes")).toBeTruthy();
    expect(within(row).getAllByText("2026-02-03").length).toBe(2);
  });
});
