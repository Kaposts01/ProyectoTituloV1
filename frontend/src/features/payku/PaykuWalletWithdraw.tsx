import { useCallback, useEffect, useState } from "react";
import { apiErrorCodeIs, friendlyError, getJson, postJson } from "../../api";
import { label } from "../../i18n/label";
import { money } from "../general/unifiedDisplay";

export const WALLET_URL = "/api/v1/writes/payku/wallet";
export const WALLET_WITHDRAW_URL = "/api/v1/writes/payku/wallet/withdraw";
export const WALLET_WITHDRAW_PERMISSION = "payku.wallet.withdraw";

export type WalletBalance = { enabled: boolean; amount_available: number | null; currency: string | null };

const t = (key: string) => label("walletWithdraw", key);

/**
 * Botón «Retirar fondos» de la billetera Payku (CRM-14F). Solo se monta con el permiso `payku.wallet.withdraw`.
 * Lee el saldo, muestra el monto en un diálogo de confirmación y envía ese monto como `expected_amount`: el backend
 * relee el saldo y retira TODO el disponible solo si sigue siendo el mismo.
 */
export function PaykuWalletWithdraw() {
  const [balance, setBalance] = useState<WalletBalance | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setBalance(await getJson<WalletBalance>(WALLET_URL));
    } catch (exc) {
      setBalance(null);
      setLoadError(friendlyError(exc));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const amount = balance?.amount_available ?? 0;
  const canWithdraw = Boolean(balance?.enabled) && amount > 0;

  async function confirm() {
    setSending(true);
    setError(null);
    try {
      await postJson(WALLET_WITHDRAW_URL, { expected_amount: amount });
      setConfirming(false);
      setDone(true);
      await load();
    } catch (exc) {
      setError(friendlyError(exc));
      if (apiErrorCodeIs(exc, "payku_wallet_balance_changed")) await load();
    } finally {
      setSending(false);
    }
  }

  return (
    <article className="panel wallet-withdraw-panel" aria-label={t("title")}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">PAYKU</p>
          <h3>{t("title")}</h3>
        </div>
      </div>
      {loadError ? <p className="error-message" role="alert">{loadError}</p> : null}
      {!balance && !loadError ? <p className="muted-copy">{t("loading")}</p> : null}
      {balance ? (
        <>
          {balance.enabled ? (
            <p>
              {t("available label")}: <strong className="mono" data-testid="wallet-available">{money(amount, balance.currency ?? "CLP")}</strong>
            </p>
          ) : (
            <p className="muted-copy">{t("disabled")}</p>
          )}
          {balance.enabled && amount <= 0 ? <p className="muted-copy">{t("empty")}</p> : null}
          {done ? <p className="success-message" role="status">{t("done")}</p> : null}
          <button
            type="button"
            className="secondary-button"
            disabled={!canWithdraw}
            onClick={() => {
              setError(null);
              setDone(false);
              setConfirming(true);
            }}
          >
            {t("button")}
          </button>
        </>
      ) : null}
      {confirming && balance ? (
        <div className="edit-dialog-backdrop" role="presentation">
          <section className="edit-dialog" role="dialog" aria-modal="true" aria-label={t("dialog title")}>
            <div className="edit-dialog-heading">
              <div>
                <p className="eyebrow">PAYKU / BILLETERA</p>
                <h3>{t("dialog title")}</h3>
              </div>
            </div>
            <p className="edit-dialog-note">{t("dialog note")}</p>
            <p>
              {t("amount label")}: <strong className="mono" data-testid="wallet-confirm-amount">{money(amount, balance.currency ?? "CLP")}</strong>
            </p>
            {error ? <p className="error-message form-error" role="alert">{error}</p> : null}
            <div className="edit-dialog-actions">
              <button type="button" className="cancel-subscription-button" disabled={sending} onClick={() => void confirm()}>
                {sending ? t("sending") : t("confirm")}
              </button>
              <button type="button" className="cancel-button" disabled={sending} onClick={() => setConfirming(false)}>
                {t("back")}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </article>
  );
}
