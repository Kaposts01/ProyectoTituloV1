# Referencia API Toku para sincronizacion de lectura

## Alcance

Este documento describe exclusivamente los endpoints `GET` que consume este
proyecto de Google Apps Script para copiar datos desde Toku a Google Sheets.
No documenta altas, ediciones, eliminaciones, Checkout Sessions, webhooks ni
otros flujos de escritura.

Fuente oficial revisada: <https://docs.trytoku.com/docs/via-api-2>.

Paginas de referencia consultadas el 2026-08-23:

- <https://docs.trytoku.com/reference/introduccion>
- <https://docs.trytoku.com/reference/autenticacion>
- <https://docs.trytoku.com/reference/headers-y-convenciones>
- <https://docs.trytoku.com/reference/rate-limits>
- <https://docs.trytoku.com/reference/get_customers>
- <https://docs.trytoku.com/reference/get_subscriptions>
- <https://docs.trytoku.com/reference/list_invoices>
- <https://docs.trytoku.com/reference/get_public_transactions>
- <https://docs.trytoku.com/reference/get_payment_methods>

La version de contrato publicada por esos endpoints es `2026-07-23`. Esta es
una referencia de integracion, no una copia completa del OpenAPI de Toku.

## Configuracion y seguridad

- Base URL de produccion: `https://api.trytoku.com`.
- La integracion actual usa `x-api-key`; la clave vive solo en la Script
  Property `TOKU_API_KEY`. `TOKU_API_KEY_SANDBOX` habilita llamadas sandbox.
- `TOKU_BASE_URL` es opcional y permite reemplazar la base URL.
- La API tambien admite OAuth M2M con `Authorization: Bearer <access_token>`.
  Segun Toku, habilitar OAuth desactiva la API Key de la organizacion. Este
  proyecto no implementa OAuth M2M para Toku: no configurar OAuth sin adaptar
  antes `ApiCore.js`.
- `x-account-key` selecciona una cuenta de cobro cuando la organizacion tiene
  mas de una. El proyecto no lo envia hoy.
- `x-api-version` fija el contrato por fecha. El proyecto no lo envia hoy; por
  tanto, usa la version que Toku derive para la organizacion. Antes de fijarlo
  en codigo, validar los mappers contra la version elegida.
- Nunca guardar API keys, access tokens ni respuestas crudas con datos
  sensibles en este archivo, en el repositorio o en logs.

## Convenciones comunes

Todas las llamadas actuales son `GET`, sin body, y envian:

```text
accept: application/json
Content-Type: application/json
x-api-key: <Script Property TOKU_API_KEY>
```

Los codigos relevantes para la sincronizacion son:

| HTTP | Significado operativo |
| --- | --- |
| 200 | Pagina leida correctamente. |
| 401 | Falta, vencio o es invalida la credencial. |
| 403 | La credencial no tiene acceso al recurso. |
| 422 | Filtro o formato de parametro invalido. |
| 429 | Limite de tasa excedido; reintentar con backoff exponencial y sin paralelismo. |
| 5xx | Error transitorio de Toku; registrar el fallo y reintentar de forma acotada. |

`page_size` acepta como maximo 100 en los cinco listados que consume el
proyecto. Los filtros son opcionales y no se usan en cargas completas, salvo
en transacciones.

## Endpoints sincronizados

### Customers

```text
GET /customers?page_size=100&next_cursor=<cursor>
```

- Paginacion por cursor: la respuesta es `{ items, next_cursor }`.
- Enviar el `next_cursor` recibido hasta que sea `null`.
- Limite oficial: 20 solicitudes por segundo.
- Filtros disponibles: `mail`, `external_id`, `rfc`, `start_date`, `end_date`.
- `start_date` y `end_date` son ISO 8601 y filtran por fecha de creacion.
- La clave primaria de la hoja es `id`.

Campos leidos por `Customer.js`:

```text
id, external_id, government_id, name, mail, phone_number, silenced_until,
pac_mandate_id, send_mail, default_receipt_type, rfc, tax_zip_code,
fiscal_regime, secondary_emails, metadata, default_agent, agent_phone_number
```

Destino: `Toku Clientes`.

`silenced_until` tambien genera `fecha_silenciado_hasta`,
`mes_silenciado_hasta` y `anio_silenciado_hasta` en UTC.

