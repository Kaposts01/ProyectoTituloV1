import type { CancellationBody, CancellationChannel, CancellationReason, TokuStopMode } from "./types";

export const REASON_CODES: CancellationReason[] = [
  "member_request", "payment_failure", "duplicate_subscription", "deceased", "fraud_suspected", "organization_decision", "other",
];

export type CancellationFormValues = {
  channel: CancellationChannel;
  subscription: string;
  reasonCode: CancellationReason | "";
  comment: string;
  tokuStopMode: TokuStopMode;
  tokuEndDate: string;
  confirmIrreversible: boolean;
};

export const EMPTY_CANCELLATION_FORM: CancellationFormValues = {
  channel: "virtualpos1", subscription: "", reasonCode: "", comment: "", tokuStopMode: "paused", tokuEndDate: "", confirmIrreversible: false,
};

export type CancellationFormErrors = Partial<Record<"subscription" | "reasonCode" | "comment" | "tokuEndDate" | "confirmIrreversible", string>>;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Valida el formulario y arma el cuerpo del API. Los campos de Toku solo viajan en Toku y la confirmación solo en
 * Payku (el API rechaza campos que no corresponden al canal). Sin errores devuelve `body`.
 */
export function validateCancellationForm(values: CancellationFormValues): { errors: CancellationFormErrors; body: CancellationBody | null } {
  const errors: CancellationFormErrors = {};
  const subscription = values.subscription.trim();
  if (!subscription) errors.subscription = "Indique la suscripción que se dará de baja.";
  else if (values.channel === "tch" && !/^\d+$/.test(subscription)) errors.subscription = "En TCH la suscripción es el número de ficha (solo dígitos).";
  if (!values.reasonCode) errors.reasonCode = "Elija el motivo de la baja.";
  const comment = values.comment.trim();
  if (!comment) errors.comment = "El comentario del motivo es obligatorio.";
  if (values.channel === "toku" && values.tokuStopMode === "end_date" && !DATE_RE.test(values.tokuEndDate)) {
    errors.tokuEndDate = "Indique la fecha de término de la suscripción.";
  }
  if (values.channel === "payku" && !values.confirmIrreversible) {
    errors.confirmIrreversible = "Debe confirmar de forma explícita que la baja en Payku es irreversible.";
  }
  if (Object.keys(errors).length > 0 || !values.reasonCode) return { errors, body: null };
  const body: CancellationBody = {
    channel: values.channel, subscription_external_id: subscription, reason_code: values.reasonCode, reason_comment: comment,
  };
  if (values.channel === "toku") {
    body.toku_stop_mode = values.tokuStopMode;
    if (values.tokuStopMode === "end_date") body.toku_end_date = values.tokuEndDate;
  }
  if (values.channel === "payku") body.confirm_irreversible = true;
  return { errors, body };
}
