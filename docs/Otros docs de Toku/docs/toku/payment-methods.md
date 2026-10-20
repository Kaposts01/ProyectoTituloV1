# Payment Methods y Customer Collection Accounts

Objeto: <https://docs.trytoku.com/reference/payment-method-object>

## Qué es

Un **Payment Method** es un medio de pago **automático** que un Customer inscribió para que Toku lo cobre después: tarjeta (PAT / Oneclick / PatPass), cuenta bancaria (PAC / domiciliación) o Pix. [Confirmado]

Relaciones [Confirmado]:
- Pertenece a un **Customer**.
- Se asocia a una o más **Subscriptions** (`subscription_ids[]`, `product_ids[]` en la forma agregada) → **N:M**.
- Apunta a un **Payment Instrument** (`id_payment_instrument`). Varios Payment Methods pueden compartir un instrumento.

> ⚠️ **Datos sensibles.** El objeto trae `bank_account.account_number` (número de cuenta completo), `card.token`, `card.bin`, `card.last_digits`, `card_holder`, `pix.tax_id`, códigos QR y links de pago. **No se deben guardar crudos en BD_CENTRAL** y conviene enmascararlos también en STG. Ver [data-model.md](data-model.md#6-datos-sensibles). [Recomendación]

## Objeto Payment Method [Confirmado]

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string `pm_…` | ID |
| `external_id` | string | ID de la organización |
| `provider_external_id` | string | ID en el procesador |
| `id_payment_instrument` | string | Instrumento al que apunta |
| `type` | enum | `card`, `bank_account`, `pix` (define qué subobjeto viene lleno) |
| `status` | enum | 14 valores (ver [statuses.md](statuses.md#payment-method)) |
| `status_history[]` | | `{ new_status, old_status, timestamp }` |
| `gateway` | enum | `transbank_oneclick`, `klap_oneclick`, `patpass`, `toku_pac`, `fintoc_pac`, `universo_pac`, `external_pac`, `ecert_pac`, `manual_pac`, `internal_psp`, `domiciliation`, `mx_banco_*`… (lista abierta) |
| `toku_response_code` | string \| null | Resultado de la última inscripción. `null` en cargas masivas o migraciones |
| `card_brand` | string \| null | `visa`, `mastercard`, … |
| `created_at` | date-time | Fecha de inscripción |
| `payment_method_metadata` | object | |
| `card` / `bank_account` / `pix` | object \| null | Detalle según `type` |

`card`: `token`, `bin`, `last_digits`, `card_holder`, `card_type` (`credit`/`debit`/`prepaid`), `expiration_month`, `expiration_year`, `bank_id`, `bank_name`, `institution_country`, `three_d_secure`, `additional_data`.

`bank_account`: `account_number`, `account_type`, `name`, `bank_id`, `bank_name`, `institution_country`, `additional_data`.

### Forma agregada (`AggregatedPaymentMethod`) [Confirmado]

La devuelven el listado, el detalle y los webhooks:

```json
{
  "payment_method": { "id": "pm_…", "type": "bank_account", "status": "chargeable", "…": "…" },
  "customer": { "id": "cus_…", "external_id": "…", "email": "…" },
  "subscription_ids": ["sub_…"],
  "product_ids": ["…"],
  "gateway": "toku_pac",
  "id_account": "acc_…",
  "id_checkout_session": "…",
  "updated_fields": { "status": "…", "appended_subscriptions": [], "removed_subscriptions": [], "additional": {} }
}
```
`updated_fields` solo viene en el contexto de webhooks. *(Ejemplo ilustrativo.)*

---

## Listar Payment Methods

```http
GET /payment-methods
```
Doc: <https://docs.trytoku.com/reference/get_payment_methods>

| Query | Tipo | Descripción |
|---|---|---|
| `page` / `page_size` | integer | Desde 1; máx. 100 |
| `id_customer` | string | **Métodos de un Customer**: este es el endpoint para "listar los payment methods de un customer" |
| `id_account` | string | |
| `status` | enum | Un estado |
| `gateway`, `toku_product` | string | |
| `external_id` | string 1–128 | |
| `start_date` / `end_date` | date-time | `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DDTHH:MM:SS` |

Respuesta: `{ items: AggregatedPaymentMethod[], total_results }`.
- **Excluye los eliminados.** [Confirmado] Para detectar bajas hay que usar el webhook `payment_method.deleted` o comparar snapshots.
- `total_results` cuenta también los ítems que Toku no pudo construir. Ver [pagination.md](pagination.md).
- Rate limit: **[No confirmado]** numérico.

---

## Obtener Payment Method

```http
GET /payment-methods/{public_id_payment_method}
```
Doc: <https://docs.trytoku.com/reference/get_payment_method_by_id>

Respuesta: la forma agregada.

### Variante obsoleta
```http
GET /payment_method?id={id}            # o ?external_id=
```
Doc: <https://docs.trytoku.com/reference/get_payment_method>. El índice oficial la marca como **"(obsoleto)"** y devuelve un DTO más antiguo (`DTOPaymentMethodV6`). Usar la ruta nueva.

---

## Eliminar Payment Method

```http
DELETE /payment-methods?id_payment_method={id}
```
Doc: <https://docs.trytoku.com/reference/delete_payment_method>

| Query | Tipo | Requerido | Descripción |
|---|---|---|---|
| `id_payment_method` | string | Sí | |
| `force_status_change` | boolean | No (default `false`) | Fuerza el estado `deleted` aunque la transición no esté permitida |

- **Borrado lógico**: queda `status: deleted` con su fecha; se conserva en el historial. Repetirlo no tiene efecto (idempotente). [Confirmado]
- `200 {"success": true}`; `400` si no puede pasar a `deleted` desde su estado actual.
- ⚠️ El ID va en la **query**, no en el path.

---

## Asociar Payment Method a Subscription

```http
POST /subscriptions/associate/payment-method
```
Doc: <https://docs.trytoku.com/reference/associate_subscription>

### Body
| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `id_subscription` | string | **Sí** | Subscription a cobrar |
| `id_payment_method` | string `pm_…` | Uno de estos tres | Medio de pago |
| `token` | string | Uno de estos tres | Alternativa: token del medio |
| `clabe` | string | Uno de estos tres | Alternativa (México) |
| `payment_scope` | `SUBSCRIPTION` \| `CUSTOMER` | No | `SUBSCRIPTION`: solo cobra las Subscriptions donde se inscribió. `CUSTOMER`: puede cobrar cualquier deuda del Customer |
| `exclude_from_recurring` | boolean | No | Sin descripción en la doc |
| `id_orchestration` | string | No | Para procesos asíncronos más grandes |

### Reglas [Confirmado]
- La Subscription y el Payment Method deben ser **del mismo Customer**.
- Estar asociado **no garantiza** que se use ese medio: si hay varios asociados, se cobra con el **activo**.
- `200`: `{ success, message, id_payment_method, id_subscription }`. Con `success: false`, `message` explica por qué. **Siempre revisar `success`, no solo el HTTP status.**
- `400`: la Subscription no existe o no comparte Customer. `404`: el Payment Method no existe.
- **[No confirmado]** Si la llamada reemplaza o agrega asociaciones. Verificarlo con `GET /payment-methods/{id}` → `subscription_ids`.

### En lote
```http
POST /subscriptions/associate/payment-method/batch
```
Doc: <https://docs.trytoku.com/reference/associate_subscription_bulk>

Body `{ "data": [ {…mismo formato…} ] }`, **máximo 500**. Responde `200` **aunque fallen algunos**: revisar `load_summary` (`success`, `error`, `unhandled_error`), `success_detail[]` y `errors_details[]`. `detail` puede indicar que el proceso quedó asíncrono.

---

## Customer Collection Accounts (PAC por API)

Una **Customer Collection Account** es la **cuenta bancaria** que registra un Customer para que Toku le cobre por **PAC** o domiciliación. [Confirmado]

### Crear
```http
POST /customer-collection-accounts
```
Doc: <https://docs.trytoku.com/reference/post_customer_collection_account_endpoint>

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `customer` | `cus_…` | **Sí** | |
| `institution_id` | enum `Institution` | **Sí** | Códigos con prefijo `cl_` o `mx_`; también `mock` para pruebas. Lista abierta |
| `account_number` | string | **Sí** | Se normaliza a alfanumérico |
| `account_type` | enum | **Sí** | `checking_account` (corriente) o `sight_account` (vista) |
| `currency_code` | enum | No | Por defecto, la moneda del país de la organización |
| `subscription` | `sub_…` | No | Si se omite, la cuenta aplica a **todas** las Subscriptions del Customer |
| `government_id` | string | No | RUT del titular; por defecto, el del Customer |

- **Idempotente por (Customer, Subscription)**: si ya existe una cuenta válida para esa combinación, la actualiza. [Confirmado]
- `201` con `{ customer, institution_id, account_number, account_type, currency_code, government_id, subscription }`.
- `404`: Customer o Subscription inexistentes. `422`: no se pudo determinar la moneda.
- **[No confirmado]** Si crear la cuenta genera automáticamente un Payment Method `pm_…` (y en qué estado) o si requiere un paso de activación con el banco o mandato. **Es lo primero que hay que probar** en el flujo [enroll-payment-method](workflows/enroll-payment-method.md). **[Inferencia]** Vale la pena probar `institution_id: "mock"`, que podría servir para pruebas sin afectar un banco real.

### Listar
```http
GET /customer-collection-accounts?customer={cus_id}[&subscription={sub_id}]
```
Doc: <https://docs.trytoku.com/reference/get_customer_collection_account_endpoint>

Devuelve `{ "customer_collection_accounts": [...] }` con las cuentas **activas**, ordenadas por Subscription (las no ligadas van al final). `404` si no hay ninguna.

### Eliminar
Doc: <https://docs.trytoku.com/reference/delete_customer_collection_account_endpoint>. **No verificado en detalle aún.**

### PAC por lote (Chile)
"Crear PACs por lote" / "Eliminar PACs por lote": <https://docs.trytoku.com/reference/create_pacs>. **No verificado en detalle aún.**

---

## Lo que NO es público

| Operación | Estado |
|---|---|
| `POST /payment-methods` (crear Payment Method genérico) | **No aparece en la referencia pública** (llms.txt). Nuestra nota interna dice que es `x-internal: true` y que requiere IDs numéricos internos. **[No confirmado]** como ruta utilizable. **No usar.** |
| `PUT /payment-methods` (editar) | **No aparece en la referencia pública.** No usar. |
| Crear Payment Method de tarjeta | Solo por la **PCI Compliant API** (datos cifrados), que no aplica a nuestro caso |

Para inscribir medios de pago, los caminos públicos son: **portal/Checkout de Toku** (el socio inscribe su tarjeta o PAC), **Collection Accounts** (PAC por API) y **PAC por lote**.

## Webhooks relacionados
`payment_method.attached`, `payment_method.attached_products` (el Customer inscribió un medio en la plataforma), `payment_method.updated`, `payment_method.status_update`, `payment_method.deleted`, `payment_method_inscription_intent.failed`, `payment_instrument.created`, `payment_instrument.updated`, `activation.created` (activación de transferencias en Chile).
