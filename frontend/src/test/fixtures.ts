/** Fábricas de datos sintéticos para las pruebas de caracterización (sin datos personales reales). */

type Payload = Record<string, unknown>;

export function rec(source: string, resourceType: string, externalId: string, payload: Payload, extra: Payload = {}) {
  return { id: `rec-${resourceType}-${externalId}`, source, resource_type: resourceType, external_id: externalId, payload, ...extra };
}

export const vpClient = (n: number, over: Payload = {}) => rec("virtualpos1", "client", `cli-${n}`, {
  uuid: `cli-${n}`, first_name: `Persona${n}`, last_name: "Sintética", social_id: `1111111${n}-1`, social_id_type: "1",
  email: `p${n}@example.invalid`, phone_number: `+5690000000${n}`, status: "ACTIVO", type: "PERSONA", private_note: "Nota sintética", ...over,
});

export const vpPlan = (n: number, over: Payload = {}) => rec("virtualpos1", "plan", `plan-${n}`, {
  id: `plan-${n}`, name: `Plan Sintético ${n}`, amount: 10000, currency: "CLP", automatic_renewal: true, is_active: true,
  show_in_terminal: false, frequency_type: "monthly", suscription_url: "https://example.invalid/suscribirse", ...over,
}, { subscription_count: 5, active_subscription_count: 4, cobrable_subscription_count: 3 });

export const vpSubscription = (n: number, over: Payload = {}, extra: Payload = {}) => rec("virtualpos1", "subscription", `sub-${n}`, {
  id: `sub-${n}`, status: "ACTIVA", amount: 10000, suscription_date: "2025-01-10", canceled_at: "", plan_name: "Plan Sintético 1",
  plan_id: "plan-1", currency: "CLP", renewal: "T", client: { social_id: `1111111${n}-1` }, ...over,
}, { secondary_status: "cobrable", last_paid_date: "2025-03-05T00:00:00", ...extra });

export const vpCharge = (n: number, status: string, over: Payload = {}) => rec("virtualpos1", "charge", `chg-${n}`, {
  id: `chg-${n}`, status, amount: 10000, charge_date: "2025-04-05", ...over,
}, { subscription_id: "sub-1", client_name: "Persona1 Sintética", client_social_id: "11111111-1", plan_name: "Plan Sintético 1" });

export const vpPayment = (n: number, over: Payload = {}) => rec("virtualpos1", "payment", `pay-${n}`, {
  social_id: `1111111${n}-1`,
  order: { uuid: `ord-${n}`, authorized_at: "2025-03-05T10:00:00", amount: 10000, status: "pagado", payment_type_code: "VN", deposits: [{ payout_amount: 9500 }] }, ...over,
}, { client_name: "Persona1 Sintética" });

export const tokuCustomer = (n: number, over: Payload = {}) => rec("toku", "customer", `tcu-${n}`, {
  id: `tcu-${n}`, government_id: `2222222${n}-2`, name: `Cliente Toku ${n}`, mail: `t${n}@example.invalid`, phone_number: `+5691111111${n}`, status: "active", ...over,
});

export const tokuSubscription = (n: number, over: Payload = {}, extra: Payload = {}) => rec("toku", "subscription", `tsu-${n}`, {
  id: `tsu-${n}`, amount: 5000, status: "ACTIVE", anchor: "2025-01-05", ...over,
}, { client_rut: `2222222${n}-2`, client_name: `Cliente Toku ${n}`, secondary_status: "cobrable", last_paid_date: "2025-03-01T00:00:00", ...extra });

export const paykuClient = (n: number, over: Payload = {}) => rec("payku", "client", `pcl-${n}`, {
  id: `pcl-${n}`, rut: `3333333${n}-3`, name: `Cliente Payku ${n}`, email: `k${n}@example.invalid`, phone: `+5692222222${n}`, ...over,
});

export const paykuSubscription = (n: number, over: Payload = {}, extra: Payload = {}) => rec("payku", "subscription", `psu-${n}`, {
  id: `psu-${n}`, status: "active", client: { rut: `3333333${n}-3` }, start: "2025-01-05", end: "", ...over,
}, { secondary_status: "cobrable", last_paid_date: null, ...extra });

export const page = (items: unknown[], total = items.length, offset = 0, limit = 100) => ({ items, total, offset, limit });