### Subscriptions

```text
GET /subscriptions?page_size=100&next_cursor=<cursor>
```

- Paginacion por cursor: `{ items, next_cursor }`.
- Limite oficial: 20 solicitudes por segundo.
- Filtros disponibles: `start_date`, `end_date`, `is_recurring`.
- `start_date` y `end_date` son ISO 8601 y filtran por fecha de creacion.
- La clave primaria de la hoja es `id`.

Campos de raiz leidos por `Subscription.js`:

```text
customer, id, product_id, id_account, pac_mandate_id, is_recurring, amount,
due_day, currency_code, receipt_product_code, metadata
```

Campos leidos de `recurring` cuando `is_recurring` es verdadero:

```text
frequency, interval, end_date, status, anchor, creation_lead_days,
max_active_invoices
```

`fecha_inicio` se calcula localmente como el menor `due_date` de las Deudas
asociadas a la suscripcion. `fecha_ultima_deuda_pagada` es el mayor `due_date`
entre sus Deudas con `status = PAID`; no representa una fecha efectiva de pago,
porque ese campo no esta disponible en `GET /invoices`. El valor
`estado_secundario` tampoco viene de Toku: se calcula localmente con metodos
de pago cobrables y deudas pagadas.

Destino: `Toku Suscripciones`.

`recurring.end_date` y `recurring.anchor` conservan sus columnas de fecha
existentes y generan componentes de mes y anio. Las fechas locales calculadas
de inicio, ultima deuda pagada y ultima transaccion exitosa tambien los generan.

### Invoices

```text
GET /invoices?page_size=100&next_cursor=<cursor>
```

- Paginacion por cursor: `{ items, next_cursor }`.
- Limite oficial: 20 solicitudes por segundo.
- Filtros disponibles: `account_id`, `customer_id`, `subscription_id`,
  `general_status`, `in_progress`, `start_date`, `end_date`, `due_date` y
  `due_date_from`.
- `start_date` y `end_date` son ISO 8601; los filtros `due_date*` usan
  `YYYY-MM-DD`.
- La clave primaria de la hoja es `id`.

Campos leidos por `Invoice.js`:

```text
customer, id, subscription, product_id, invoice_external_id, due_date, amount,
paid_amount, currency_code, status, is_paid, is_void,
disable_automatic_payment, receipt_type, id_receipt, source, expiration_date,
expiration_action, link_payment, metadata, max_collection_attempts,
remaining_collection_attempts, account, general_status, in_progress,
refund_data
```

La API marca `EXPIRED` como legado para nuevas invoices. `general_status` y
`status` son campos distintos y ambos se guardan.

Destino: `Toku Deudas`.

`due_date` y `expiration_date` conservan sus columnas `fecha_*` y generan los
componentes `mes_*` y `anio_*` en UTC.

### Transactions

```text
GET /transactions?page=1&page_size=100&start_date=<fecha>&end_date=<fecha>
```

- Paginacion numerica: la respuesta es `{ items, total_results }`.
- Incrementar `page` desde 1 y conservar los filtros en cada pagina.
- Limite oficial: 1 solicitud por segundo.
- El listado solo devuelve tipos `PAYMENT`, `REVERSED` y `CHARGEBACK`; el
  filtro opcional `types` solo acepta esos valores.
- La sincronizacion incremental usa `start_date` y `end_date` en formato
  `YYYY-MM-DDTHH:MM:SS`, UTC y sin milisegundos ni sufijo `Z`, mas un solape
  local de 24 horas.
- La clave primaria de la hoja es `transaction.id`.

Cada item es agregado y contiene `transaction`, `customer`, `payment_intents`,
`payment_instrument` y `wallet_movements`. `Transaction.js` guarda solo el
primer elemento de `payment_intents`; esta es una limitacion conocida del
modelo de hoja.

Campos principales leidos:

```text
transaction.id, type, external_id, amount, currency, transaction_date,
initialization_date, status, response_code, original_response_message, voucher,
id_payout, id_checkout_session, gateway, id_account, toku_product,
transaction_metadata
customer.id, email, name, phone_number, government_id
payment_intents[0].id, id_invoice, id_subscription, invoice_external_id,
product_id, gateway, status, price_change_amount
payment_instrument.type, payment_instrument.card.card_brand,
payment_instrument.card.last_digits, wallet_movements
```

