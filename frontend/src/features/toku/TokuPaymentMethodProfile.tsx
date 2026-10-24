import { text, record, identifierList } from "../shared/utils";

export function TokuPaymentMethodProfile({ payload }: { payload: Record<string, unknown> }) {
  const customer = record(payload.customer);
  const method = record(payload.payment_method);
  const card = record(method.card);
  const fields = (items: [string, unknown][]) => (
    <dl className="field-list payment-method-fields">
      {items.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{text(value)}</dd>
        </div>
      ))}
    </dl>
  );
  return (
    <>
      <section className="panel">
        <p className="eyebrow">MÉTODO DE PAGO</p>
        <h3>{text(method.type, "Método sin tipo")}</h3>
        {fields([
          ["Estado", method.status],
          ["Gateway", payload.gateway],
          ["Creado", method.created_at],
          ["ID método", method.id],
          ["ID externo", method.external_id],
          ["Cuenta", payload.id_account],
          ["Sesión de checkout", payload.id_checkout_session],
        ])}
      </section>
      <section className="panel client-subscriptions">
        <p className="eyebrow">CLIENTE</p>
        {fields([
          ["Nombre", customer.name],
          ["RUT", customer.government_id],
          ["Correo electrónico", customer.email],
          ["Teléfono", customer.phone_number],
          ["ID cliente", customer.id ?? customer.external_id],
        ])}
      </section>
      {Object.keys(card).length ? (
        <section className="panel client-subscriptions">
          <p className="eyebrow">TARJETA</p>
          {fields([
            ["Marca", card.card_brand],
            ["Tipo", card.card_type],
            ["Titular", card.card_holder],
            ["Últimos dígitos", card.last_digits],
            ["Banco", card.bank_name],
            ["Vencimiento", card.expiration_month && card.expiration_year ? `${card.expiration_month}/${card.expiration_year}` : null],
            ["País emisor", card.institution_country],
            ["3D Secure", card.three_d_secure === true ? "Sí" : card.three_d_secure === false ? "No" : null],
          ])}
        </section>
      ) : null}
      <section className="panel client-subscriptions">
        <p className="eyebrow">ASOCIACIONES</p>
        {fields([
          ["IDs de suscripciones", identifierList(payload.subscription_ids)],
          ["IDs de productos", identifierList(payload.product_ids)],
        ])}
      </section>
    </>
  );
}
