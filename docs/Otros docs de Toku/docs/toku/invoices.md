# Invoices

Objeto: <https://docs.trytoku.com/reference/invoice-object>

## Qué es

Una **Invoice** es una **deuda/cuota** de un Customer. Siempre pertenece a una Subscription. [Confirmado]

- Si la Subscription es recurrente, Toku crea las Invoices automáticamente.
- Si no lo es, las carga la organización con `POST /invoices`.

**Invoice de Toku ≠ Cargo Programado de VirtualPOS.** La Invoice es la **deuda** (lo que se debe cobrar). El intento o resultado del cobro es otra entidad (Payment Intent / Transaction). En VirtualPOS, el "cargo programado" mezcla deuda y ejecución. **[Inferencia]** Hay que mapearlos por separado.

**Autenticación y errores comunes:** ver [authentication.md](authentication.md) y [errors.md](errors.md). Límite: **20 req/s**.

## Objeto Invoice [Confirmado]

Requeridos en la respuesta: `id`, `customer`, `subscription`, `product_id`, `due_date`, `status`. En los **listados** (`GET /invoices` y `/invoices/chargeable`) también son requeridos `general_status` e `in_progress`.

| Campo | Tipo | Descripción | Uso interno |
|---|---|---|---|
| `id` | string `in_…` | ID público | PK |
| `customer` | string `cus_…` | Deudor | FK |
| `subscription` | string `sub_…` | Subscription dueña | FK |
| `account` | string `acc_…` | Cuenta de cobro | |
| `product_id` | string | Producto de la Subscription | |
| `invoice_external_id` | string ≤256 | ID externo de la deuda. **Único dentro de una Subscription.** Distingue dos deudas del mismo producto con el mismo vencimiento. | Llave con nuestra "cuota" |
| `due_date` | `YYYY-MM-DD` | Vencimiento | |
| `amount` | number | Monto. Decimales: CLP 0, MXN/BRL/USD 2, CLF 4 | |
| `paid_amount` | number | Monto ya pagado (pagos parciales) | |
| `currency_code` | enum | `CLP`, `CLF`, `MXN`, `BRL`, `USD` | |
| `status` | enum | **Estado detallado** (13 valores, ver [statuses.md](statuses.md)) | Guardar crudo |
| `general_status` | enum | **Estado general**: `paid`, `partially_paid`, `unpaid`, `void`, `expired`. *Un cobro en curso no cambia el estado general.* Solo garantizado en listados | Estado "de negocio" |
| `in_progress` | boolean | Hay un cobro en curso (sin confirmar ni rechazar). Solo garantizado en listados | |
| `is_paid` | boolean | Pagada | |
| `is_void` | boolean | Anulada (se trata como eliminada) | |
| `disable_automatic_payment` | boolean | Excluida del cobro automático aunque haya un medio de pago activo | |
| `expiration_date` | date-time | Después de esta fecha no se intenta cobrar | |
| `expiration_action` | enum | `EXPIRE` (legado → estado `EXPIRED`, deprecado), `VOID`, `DELETE` | |
| `max_collection_attempts` / `remaining_collection_attempts` | integer | Intentos de cobro. Cambiar el máximo **resetea** los restantes | |
| `link_payment` | URL | Vacío = portal de Toku. Solo se llena si se usa un procesador externo | |
| `receipt_type` | enum | `bill`, `invoice`, `no_receipt` | |
| `id_receipt` | integer | Documento tributario asociado | |
| `source` | string \| null | Origen (carga masiva, integración, suscripción recurrente) | Distingue las automáticas de las manuales |
| `metadata` | object | Valores ≤256 caracteres; claves declaradas en la webapp | |
| `refund_data` | object \| null | `refund_status` (`success`/`failed`), `refund_amount`, `refund_reason`, `id_transaction_payment`, `id_transaction_refund` | |

**No hay `paid_at`, `created_at` ni `updated_at`.** [Confirmado por ausencia] **No se puede saber la fecha efectiva de pago desde la Invoice**: hay que ir a la Transaction (`transaction_date`) a través del Payment Intent (`id_invoice`). Esto coincide con la limitación ya anotada en `Toku_API_Documentacion.md`.

## ¿Cómo sé si una Invoice está pagada? [Confirmado + Recomendación]

