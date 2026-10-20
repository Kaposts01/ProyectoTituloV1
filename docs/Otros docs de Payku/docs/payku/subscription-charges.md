# Cobros de suscripción

Documentación oficial: https://docs.payku.com/cl/api/subscriptions/ ("Crear transacción", "Obtener suscripción", "Obtener suscripciones V3", "url Callback notificación cobro")

---

## Términos clave

- **Cobro:** cada cargo a la tarjeta de un suscriptor. En la documentación Payku lo llama "transacción" (`transactions[]`, `sutransaction`).
- **Ciclo:** el periodo que se cobra (p. ej. "julio"). En V3: `payment_cycle_day`.
- **Intento:** cada vez que Payku trata de cobrar un ciclo. En V3: `try_number`.

🎨 **Analogía:** la suscripción es un **contrato de arriendo**; cada mes hay un **recibo** (ciclo) y Payku puede **tocar la puerta** varias veces (intentos) hasta que pagan o se rinde (`maximum attempt limit` → suscripción `suspended`).

---

## 1. ¿Payku funciona como "Suscripción → Cobro → Transacción"?

| Modelo esperado | Realidad en Payku | Estado |
|---|---|---|
| Suscripción → Cobro | Sí: los cobros viven **dentro** de la suscripción (`transactions[]`, `paid[]`). | ✅ |
| Cobro → Transacción separada | Cada cobro tiene un número `transaction` / `transaction_id` y `verification_key`. **No** está documentado que exista como recurso consultable en `/api/transaction`. | ⚠️ |
| Ciclo con reintentos | Solo visible en V3 (`paid[]` con `try_number`). | ✅ |
| "Invoice" o documento de deuda (como Toku) | **No existe.** | ✅ (no aparece) |

```text
SUSCRIPCIÓN (su…)
  ├── V1 / detalle → transactions[]  = un registro por cobro (con número de transacción)
  └── V3           → paid[]          = un registro por ciclo/intento
                        └── transactions[]  (estructura no documentada ⚠️)
```

---

## 2. Cómo se generan los cobros

| Tipo de plan | Quién cobra | Cómo |
|---|---|---|
| Monto fijo | **Payku, automático**, desde el mes siguiente a la suscripción. ✅ | Nos enteramos por el callback `url_notify_payment` o al consultar. |
| Monto variable | 💡 Payku, automático, con el `amount` indicado al crear. ⚠️ | Ídem. |
| Consumo | **Nosotros**, con `POST /api/sutransaction`. ✅ | Respuesta inmediata + callback. |

---

## 3. Crear cobro (planes de consumo)

### Endpoint

