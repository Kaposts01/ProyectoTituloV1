# Transactions y Payment Intents (los "pagos" de Toku)

Objeto: <https://docs.trytoku.com/reference/transaction-object> · Glosario: <https://docs.trytoku.com/docs/glosario>

## Por qué no existe `payments.md`

Toku no expone un recurso "Payment". Un pago se modela con dos objetos: [Confirmado]

| Objeto | Qué es | Analogía |
|---|---|---|
| **Transaction** | Un **movimiento de dinero**: un cobro, una reversa, un contracargo. Puede pagar **varias** Invoices a la vez. | La **boleta del supermercado**: un solo pago |
| **Payment Intent** | La parte de esa Transaction que se aplica a **una** Invoice. Cada Payment Intent está ligado a **exactamente una** Invoice. | Cada **línea** de la boleta: qué deuda saldó y por cuánto |

```text
TRANSACTION (1) ──< PAYMENT INTENT (N) >── (1) INVOICE
```

Así, **Transaction ↔ Invoice es N:M**:
- Una Transaction paga varias Invoices (por ejemplo, un socio paga 3 cuotas atrasadas de una vez en el portal).
- Una Invoice puede tener varias Transactions (intentos fallidos más el exitoso, o pagos parciales).

> ⚠️ El sync actual en Apps Script (`Transaction.js`) guarda solo `payment_intents[0]`. Esto **pierde información** cuando una Transaction paga más de una Invoice. Ver [workflows/sync-toku.md](workflows/sync-toku.md).

Límite: **1 req/s** en `GET /transactions` y `GET /transactions/{id}`. [Confirmado]

## Objeto Transaction [Confirmado]

Requeridos: `id`, `type`, `amount`, `currency`, `transaction_date`, `status`, `transaction_metadata`.