| Pregunta | Campo |
|---|---|
| ¿Pagada completa? | `general_status == "paid"` (o `is_paid == true`) |
| ¿Pagada fuera de Toku? | `status == "EXTERNALLY_PAID"` |
| ¿Pago parcial? | `general_status == "partially_paid"`; ver `paid_amount` vs `amount` |
| ¿Se está cobrando ahora (PAC/PAT en proceso)? | `in_progress == true`. **No tocarla.** Toku advierte que no se debe borrar ni modificar una deuda "En proceso de cobro" para evitar cobros duplicados |
| ¿Anulada? | `general_status == "void"` / `is_void == true` |
| ¿Cuándo y con qué se pagó? | Payment Intent con `id_invoice` → su Transaction (ver [transactions.md](transactions.md)) |

---

## Listar Invoices

```http
GET /invoices
```
Doc: <https://docs.trytoku.com/reference/list_invoices>

### Propósito
Recorrer o conciliar Invoices. Es el endpoint principal de sincronización.

### Query parameters
| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `page_size` | integer | No | 50 por defecto, máx. 100 |
| `next_cursor` | string | No | Cursor |
| `account_id` | string `acc_…` | No | |
| `customer_id` | string `cus_…` | No | |
| `subscription_id` | string `sub_…` | No | |
| `general_status` | array enum | No | `paid`, `partially_paid`, `unpaid`, `void`, `expired`. Repetible: `?general_status=unpaid&general_status=partially_paid` |
| `in_progress` | boolean | No | Solo las que tienen un cobro en curso |
| `start_date` / `end_date` | date-time | No | **Fecha de creación** (inclusive) |
| `due_date` | `YYYY-MM-DD` | No | Vencimiento exacto |
| `due_date_from` | `YYYY-MM-DD` | No | Vencimiento desde (inclusive) |

**Paginación por cursor.** No hay `due_date_to`: para acotar por arriba hay que filtrar del lado nuestro.

---

## Crear Invoice (upsert)

```http
POST /invoices
```
Doc: <https://docs.trytoku.com/reference/create_or_update_invoice>

### Propósito
Crea una deuda o la actualiza si coincide la clave de negocio.

**Idempotencia** [Confirmado]: por `product_id + due_date`, **o** por `product_id + invoice_external_id`. `201` si la creó, `200` si la actualizó.

### Request body
| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `customer` | `cus_…` | **Sí** | |
| `due_date` | `YYYY-MM-DD` | **Sí** | |
| `subscription` | `sub_…` | Una de las dos | Si no se envía, se usa `product_id` |
| `product_id` | string ≤256 | Una de las dos | **Si no existe la Subscription, Toku la crea** (no recurrente) |
| `invoice_external_id` | string ≤256 | Recomendado | |
| `amount` | number ≥0 | | Respetar los decimales de la moneda |
| `currency_code` | enum | | Por defecto, la moneda de la Account |
| `disable_automatic_payment` | boolean | | **En pruebas: `true`** |
| `expiration_date` | `YYYY-MM-DD HH:MM:SS` (hora local de la org.) o ISO 8601 con zona | | |
| `expiration_action` | `VOID` \| `DELETE` \| `EXPIRE` \| `""` | | `EXPIRE` es legado; usar `VOID` o `DELETE` |
| `max_collection_attempts` | integer o `""` | | `""` quita el límite |
| `is_paid` | boolean | | `true` registra un **pago externo** por el total. `false` borra el pago externo registrado (no deshace un pago cobrado por Toku) |
| `is_void` | boolean | | |
| `link_payment` | URL | | |
| `receipt_type`, `id_receipt`, `metadata`, `source` (≤32) | | | |

```json
{
  "customer": "cus_…",
  "product_id": "TEST-DEUDA-PUNTUAL",
  "invoice_external_id": "TEST-DEUDA-0001",
  "due_date": "2026-11-05",
  "amount": 20000,
  "currency_code": "CLP",
  "receipt_type": "no_receipt",
  "disable_automatic_payment": true
}
```

⚠️ Este endpoint **no lleva query params** (la colección Postman tiene un `?page_size=100` sobrante).

---

## Listar Invoices cobrables

```http
GET /invoices/chargeable
```
Doc: <https://docs.trytoku.com/reference/get_paginated_chargeable_invoices>