```http
POST /api/sutransaction
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Crear transacción" y https://docs.payku.com/cl/api/consumption-subscriptions/ → "Crear transacción"

### Propósito
"Generar una transacción única a uno de sus clientes que se encuentre suscrito a un plan de consumo." ✅ Cobra a la tarjeta inscrita **sin** que el cliente intervenga.

### Autenticación
`Bearer` + `Sign` ✅

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `suscription` | string | ✓ | ID de la suscripción. Máx. 60. ✅ |
| `amount` | string | | Monto. Máx. 14. ✅ (es **string**) |
| `order` | string | | Orden del comercio. Máx. 40. ✅ |
| `description` | string | | Descripción. Máx. 1000. ✅ |
| `card` | string | | `identifier` de la tarjeta a cobrar (si tiene varias). Máx. 28. Solo documentado en *Suscripción de consumo*. ✅ |
| `marketplace` | string | | ID de marketplace (`ma…`). Solo en *Suscripción de consumo*. ✅ |

```json
{
  "suscription": "sucaab7865dceaff49d8b3",
  "amount": "10000",
  "order": "TECHO-2026-10-000123",
  "description": "Aporte octubre 2026"
}
```

### Response (200)

```json
{
  "status": "success",
  "order": "001",
  "amount": "10000",
  "transaction_id": "204444",
  "verification_key": "025dcad37e071daa8bfc2df35189009db65692a4ff766856108be1675e870839"
}
```

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `status` | string | `pending` / `success` / `rejected` / `refunded partial` / `refunded`. ✅ | ⚠️ Un `rejected` puede venir con HTTP 200: es un rechazo de pago, no un error de API. |
| `transaction_id` | string | Número de transacción. ✅ | **Clave del cobro.** |
| `verification_key` | string | Hash. ✅ | Auditoría. |
| `order` | string | Nuestra orden. ✅ | Idempotencia de nuestro lado. |

### Consideraciones (⚠️ mueve dinero)
- **Nunca reintentes a ciegas.** Si hay timeout, busca el `order` en `GET /api/sususcription/{id}` → `transactions[].order` antes de volver a cobrar.
- Usa un `order` **único** generado por nosotros (máx. 40 caracteres).
- ⚠️ No está documentado si Payku rechaza un `order` repetido.
- ⚠️ No está documentado qué pasa si se llama sobre una suscripción de **monto fijo**.

---

## 4. Leer cobros

No hay un endpoint "listar cobros". Se obtienen desde la suscripción (o el cliente):

| Fuente | Ruta | Campos del cobro | Estados |
|---|---|---|---|
| Detalle de suscripción | `GET /api/sususcription/{id}` → `transactions[]` | `created_at`, `amount` (int), `transaction` (int), `authorization_code`, `order`, `description`, `status` | Lista B |
| Listado V1 | `GET /api/sususcription` → `transactions[]` | ídem | Lista B 💡 |
| Listado V3 | `GET /api/sususcriptionv3` → `paid[]` | `payment_cycle_day`, `payment_day`, `status`, `amount_paid`, `try_number`, `paid_number`, `transactions[]` | ⚠️ no documentado |
| Cliente | `GET /api/suclient/{id}` → `subcriptions.transactions[]` | + `date_payment` | Lista A |
| Callback de cobro | `url_notify_payment` | `transaction_id`, `verification_key`, `order`, `status`, `subscriptions{id, client}` | Lista B |

(Listas A y B: [statuses.md](statuses.md#2-cobro-de-suscripción))

---

## 5. Respuestas rápidas

| Pregunta | Cómo | Estado |
|---|---|---|
| ¿Cómo listarlos? | Recorrer V3 (`paid[]`) o el detalle de cada suscripción (`transactions[]`). | ✅ |
| ¿Cómo buscar uno específico? | Por `transaction` / `order` dentro de la suscripción. **No hay** `GET` por ID de cobro. | ✅ / ⚠️ |
| ¿Cómo saber si fue pagado? | `status == "success"` (V1/detalle/callback) o `paid[].status == "success"` (V3). | ✅ |
| ¿Cómo asociarlo a la suscripción? | Viene dentro de ella; en el callback, `subscriptions.id`. | ✅ |
| ¿Cómo asociarlo al cliente? | Vía la suscripción (`client.id`) o el callback (`subscriptions.client`). | ✅ |
| ¿Monto? | `amount` (V1/detalle) / `amount_paid` (V3). | ✅ |
| ¿Fecha? | `created_at`; `date_payment` (solo en el cliente); `payment_cycle_day` y `payment_day` (V3). | ✅ |
| ¿Método de pago? | Tarjeta de la suscripción (`cards.card_type`). ⚠️ No viene por cobro. | ⚠️ |
| ¿Referencia? | `order`. | ✅ |
| ¿Código de operación? | `authorization_code` (autorización del emisor) y `transaction` (número Payku). | ✅ |
| ¿Errores / motivo de rechazo? | Solo el `status`. ⚠️ No hay mensaje de rechazo por cobro (a diferencia de `gateway_response.message` en transacciones). | ⚠️ |
| ¿Reintentos? | V3: `try_number` por ciclo. Estados `retry` y `maximum attempt limit` (Lista A). Número máximo y calendario **no documentados**. | ✅ / ⚠️ |

---

## 6. Qué guardar (por cobro) 💡

| Campo | Fuente | Para qué |
|---|---|---|
| `payku_subscription_id` | contenedor / callback | FK |
| `payku_client_id` | suscripción / callback | FK |
| `payku_transaction_id` | `transaction` / `transaction_id` | Clave natural del cobro |
| `order` | todas | Nuestra referencia, cruce con conciliación |
| `verification_key` | callback / `sutransaction` | Auditoría |
| `authorization_code` | V1 / detalle | Soporte, contraloría |
| `cycle_date` | V3 `payment_cycle_day` | Periodo |
| `paid_date` | V3 `payment_day` o `created_at` | Fecha contable |
| `attempt` | V3 `try_number` | Reintentos |
| `paid_number` | V3 | Cuota correlativa |
| `amount` | `amount` / `amount_paid` | Monto (convertir a entero CLP) |
| `status_origen` | literal | Trazabilidad |
| `status_normalizado` | mapping | Reportes |
| `source` | `v1` / `v3` / `detail` / `webhook` | Saber de dónde vino cada dato |

⚠️ **Clave única del cobro:** 💡 `payku_transaction_id` cuando existe. Para filas de V3 sin `transactions[]` usa (`payku_subscription_id`, `payment_cycle_day`, `try_number`). Validar en sandbox cuál es estable (Q-08).
