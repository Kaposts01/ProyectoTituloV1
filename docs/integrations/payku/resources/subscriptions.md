# Suscripciones (`/api/sususcription`, `/api/sususcriptionv3`)

Documentación oficial: https://docs.payku.com/cl/api/subscriptions/

> Ojo con la ortografía de Payku: la ruta es **`sususcription`** (con "su" repetido), el campo del body es **`suscription`** y en el cliente aparece **`subcriptions`**. Escríbelos exactamente así.

**Autenticación (todos):** `Authorization: Bearer` + `Sign` ✅

---

## Respuestas rápidas

| Pregunta | Respuesta | Estado |
|---|---|---|
| ¿Cómo se crea? | `POST /api/sususcription` con `plan` + `client` → devuelve `url` donde el cliente inscribe su tarjeta. | ✅ |
| ¿Cómo se consulta una? | `GET /api/sususcription/{id}` | ✅ |
| ¿Cómo se listan? | `GET /api/sususcriptionv3` (recomendado) o `GET /api/sususcription` (V1), con fechas y paginación. | ✅ |
| ¿Cómo se relaciona con el cliente? | `client.id` dentro de la suscripción; `client` al crear. | ✅ |
| ¿Cómo se sabe su estado? | `status` (V1/detalle) o `estatus` (V3); historial en `logs.status[]`; aviso por callback. | ✅ |
| ¿Cómo se cancela? | `DELETE /api/sususcription/{id}`. | ✅ (el estado resultante ⚠️) |
| ¿Cómo se suspende? | **No hay endpoint.** Payku la suspende (p. ej. tras agotar reintentos de cobro). | ✅ / ⚠️ |
| ¿Cómo se reactiva? | No hay endpoint. Inscribiendo una tarjeta nueva (`POST /api/suinscriptionscards`), Payku "podrá" cobrar lo atrasado y "activar automáticamente" la suscripción. | ✅ (comportamiento) |
| ¿Cómo se asocia a cobros? | Los cobros vienen dentro: `transactions[]` (V1/detalle) o `paid[]` (V3). | ✅ |
| ¿Fecha de inicio? | `start`. | ✅ |
| ¿Fecha de término? | `end` ("fecha de término de la suscripción"). | ✅ (significado exacto ⚠️) |
| ¿Periodicidad? | **No se expone.** Solo se sabe que el plan de monto fijo cobra "a partir del mes siguiente". 💡 mensual. | ⚠️ |
| ¿Monto? | No hay `amount` en la suscripción (V1, V3 ni detalle). Aparece en `GET /api/suclient/{id}` → `subcriptions.amount`, y por cobro (`amount`, `amount_paid`). | ⚠️ |
| ¿Medio de pago? | Tarjeta inscrita: `cards` / `active_cards` (`card_type`, `last_4_digits`). No hay otro medio documentado para suscripciones. | ✅ |

---

## Crear suscripción

### Endpoint

