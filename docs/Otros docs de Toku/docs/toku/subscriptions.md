# Subscriptions

Objeto: <https://docs.trytoku.com/reference/subscription-object>

## Qué es

Una **Subscription** es un *plan de pago* de un Customer, identificado por un `product_id` que define la organización (el glosario de Toku la equipara a "Producto"). [Confirmado]

- **Toda Invoice pertenece a una Subscription.** [Confirmado]
- Puede ser **recurrente** (`is_recurring: true`): Toku genera las Invoices solo, según `frequency` / `interval` / `due_day`.
- O **no recurrente** (`is_recurring: false`): la organización carga las Invoices.

En TECHO: un aporte mensual de un socio = una Subscription recurrente.

**Autenticación y errores comunes:** ver [authentication.md](authentication.md) y [errors.md](errors.md). Límite: **20 req/s**.

## Objeto Subscription [Confirmado]

| Campo | Tipo | Descripción | Uso interno |
|---|---|---|---|
| `id` | string (`sub_…`) | ID público. Requerido. | PK |
| `product_id` | string (≥1, sin espacios al inicio ni al final) | ID del producto en la organización. **No se repite dentro de una Account.** Requerido. | Llave de cruce con nuestro "plan/compromiso" |
| `customer` | string (`cus_…`) | Dueño. Requerido. | FK |
| `id_account` | string (`acc_…`) | Cuenta de cobro. Requerido. | |
| `amount` | number ≥0 | Monto de las deudas que genera | |
| `currency_code` | enum | `CLP`, `CLF`, `MXN`, `BRL`, `USD` | |
| `due_day` | integer 1–31 | Día de vencimiento (ver semántica abajo) | |
| `is_recurring` | boolean (default `false`) | Si genera Invoices automáticamente | |
| `recurring` | object | **Solo cuando `is_recurring` es `true`** | |
| `metadata` | object string→string | Campos extra | |
| `pac_mandate_id` | string | Mandato PAC asociado | |
| `receipt_product_code` | string ≤8 | Código de producto para el documento tributario | |

### Objeto `recurring` [Confirmado]

| Campo | Tipo | Descripción |
|---|---|---|
| `amount` | number | Monto de cada deuda recurrente |
| `anchor` | date | Fecha ancla desde la que se calculan los períodos |
| `creation_lead_days` | integer ≥0 | Cuántos días antes del vencimiento se crea cada Invoice |
| `due_day` | integer | Igual que el `due_day` de la raíz |
| `end_date` | date \| null | Hasta cuándo genera deudas; `null` = sin fin |
| `frequency` | enum | `daily`, `weekly`, `monthly`, `yearly` |
| `interval` | integer ≥1 | Cada cuántas unidades de `frequency` se genera una deuda |
| `max_active_invoices` | integer ≥1 | Máximo de deudas impagas simultáneas |
| `status` | enum | `ACTIVE`, `PAUSED`, `FINISHED` |
| `start_date` | date | **Solo aparece en el payload del webhook `subscription.updated`**, no en el schema REST |

### Semántica de `frequency` + `interval` + `due_day` [Confirmado]

| `frequency` | `due_day` significa | Ejemplo |
|---|---|---|
| `daily` | Se ignora | — |
| `weekly` | Día de la semana, de 1 (lunes) a 7 (domingo) | `due_day: 5` = vence los viernes |
| `monthly` | Día del mes. Si el mes es más corto, se ajusta al último día y el ciclo siguiente vuelve al original | `due_day: 31` → 28 de febrero, luego 31 de marzo |
| `yearly` | Igual que `monthly` | |

`interval: 2` con `monthly` = una deuda cada dos meses.

⚠️ El schema de `due_day` permite de 1 a 31 para todas las frecuencias, pero la descripción limita `weekly` a 1–7. Validarlo de nuestro lado.

### Estado de la suscripción [Confirmado / Inferencia]

| Situación | Cómo se ve |
|---|---|
| Recurrente activa | `is_recurring: true` y `recurring.status: "ACTIVE"` |
| Pausada (manualmente o porque llegó a `max_active_invoices` impagas) | `recurring.status: "PAUSED"` |
| Terminada (pasó `end_date`) | `recurring.status: "FINISHED"`. **[Inferencia]**: la doc no define `FINISHED` |
| No recurrente | `is_recurring: false`, sin `recurring`. **No tiene estado propio** |
| Eliminada | Desaparece (`DELETE` → `204`), con el webhook `subscription.deleted` |

> **"¿Está activa?"** depende de lo que signifique "activa" para el negocio. Para Toku es `recurring.status == "ACTIVE"`. Para TECHO probablemente sea "activa y con medio de pago cobrable y al día". Eso se calcula en el modelo normalizado cruzando Payment Methods e Invoices (ver [workflows/sync-toku.md](workflows/sync-toku.md)).

---

## Listar Subscriptions

```http
GET /subscriptions
```
Doc: <https://docs.trytoku.com/reference/get_subscriptions>

| Query | Tipo | Requerido | Descripción |
|---|---|---|---|
| `page_size` | integer | No | 50 por defecto, máx. 100 |
| `next_cursor` | string | No | Cursor |
| `start_date` / `end_date` | date-time | No | **Fecha de creación** (inclusive) |
| `is_recurring` | boolean | No | Solo recurrentes / no recurrentes |

**Paginación por cursor** (`items`, `next_cursor`). ⚠️ No usa `page`: ver [postman-audit.md](postman-audit.md).

