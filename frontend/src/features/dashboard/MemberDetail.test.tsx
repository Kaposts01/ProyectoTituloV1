import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MemberDetail } from "./MemberDetail";

afterEach(cleanup);

it("distingue cero de importes no informados y no inventa una moneda", () => {
  render(<MemberDetail member={null} can={() => false} onClose={() => {}} detail={{ rut: "11111111-1", clients: [], subscriptions: [], transactions: [],
    charges: ["0", "", null].map((amount, i) => ({ portal: "virtualpos1", externalId: `DEMO-${i}`, internalId: `DEMO-I${i}`, status: "pagado", amount })) }} />);
  const rows = within(screen.getByRole("region", { name: "Cobros del socio" })).getAllByRole("row");
  expect(within(rows[1]).getAllByRole("cell")[2]).toHaveTextContent("0");
  expect(within(rows[2]).getAllByRole("cell")[2]).toHaveTextContent("—");
  expect(within(rows[3]).getAllByRole("cell")[2]).toHaveTextContent("—");
  expect(screen.getByText("Esta ficha no informa la moneda de los importes.")).toBeTruthy();
  expect(screen.queryByText(/CLP/)).toBeNull();
});