Las Invoices que **se pueden cobrar ahora**. Excluye pagadas, anuladas y no cobrables. Sirve para armar una corrida de cobro. Paginación por cursor, con orden estable. Sin filtros, salvo `page_size` y `next_cursor`.

---

## Listar Invoices de un Customer (Account autenticada)

```http
GET /invoices/customer/{customer_encrypted_id}
```
Doc: <https://docs.trytoku.com/reference/list_invoices_by_customer>

Array sin paginar. **Diferencia con `GET /customers/{id}/invoices`:** este responde `404` cuando el Customer no tiene Invoices. En el código, tratar ese `404` como "lista vacía".

---

## Buscar Invoice por identificador externo

```http
GET /invoices/lookup?invoice_external_id={invoice_external_id}
```
Doc: <https://docs.trytoku.com/reference/lookup_invoice>

Único parámetro documentado: `invoice_external_id`. La combinación debe identificar una sola Invoice dentro de la Account. **[Inferencia]** Como `invoice_external_id` es único **dentro de una Subscription** (no globalmente), dos Subscriptions podrían tener el mismo valor. **[Recomendación]** Hacer el `invoice_external_id` globalmente único (por ejemplo, incluir el ID de la cuota de BD_CENTRAL).

---

## Obtener Invoice

```http
GET /invoices/{encrypted_invoice_id}
```
Doc: <https://docs.trytoku.com/reference/get_invoice>

`404` si no existe o no pertenece a la organización/Account.

---

## Editar Invoice

```http
PUT /invoices/{encrypted_invoice_id}
```
Doc: <https://docs.trytoku.com/reference/edit_invoice>

- Parcial: solo cambian los campos enviados.
- Campo extra que no está en el POST: `payment_amount` (>0). **Requiere `is_paid: true` en el mismo request**; si no, `422`. **[Inferencia]** Sirve para registrar un pago externo parcial.
- **[No confirmado]** Qué estados permiten edición. Evitar editar con `in_progress: true`.

---

## Anular Invoice

```http
POST /invoices/{encrypted_invoice_id}/void
```
Doc: <https://docs.trytoku.com/reference/void_invoice>

### Body
| Campo | Tipo | Notas |
|---|---|---|
| `delete_invoice` | boolean | Requerido en el schema. **Si se omite el body, se asume `true` y la Invoice se borra.** `false` la conserva como registro histórico |
| `metadata` | object | Se mezcla (merge) con la metadata existente |

Respuesta `200` con la Invoice (`is_void: true`, `status: "VOID"`).

> ⚠️ El método es **`POST`**, no `PUT`. [Confirmado] **[Recomendación]** Enviar siempre `{"delete_invoice": false}` para conservar trazabilidad.

---

## Eliminar Invoice

```http
DELETE /invoices/{encrypted_invoice_id}
```
Doc: <https://docs.trytoku.com/reference/delete_invoice>

| Código | Significado |
|---|---|
| `204` | Eliminada (irreversible) |
| `202` | **Diferida**: tiene un cobro en curso que no se puede abortar. Se borrará cuando se resuelva (solo si la organización tiene habilitado el diferido). Body: la Invoice |
| `409` | Mismo caso, sin diferido habilitado (descrito en el texto, no en el schema) |

Toku recomienda `DELETE` solo para deudas cargadas por error. Para dejar de cobrar conservando la historia, usar **void**.

## Void vs Delete vs `is_void` [Confirmado + Recomendación]

| Acción | Resultado | Cuándo |
|---|---|---|
| `POST /void` con `delete_invoice: false` | Anulada, se conserva (`VOID`) | **Por defecto**: el socio deja de deber esa cuota |
| `POST /void` sin body o con `true` | Anulada y borrada | Evitar |
| `DELETE` | Borrada (`DELETED`) | Solo datos de prueba o cargas erróneas |
| `POST`/`PUT` con `is_void: true` | Marca como anulada | **[No confirmado]** si equivale exactamente al endpoint `/void`. Preferir el endpoint |

## Webhooks relacionados
`invoice.created`, `invoice.updated`, `invoice.paid` (payload: `{ id, event_type, invoice, transactions[] }`), `invoice.voided`, `invoice.refund`, `invoice_restructuring.completed`. Ver [webhooks.md](webhooks.md).