```http
POST /api/sususcription
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Crear suscripción"

### Propósito
- **Para qué sirve:** suscribir un cliente existente a un plan (monto fijo, consumo o monto variable). ✅
- **Cuándo usarlo:** después de crear o encontrar el cliente ([customers.md](customers.md)).
- **Qué crea:** una suscripción en estado `register`, más una **URL** de "pago y activación" que el cliente debe abrir para inscribir su tarjeta. ✅
- **Implicancias recurrentes (✅ textual de Payku):**
  - "Al realizar esta solicitud por primera vez se realizará un cobro de **$50** que permite comprobar que la tarjeta se encuentra activa y es válida."
  - Plan de monto fijo: "el cobro del servicio será automático **a partir del mes siguiente** de la fecha de suscripción".
  - Plan de consumo: "será necesario utilizar el endpoint `api/sutransaction` para generar la transacción".

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `plan` | string | ✓ | ID del plan. Máx. 70. ✅ |
| `client` | string | ✓ | ID del cliente. Máx. 20. ✅ |
| `amount` | string | Ver nota | Solo para planes de **monto variable**; moneda CLP. Máx. 14 dígitos. ✅ |
| `coupon` | string | Ver nota | Código de cupón. Máx. 50. ✅ |

⚠️ La especificación marca `amount` y `coupon` como "oneOf" (opción 1 / opción 2) y ambos como requeridos, pero el ejemplo oficial envía **solo `plan` y `client`**. 💡 Interpretación: `amount` solo si el plan es de monto variable; `coupon` opcional. Validar (Q-07).

```json
{
  "plan": "pl9697fb170834ad42dd00",
  "client": "cl9b1e1dd988694f30fa30"
}
```

### Response (200)

```json
{
  "status": "register",
  "id": "sucaab7865dceaff49d8b3",
  "url": "http://BASE_URL/gateway/registrosuscripcion?tipoplan=2&plan=true&token=219&validacion=e6c50ba0e0"
}
```

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `id` | string | ID único de la suscripción. | **Guardar de inmediato** junto a nuestro ID (no hay campo de ID externo). |
| `status` | string | `register`. | Estado inicial `PENDIENTE_ACTIVACION`. |
| `url` | string | URL de pago y activación. | Redirigir al socio o enviársela. ⚠️ No sabemos cuánto dura vigente. |

### Errores
Estándar → [errors.md](errors.md).

### Consideraciones
- ⚠️ **Idempotencia:** no documentada. Un reintento puede crear **otra** suscripción. Antes de reintentar, consulta el cliente (`GET /api/suclient/{id}`) o lista V3 del día.
- ⚠️ No está documentado si el cobro de $50 se reembolsa o se descuenta.
- ⚠️ No está documentado qué pasa si el cliente nunca completa la `url` (¿queda `register` para siempre?).
- 💡 Usa el estado `register` + antigüedad para un recordatorio automático al socio.

### Ejemplo práctico
Ver [workflows/create-subscription.md](workflows/create-subscription.md).

---

## Obtener suscripción (detalle)

### Endpoint

```http
GET /api/sususcription/{identificadorSuscripcion}
```

### Propósito
Fuente más completa para **una** suscripción: estado, fechas, cliente, plan, tarjetas, cobros e historial. 💡 Úsalo para confirmar un webhook y para reprocesar casos puntuales.

### Path parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `identificadorSuscripcion` | string | ✓ | ID de la suscripción. "Máximo 20 caracteres" ✅ (los ejemplos tienen 22 ⚠️). |

### Response (200)

```json
{
  "id": "sucaab7865dceaff49d8b7",
  "status": "active",
  "start": "2019-07-22 18:34:49",
  "end": "2023-06-12 00:00:00",
  "client": {
    "id": "cld0835b9063a5903f4ae7",
    "name": "name",
    "email": "joedoe@example.com",
    "rut": "11.111.111-1",
    "phone": "56972756487",
    "parámetros": [],
    "additional_parameters": ""
  },
  "plan": { "id": "pl9697fb170834ad42dd00", "name": "test plan", "currency": "CLP" },
  "cards": { "last_4_digits": "XXXXXXXXXXXX6622", "card_type": "Visa" },
  "active_cards": [
    { "last_4_digits": "XXXXXXXXXXXX6622", "identifier": "surec804a8ed60c747cb8839", "card_type": "Visa", "register": "2023-07-26 08:00:19" }
  ],
  "transactions": [
    { "created_at": "2023-09-30 19:58:35", "amount": 10000, "transaction": 204444, "authorization_code": "1234",
      "order": "001", "description": "descripcion", "status": "success" }
  ],
  "logs": {
    "status": [ { "change_date": "2021-02-17 16:11:53", "initial_status": "register", "final_status": "active" } ]
  }
}
```

### Campos importantes

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `id` | string | ID de la suscripción. | Clave. |
| `status` | string | `register` / `active` / `finish` / `delete` / `cancel` / `suspended`. | Guardar literal + normalizado. |
| `start` | string | Inicio. | Fecha de alta. |
| `end` | string | Término. | ⚠️ En el ejemplo, una suscripción `active` tiene `end` en el pasado: no está claro si es fecha de fin real o de vencimiento de la tarjeta. Guardar sin interpretar. |
| `client.id` | string | Cliente. | FK a `payku_cliente_map`. |
| `client.parámetros` | array | Campo con **tilde** en el nombre. ⚠️ Sin descripción. | Guardar en staging; ojo con el encoding del parser. |
| `plan.id` / `plan.currency` | string | Plan y moneda. | FK a catálogo de planes. |
| `cards` | object | Tarjeta (sin `identifier`). 💡 La que se está usando. | Mostrar en soporte. |
| `active_cards[]` | array | Tarjetas vigentes con `identifier`. | Para consumo y eliminación. |
| `transactions[]` | array | Cobros (estados **Lista B**). | → [subscription-charges.md](subscription-charges.md). |
| `logs.status[]` | array | Historial de cambios de estado. | → `suscripcion_estado_hist`. |

### Estados posibles
Ver [statuses.md](statuses.md#1-suscripción).

---

## Obtener suscripciones (V1)

### Endpoint

```http
GET /api/sususcription?page=1&per_page=100
```

### Propósito
Listado de suscripciones de la cuenta. Trae un campo que V3 no tiene: `last_status_current_payment`. ✅

### Query parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `page` | int | | Página. ✅ |
| `per_page` | int | | Máximo **no indicado** en la doc ("un máximo de  registros"). ⚠️ |
| (filtro de fecha) | date | | Existe; si no se envía, usa la **fecha actual**. ✅ Nombre del parámetro **no documentado** ⚠️ (💡 probar `date_init` / `date_end`). |
| `<estado>=true` | bool | | Filtrar por estado; sin filtro trae todos. ✅ |

### Response (200)

```json
[
  {
    "subscriptions": [
      {
        "id": "sucaab7865dceaff49d8b7",
        "status": "active",
        "last_status_current_payment": "pending",
        "start": "2019-07-22 18:34:49",
        "end": "2023-06-12 00:00:00",
        "client": { "id": "su7e5e1c0b1bd2e37ec557", "name": "name", "email": "johndoe@example.com", "rut": "11.111.111-1", "phone": "56928265454", "parámetros": [], "additional_parameters": "" },
        "plan": { "id": "pl9697fb170834ad42dd00", "name": "test plan", "currency": "CLP" },
        "cards": { "last_4_digits": "XXXXXXXXXXXX6622", "card_type": "Visa" },
        "transactions": [ { "created_at": "2023-09-30 19:58:35", "amount": 10000, "transaction": 204444, "authorization_code": "1234", "order": "001", "description": "descripcion", "status": "success" } ],
        "logs": { "status": [ { "change_date": null, "initial_status": null, "final_status": null } ] }
      }
    ]
  }
]
```

### Consideraciones
- La respuesta es un **arreglo** que contiene un objeto con `subscriptions`. ✅
- `logs.status[]` puede venir con valores `null`. ✅
- `last_status_current_payment`: valores posibles no documentados. ⚠️

---

## Obtener suscripciones V3 (recomendado para sincronizar)

### Endpoint

```http
GET /api/sususcriptionv3?date_init=2021-09-01&date_end=2021-09-15&active=true&page=1&per_page=1000
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Obtener suscripciones V3"