No hay filtro por `customer` ni por `recurring.status`.

---

## Crear Subscription (upsert)

```http
POST /subscriptions
```
Doc: <https://docs.trytoku.com/reference/create_or_update_subscription>

### Propósito
Crea o actualiza. **Idempotente por `(Account, product_id)`**: si ya existe ese `product_id` en la cuenta, la actualiza y responde `200`; si no, la crea y responde `201`. [Confirmado]

### Request body
| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `product_id` | string | **Sí** | |
| `customer` | string `cus_…` | **Sí** | |
| `amount` | number ≥0 | No | Monto por Invoice |
| `currency_code` | enum | No | CLP sin decimales |
| `is_recurring` | **boolean** | No (default `false`) | ⚠️ Booleano real, no `"True"` |
| `frequency` | enum | No | `daily`/`weekly`/`monthly`/`yearly` |
| `interval` | **integer** 1–52 | No | |
| `due_day` | **integer** 1–31 | No | |
| `end_date` | date | No | `null` = sin fin |
| `creation_lead_days` | integer ≥0 | No | |
| `max_active_invoices` | integer ≥1 | No | |
| `metadata` | object | No | Claves declaradas en la webapp |
| `pac_mandate_id` | string | No | |
| `receipt_product_code` | string ≤8 | No | |

> ⚠️ **En el request, la configuración de recurrencia va en la raíz** (`frequency`, `interval`, …), **no dentro de un objeto `recurring`**. El objeto `recurring` solo aparece en la **respuesta**. [Confirmado]

Ejemplo (aporte mensual el día 5):
```json
{
  "product_id": "TEST-SOCIO-0001-MENSUAL",
  "customer": "cus_…",
  "amount": 10000,
  "currency_code": "CLP",
  "is_recurring": true,
  "frequency": "monthly",
  "interval": 1,
  "due_day": 5,
  "creation_lead_days": 5,
  "max_active_invoices": 3
}
```

### Consideraciones
- **[Recomendación]** Construir el `product_id` de forma determinística desde nuestra BD (por ejemplo `SOCIO-{id_socio}-{id_compromiso}`), para que el upsert sea naturalmente idempotente y trazable.
- `TK30501`: no se puede "transferir" una Subscription a otro Customer reenviando el mismo `product_id` con otro `customer`.
- **[No confirmado]** Qué fecha toma el `anchor` si no se envía (probablemente la fecha de creación). Verificarlo leyendo `recurring.anchor` en la respuesta.

---

## Listar Subscriptions de un Customer

```http
GET /subscriptions/customer/{customer_id}
```
Doc: <https://docs.trytoku.com/reference/subscriptions_by_customer>

Array **sin paginar** de Subscriptions del Customer. El path param se llama `customer_id` (`cus_…`).

---

## Buscar Subscription por identificadores externos

```http
GET /subscriptions/lookup?product_id={product_id}
```
Doc: <https://docs.trytoku.com/reference/lookup_subscription>

Único parámetro documentado: `product_id`. Devuelve una Subscription o `404`.

---

## Obtener Subscription

```http
GET /subscriptions/{encrypted_subscription_id}
```
Doc: <https://docs.trytoku.com/reference/get_subscription>

---

## Editar Subscription

```http
PUT /subscriptions/{encrypted_subscription_id}
```
Doc: <https://docs.trytoku.com/reference/edit_subscription>

- Actualización parcial, con los mismos campos que en la creación (todos opcionales, también en la raíz).
- **Los cambios de recurrencia aplican a las Invoices que se generen desde ese momento.** Las ya creadas no cambian. [Confirmado]
- `creation_lead_days` tiene un tope: la creación nunca puede quedar antes del vencimiento del ciclo anterior.
- Respuesta `200` con la Subscription (`UpdateSubscriptionResponse`).

---

## Cambiar estado (pausar / reanudar)

```http
POST /subscriptions/{encrypted_subscription_id}/status
```
Doc: <https://docs.trytoku.com/reference/change_subscription_status>

```json
{ "status": "PAUSED" }
```

| Valor | Efecto [Confirmado] |
|---|---|
| `PAUSED` | La generación automática de Invoices se salta esta Subscription. **Las Invoices ya generadas no se tocan.** |
| `ACTIVE` | Reanuda. Cobra desde el primer ciclo cuyo vencimiento sea hoy o posterior. **Los ciclos que pasaron durante la pausa no se cobran retroactivamente.** |

Solo se permite `ACTIVE ↔ PAUSED`. Cualquier otra transición → `409` (descrito en el texto, no en el schema). No se puede pasar a `FINISHED` por esta vía.

---

## Eliminar Subscription

```http
DELETE /subscriptions/{encrypted_subscription_id}
```
Doc: <https://docs.trytoku.com/reference/delete_subscription>

`204`. **Detiene la generación de nuevas Invoices recurrentes.** [Confirmado] **[No confirmado]** Qué pasa con las Invoices impagas ya generadas: probablemente siguen existiendo y cobrándose. Ver [workflows/cancel-subscription.md](workflows/cancel-subscription.md).

---

## Asociar Payment Method

Ver [payment-methods.md](payment-methods.md#asociar-payment-method-a-subscription): `POST /subscriptions/associate/payment-method`.

## Webhooks relacionados
`subscription.created`, `subscription.updated`, `subscription.deleted`. Payload: `{ id, event_type, subscription }`, sin `updated_fields`.
