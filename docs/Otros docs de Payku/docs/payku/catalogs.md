# Catálogos: bancos y medios de pago

Documentación oficial:
- Bancos: https://docs.payku.com/cl/api/banks/
- Métodos de pago: https://docs.payku.com/cl/api/payment-methods/

Los ejemplos cURL **no** muestran headers de autenticación. ⚠️ 💡 Envía igual `Authorization: Bearer`.

---

## Bancos por moneda

```http
GET /api/banks?currency=clp
```

Respuesta ✅:

```json
{
  "status": "success",
  "banks": [
    { "code": "0001", "name": "Banco de Chile", "currency": "CLP" },
    { "code": "0012", "name": "Banco Estado", "currency": "CLP" }
  ]
}
```

Uso: `code` alimenta `accountbank_sbif` (wallet), `bank.sbif` (marketplace) y `additional_parameters.payer_bank` (transacción con transferencia). ✅

---

## Medios de pago

```http
GET /api/paymentmethods
GET /api/paymentmethods?currency=clp
```

Respuesta ✅:

```json
{
  "status": "success",
  "payment_methods": [
    { "currency": "CLP", "payment": 1, "name": "Webpay", "description": "Visa, Mastercard, Magna, American, Diners y Redcompra." },
    { "currency": "CLP", "payment": 9, "name": "MACH", "description": "Paga en comercios online internacionales y nacionales" }
  ]
}
```

`payment` es el código que se envía en `POST /api/transaction` y `POST /api/mall`. ✅

Códigos documentados en "Crear transacción" ✅: `1` Webpay · `4` Etpay · `6` Pago46 · `9` Mach · `19` Fintoc · `23` Tenpo · `26` Floid · `99` Todos · `100` Webpay plus 1–3 cuotas · `101` 4–6 cuotas · `102` 7–12 cuotas.

💡 Consulta este endpoint en vez de fijar los códigos en el código: la cuenta puede tener habilitados solo algunos medios.

⚠️ La tabla de campos de `?currency=clp` en la documentación copia por error los campos de bancos (`code`, `name`).

---

## Sobre "payments"

Payku no tiene un recurso "payment" independiente. La información del pago está en:
- `payment{…}` dentro de una transacción → [transactions.md](transactions.md)
- cobros de suscripción → [subscription-charges.md](subscription-charges.md)
- este catálogo de medios de pago.