| Campo | Tipo | Descripción | Uso interno |
|---|---|---|---|
| `id` | string | ID de la Transaction | PK |
| `external_id` | string | Referencia de la organización | |
| `provider_external_id` | string | Referencia del procesador | Conciliación bancaria |
| `id_organization`, `id_account` | string | Organización y cuenta de cobro | |
| `id_checkout_session` | string \| null | Checkout de origen | |
| `id_payout` | string \| null | Payout (liquidación) con el que se pagó a la organización. `null` mientras no se liquide | **Conciliación con el banco** |
| `id_charge_scheduled_date` | string | Fecha de cobro programado que lo originó | |
| `amount` | number | Monto | |
| `currency` | enum | `CLP`, `CLF`, `MXN`, `BRL`, `USD`. **Puede diferir de la moneda de las deudas** | |
| `status` | enum | Ver abajo | |
| `status_history[]` | `{ new_status, old_status, timestamp }` | Historial de estados | Auditoría |
| `type` | enum | Ver abajo | |
| `gateway` | string | Procesador (ver <https://docs.trytoku.com/docs/qué-valores-pueden-venir-en-el-campo-gateway>) | |
| `toku_product` | string | Producto Toku (define el medio), por ejemplo `toku_card_on_file`, `transfer_cl` | |
| `response_code` | string | Código normalizado (`SUTOK0000`, etc.). `null` mientras no se resuelve | Ver [errors.md](errors.md) |
| `original_response_message` | string | Mensaje crudo del procesador | |
| `voucher` | string | Comprobante del procesador | |
| `remediation_detail` | string | Motivo, si un cobro fallido se rehízo con éxito | |
| `number_of_installments`, `installment_amount` | | Cuotas (tarjeta) | |
| `transaction_metadata` | object | Datos del cobro (por ejemplo, tipo de tarjeta) | |
| `additional_data` | object | Información extra (por ejemplo, detalle de devolución) | |
| `initialization_date` | ISO 8601 UTC | Creación del registro | |
| `transaction_date` | ISO 8601 UTC | **Fecha del movimiento de dinero** | Fecha efectiva de pago |
| `expiration_date` | ISO 8601 UTC \| null | Hasta cuándo puede resolverse | |

### `status`
| Valor | Significado |
|---|---|
| `INITIALIZED` | El cobro aún no se resuelve |
| `SUCCESS` | Cobro capturado |
| `FAILED` | Rechazado por el procesador |
| `FAILED_INIT` | Deprecado (sin descripción) |
| `ABORTED` | Descartado antes de intentarse, o venció sin resolverse |
| `CAPTURE_PENDING` | Autorización esperando captura |

### `type`
`PAYMENT` (cobro), `EXTERNAL_PAYMENT` (pago registrado fuera de Toku), `REVERSED` (reversa), `CHARGEBACK` (contracargo), `INSCRIPTION` (inscripción de medio de pago). Sin descripción en la doc: `ONETIME`, `INSCRIPTION_REVERSED`, `CARD_ON_FILE_PAYMENT`, `CARDLESS_PAYMENT`, `PATPASS_PAYMENT`, `VOID`, `CHARGEBACK_REVERSAL`.

**`GET /transactions` solo devuelve `PAYMENT`, `REVERSED` y `CHARGEBACK`.** [Confirmado]

## Objeto Payment Intent [Confirmado: campos] / [No confirmado: significado de estados]

Viene **dentro** de la respuesta agregada (`payment_intents[]`); no tiene endpoint propio documentado.

| Campo | Requerido | Descripción |
|---|---|---|
| `id` | Sí | ID del Payment Intent |
| `amount`, `currency` | Sí | Monto aplicado a la Invoice |
| `status` | Sí | Ver [statuses.md](statuses.md#payment-intent) |
| `id_invoice` | Sí | **Invoice que salda** |
| `id_subscription` | Sí | Subscription de esa Invoice |
| `id_account` | Sí | |
| `product_id` | Sí | |
| `price_change_amount` | Sí | **[No confirmado]** su significado. **[Inferencia]** Un ajuste de precio aplicado en el checkout |
| `invoice_external_id`, `invoice_metadata` | No | Copia de datos de la Invoice, útil para cruzar sin otra llamada |
| `type` | No | `recurring` / `one_time` |
| `gateway`, `is_partial`, `is_last_payment`, `billable_exchange_rate`, `rendition_file` | No | |

## Respuesta agregada (`AggregatedTransaction`) [Confirmado]

Tanto el listado como el detalle y los webhooks `transaction.*` devuelven esta forma:

```json
{
  "transaction": { "id": "…", "type": "PAYMENT", "status": "SUCCESS", "amount": 10000, "currency": "CLP",
                   "transaction_date": "2026-10-05T12:00:00Z", "response_code": "SUTOK0000", "…": "…" },
  "customer": { "id": "cus_…", "external_id": "…", "name": "…", "email": "…", "government_id": "…" },
  "payment_intents": [
    { "id": "…", "id_invoice": "in_…", "id_subscription": "sub_…", "amount": 10000, "status": "…", "product_id": "…" }
  ],
  "payment_instrument": { "country": "CL", "…": "…" },
  "wallet_movements": [ { "id": "…", "amount": 0, "type": "…" } ],
  "applied_adjustment_documents": [ { "id": "…", "external_id": "…", "type": "credit_note", "amount": 0 } ]
}
```
*(Ejemplo ilustrativo construido desde el schema; los valores no son reales.)*

Ojo: el Customer agregado usa **`email`**, no `mail` como el objeto Customer. [Confirmado]

---

## Listar Transactions

```http
GET /transactions
```
Doc: <https://docs.trytoku.com/reference/get_public_transactions>

### Query parameters
| Campo | Tipo | Descripción |
|---|---|---|
| `page`, `page_size` | integer | Página desde 1; `page_size` máx. 100 |
| `start_date`, `end_date` | date-time | **Se comparan con la fecha de la transacción.** Formatos: `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DDTHH:MM:SS` (otro formato → `422`). Si solo va la fecha, incluye el día completo |
| `status` | enum | `INITIALIZED`, `SUCCESS`, `FAILED`, `FAILED_INIT`, `ABORTED`, `CAPTURE_PENDING` |
| `types` | array | Subconjunto de `PAYMENT`, `REVERSED`, `CHARGEBACK` (por defecto los tres) |
| `id_customer` | string | |
| `id_invoice` | string | **Transactions que cubren esa Invoice** |
| `id_payment_method` | string | |
| `id_payout` | string | Transactions liquidadas en ese payout |
| `external_id`, `provider_external_id`, `token` | string | |
| `id_customer_action_metadata`, `id_bulk_charge`, `id_charge_scheduled_date` | string | |

Respuesta: `{ items: AggregatedTransaction[], total_results }`. **Paginación por página, 1 req/s.**

**[Inferencia]** No está claro si "fecha de la transacción" es `transaction_date` o `initialization_date`. Una Transaction `INITIALIZED` podría cambiar de estado después de la ventana leída. **[Recomendación]** Releer con solapamiento (el sync actual usa 24 h, lo que es razonable) y además consumir `transaction.status_update` por webhook.

---

## Obtener Transaction

```http
GET /transactions/{public_id_transaction}
```
Doc: <https://docs.trytoku.com/reference/get_transaction>

Respuesta: `AggregatedTransaction`. Responde `400` si el tipo no es `PAYMENT`, `REVERSED` ni `CHARGEBACK`. Límite: 1 req/s.

---

## Otros endpoints de Transactions (no explorados aún)

Listados en la referencia oficial, sin verificar en detalle:

| Operación | Doc |
|---|---|
| Obtener Fees de una Transaction | <https://docs.trytoku.com/reference/get_transaction_fees_public> |
| Crear Transaction externa (registrar un pago hecho fuera de Toku) | <https://docs.trytoku.com/reference/create_external_transaction> |
| Crear / actualizar / eliminar Transactions externas (individual y en lote) | ver llms.txt |
| Capturar / cancelar Preauthorization | <https://docs.trytoku.com/reference/capture_preauth_endpoint> |
| Refund de Transaction / Invoice | <https://docs.trytoku.com/reference/refund_transaction_public> |

**[Recomendación]** Si alguna vez registramos donaciones recibidas por otra vía (transferencia directa a TECHO), "Crear Transaction externa" es probablemente el camino correcto, en lugar de marcar la Invoice con `is_paid: true`. **Verificarlo antes de usarlo.**

## Webhooks relacionados
`transaction.success` (pagos instantáneos: tarjeta, transferencia, efectivo), `transaction.bulk_success` (pagos por lotes: **PAC**, PatPass; payload `{ id, event_type, events: AggregatedTransaction[] }`), `transaction.failed`, `transaction.bulk_failed`, `transaction.status_update`, `transaction.refund`, `transaction.capture_pending`, `transaction.renewed`, `transaction_external.success`, `chargeback.status_update`.