### Propósito
- **Para qué sirve:** listado masivo con el detalle de **pagos por ciclo** (`paid[]`): cuándo correspondía cobrar, cuándo se pagó, cuántos intentos y número de pago. ✅
- **Cuándo usarlo:** carga inicial y barridos periódicos ([sync-payku.md](workflows/sync-payku.md)).
- 💡 Es el endpoint que mejor responde "¿pagó este socio este mes?".

### Query parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `date_init` | `YYYY-MM-DD` | | Inicio. Sin él: hoy. ✅ |
| `date_end` | `YYYY-MM-DD` | | Fin. Sin él: hoy. ✅ |
| `<estado>=true` | bool | | `active=true`, etc. Sin filtro: todos. ✅ |
| `page` | int | | Página. ✅ |
| `per_page` | int | | Máximo **4000**. ✅ |

⚠️ No documentado: sobre qué fecha se aplica el rango (💡 probablemente creación o `start`). Si fuera creación, **una suscripción antigua con un cobro nuevo no aparecería** en una ventana reciente. Ver la estrategia en [sync-payku.md](workflows/sync-payku.md).

### Response (200)

```json
[
  {
    "subscriptions": [
      {
        "id": "sucaab7865dceaff49d8b7",
        "estatus": "active",
        "start": "2019-07-22 18:34:49",
        "end": "2023-06-12 00:00:00",
        "client": { "id": "su7e5e1c0b1bd2e37ec557", "name": "name", "email": "johndoe@example.com", "rut": "11.111.111-1", "phone": "56928265454", "parámetros": [], "additional_parameters": "" },
        "plan": { "id": "pl9697fb170834ad42dd00", "name": "test plan", "currency": "CLP" },
        "active_cards": { "last_4_digits": "XXXXXXXXXXXX6622", "card_type": "Visa" },
        "logs": { "status": [ { "change_date": null, "initial_status": null, "final_status": null } ] },
        "paid": [
          {
            "payment_cycle_day": "2021-07-09",
            "payment_day": "2021-07-09",
            "status": "success",
            "amount_paid": 2500,
            "try_number": 1,
            "paid_number": 1,
            "transactions": []
          }
        ]
      }
    ]
  }
]
```