`transaction_date` e `initialization_date` son fechas UTC ISO 8601 en el
contrato oficial. El mapper actual las reduce a `YYYY-MM-DD` al escribir la
hoja. En Suscripciones, `fecha_ultima_transaccion_exitosa` se calcula como la
mayor `transaction_date` de registros con `transaction.status = SUCCESS` y el
`payment_intents[0].id_subscription` correspondiente. No incluye payment
intents adicionales de una misma transaccion.

Destino: `Toku Transacciones`.

`transaction_date` e `initialization_date` generan componentes de mes y anio
en UTC. Sus columnas de fecha mantienen el comportamiento vigente de fecha sin
hora; conservar el timestamp completo sigue siendo el pendiente P2.1.

### Payment Methods

```text
GET /payment-methods?page=1&page_size=100
```

- Paginacion numerica: la respuesta vigente es `{ items, total_results }`.
- Cada item es una forma agregada: `payment_method`, `customer`, `gateway`,
  `id_account`, `product_ids`, `subscription_ids` e `id_checkout_session`.
- No asumir el formato plano legacy; el mapper debe leer
  `item.payment_method` e `item.customer`.
- La pagina no incluye metodos eliminados. `total_results` puede ser mayor que
  los elementos recibidos si Toku no puede construir la forma agregada de un
  metodo.
- Filtros disponibles: `id_customer`, `id_account`, `status`, `gateway`,
  `toku_product`, `start_date`, `end_date`.
- `start_date` y `end_date` aceptan `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS` o
  `YYYY-MM-DDTHH:MM:SS`.
- La clave primaria de la hoja es `payment_method.id`.

Campos leidos por `PaymentMethod.js`:

```text
customer.id, external_id, email, phone_number, government_id, name
payment_method.id, type, status, created_at, external_id,
id_payment_instrument, provider_external_id, payment_method_metadata
payment_method.card.card_brand, card_type, bin, last_digits,
expiration_month, expiration_year, card_holder, bank_name,
institution_country, three_d_secure
payment_method.bank_account, pix, boleto
gateway, id_account, product_ids, subscription_ids, id_checkout_session
```

`bank_account`, `pix` y `boleto` se reducen a un resumen seguro antes de
escribirse: no se guardan numeros de cuenta completos, QR ni codigos Pix. Las
listas de productos, suscripciones y metadata se truncan antes de escribir. No
registrar respuestas crudas de este endpoint.

Destino: `Toku Métodos Pago`.

`created_at` conserva `fecha_creacion` y genera `mes_creacion` y
`anio_creacion` en UTC.

## Relacion con la implementacion

| Recurso | Funcion publica | Paginador |
| --- | --- | --- |
| Customers | `TOKU_SINCRONIZAR_CLIENTES` | `toku_fetchCursorAll_` |
| Subscriptions | `TOKU_SINCRONIZAR_SUSCRIPCIONES` | `toku_fetchCursorAll_` |
| Invoices | `TOKU_SINCRONIZAR_DEUDAS` | `toku_fetchCursorAll_` |
| Transactions | `TOKU_SINCRONIZAR_TRANSACCIONES` | Flujo incremental por pagina |
| Payment Methods | `TOKU_SINCRONIZAR_METODOS_PAGO` | `toku_fetchPageAll_` |

La sincronizacion no debe llamar endpoints de escritura. Los arrays de
encabezados `TOKU_*_HEADERS` en `Config.js` definen el orden contractual de
cada fila: un cambio de mapeo debe conservar ese orden y su clave primaria.

## Mantenimiento

1. Revisar la pagina oficial de cada endpoint antes de cambiar un mapper.
2. Si Toku publica una nueva version, comparar sus campos y paginacion con los
   mappers antes de enviar `x-api-version`.
3. Probar primero con una lectura acotada o sandbox, sin registrar PII ni
   credenciales.
4. Ejecutar `TOKU_PREPARAR_HOJAS` antes de una sincronizacion inicial o cuando
   se agreguen encabezados.
5. Para recuperar transacciones, usar `DEBUG_TOKU_TX_SYNC_STATE` o
   `TOKU_TX_RESET_SYNC`; no borrar Script Properties manualmente.
