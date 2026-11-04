/**
 * ADAPTADOR de la ficha general de un cliente (D33): único módulo que conoce las claves del backend
 * `id_cliente`, `id_subscription`, `id_cargo` e `id_transaccion`. Las cuatro secciones quedan con la misma forma
 * (`internalId` es el ID interno de cada tipo de registro), así la pantalla no distingue por nombre de clave.
 */
export type GeneralClientDetailWire = {
  rut?: string;
  clients?: { portal?: string; id_cliente?: string; external_id?: string }[] | null;
  subscriptions?: { portal?: string; id_subscription?: string; external_id?: string; status?: string }[] | null;
  charges?: { portal?: string; id_cargo?: string; external_id?: string; status?: string; amount?: string | null }[] | null;
  transactions?: { portal?: string; id_transaccion?: string; external_id?: string; status?: string; amount?: string | null }[] | null;
};

export type GeneralClientRecord = { portal: string; internalId: string; externalId: string; status: string | null; amount: string | null };
export type GeneralClientDetail = {
  rut: string;
  clients: GeneralClientRecord[];
  subscriptions: GeneralClientRecord[];
  charges: GeneralClientRecord[];
  transactions: GeneralClientRecord[];
};

const record = (portal?: string, internalId?: string, externalId?: string, status?: string, amount?: string | null): GeneralClientRecord => ({
  portal: portal ?? "", internalId: internalId ?? "", externalId: externalId ?? "", status: status ?? null, amount: amount ?? null,
});

export function adaptGeneralClientDetail(wire: GeneralClientDetailWire | null | undefined): GeneralClientDetail {
  const w = wire ?? {};
  return {
    rut: w.rut ?? "",
    clients: (w.clients ?? []).map((c) => record(c.portal, c.id_cliente, c.external_id)),
    subscriptions: (w.subscriptions ?? []).map((s) => record(s.portal, s.id_subscription, s.external_id, s.status)),
    charges: (w.charges ?? []).map((c) => record(c.portal, c.id_cargo, c.external_id, c.status, c.amount)),
    transactions: (w.transactions ?? []).map((t) => record(t.portal, t.id_transaccion, t.external_id, t.status, t.amount)),
  };
}