### Campos importantes (diferencias con V1)

| Campo | V1 | V3 | Uso interno 💡 |
|---|---|---|---|
| Estado | `status` | **`estatus`** | Mapear ambos al mismo campo en el ETL. |
| `last_status_current_payment` | ✅ | ❌ | Si lo necesitas, combina con V1. |
| Tarjeta | `cards` (objeto) | `active_cards` (**objeto**, sin `identifier`) | — |
| Cobros | `transactions[]` | `paid[]` (por ciclo) | V3 es mejor para cobros recurrentes. |
| `paid[].payment_cycle_day` | — | Día del ciclo que correspondía cobrar. ✅ | Periodo de la cuota. |
| `paid[].payment_day` | — | Día en que se pagó. ✅ | Fecha de pago real. |
| `paid[].try_number` | — | Número de intento. ✅ | Detectar reintentos. |
| `paid[].paid_number` | — | Número de pago. ✅ 💡 correlativo de cuotas pagadas. | Contar meses pagados. |
| `paid[].amount_paid` | — | Monto pagado. ✅ | — |
| `paid[].transactions[]` | — | ⚠️ Estructura no documentada (vacío en el ejemplo). | Guardar en staging. |

---

## Eliminar suscripción (cancelar)

### Endpoint

```http
DELETE /api/sususcription/{identificadorSuscripcion}
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Eliminar suscripción"

### Propósito
"Eliminación de una suscripción asociada a un ID de suscripción." ✅ Es la **única forma documentada de dar de baja** una suscripción por API.

### Response (200)

```json
{ "id": "sucaab7865dceaff49d8b3", "status": "success" }
```

### Consideraciones ⚠️
- No está documentado si la suscripción queda en `delete` o en `cancel` (ambos existen). 💡 Después del `DELETE`, consulta `GET /api/sususcription/{id}` y guarda el estado real.
- No está documentado si un cobro **en curso** (`pending` / `retry`) se detiene.
- **Irreversible** 💡: no hay endpoint para reactivar una suscripción eliminada. Para "pausar", no existe alternativa por API.
- Ver flujo completo: [workflows/cancel-subscription.md](workflows/cancel-subscription.md).
