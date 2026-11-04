import { describe, expect, it } from "vitest";
import { RECOVERY_CHANNELS, enabledAccounts } from "./recoveryChannels";

describe("enabledAccounts", () => {
  const accounts = RECOVERY_CHANNELS.virtualpos.accounts;
  it("produccion: ambas cuentas", () => {
    expect(enabledAccounts(accounts, ["virtualpos1", "virtualpos2", "toku", "tch"]).map((a) => a.value)).toEqual(["virtualpos1", "virtualpos2"]);
  });
  it("sandbox: solo la cuenta 1", () => {
    expect(enabledAccounts(accounts, ["virtualpos1", "toku", "tch"]).map((a) => a.value)).toEqual(["virtualpos1"]);
  });
});
