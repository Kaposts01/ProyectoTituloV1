# Clientes de suscripción (`/api/suclient`)

Documentación oficial: https://docs.payku.com/cl/api/subscriptions/ (secciones Crear / Obtener / Actualizar / Eliminar cliente y Obtener clientes)

> Este recurso es el **cliente de suscripción**. Marketplace tiene otro recurso de "cliente" (`/api/maclient`) que **no** es el mismo: ver [marketplace.md](marketplace.md).

**Autenticación (todos los endpoints de esta página):** `Authorization: Bearer TOKEN_PUBLICO` + `Sign` ✅ → [authentication.md](authentication.md)

---

## Crear cliente

Registra a la persona que luego se suscribirá a un plan.

### Endpoint

```http
POST /api/suclient
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Crear cliente" (también repetido en Suscripción de consumo).

### Propósito
- **Para qué sirve:** crear el registro del suscriptor en Payku. Es **prerrequisito** para crear una suscripción (`client` es obligatorio en `POST /api/sususcription`). ✅
- **Cuándo usarlo:** cuando un socio nuevo elige pagar con Payku y no existe ya como cliente (verifica antes con `GET /api/suclient/{email}`).
- **Qué recurso modifica:** crea un cliente (`cl…`).
- **Relación:** padre de las suscripciones → [subscriptions.md](subscriptions.md).
- **Implicancia recurrente:** el `id` devuelto es la llave que conecta nuestro socio con todas sus suscripciones y cobros en Payku. Hay que guardarlo.

### Path parameters
No aplica.

### Query parameters
No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `email` | string | ✓ | Email del cliente. Máx. 50. ✅ |
| `name` | string | ✓ | Nombre. Máx. 80. ✅ |
| `phone` | string | ✓ | Teléfono. "20 caracteres requeridos" ✅ (💡 probablemente es un máximo de 20). |
| `rut` | string | | RUT, con o sin guion. "12 caracteres requeridos". ✅ En Suscripción de consumo aparece como `integer`. ⚠️ |
| `address` | string | | Dirección. Máx. 200. |
| `country` | string | | País. Máx. 40. |
| `region` | string | | Región. Máx. 120. |
| `city` | string | | Ciudad. Máx. 40. |
| `postal_code` | string | | Código postal. Máx. 10. |
| `additional_parameters` | object | | Parámetros adicionales libres. Máx. 4000. **No entra en la firma** (es objeto). ✅ |

```json
{
  "email": "johndoe@example.com",
  "name": "John Doe",
  "rut": "111111111",
  "phone": "923122312",
  "address": "Moneda 101",
  "country": "Chile",
  "region": "Metropolitana",
  "city": "Santiago",
  "postal_code": "850000",
  "additional_parameters": {
    "parameter_1": "example",
    "parameter_2": "example 2"
  }
}
```

### Response (200)

```json
{
  "status": "active",
  "id": "cl0be4c8e623c167bc8b777",
  "rut": "11111111",
  "name": "John Doe",
  "phone": "923122312",
  "email": "johndoe@example.com",
  "address": "Moneda 101",
  "country": "Chile",
  "region": "Metropolitana",
  "city": "Santiago",
  "postal_code": "850000",
  "created_at": "2023-09-29",
  "update_at": null,
  "subcriptions": null,
  "additional_parameters": { "parameter_1": "example", "parameter_2": "example" }
}
```

### Campos importantes

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `id` | string | ID del cliente en Payku (la doc lo llama, por error, "identificador de la transacción"). | **Guardar** como `payku_client_id`. |
| `status` | string | Estado del cliente (`active`). | Staging. |
| `created_at` | string | Fecha de registro (`YYYY-MM-DD`). | Auditoría. |
| `subcriptions` | object/null | Suscripciones del cliente (`null` al crear). Nombre con error de tipeo. | — |
| `additional_parameters` | object | Lo que enviamos. | Verificar que guardó nuestro ID externo. |

### Estados posibles
`active` (ejemplo). ⚠️ No hay lista documentada → [statuses.md](statuses.md#3-cliente-de-suscripción).

### Errores
Formato estándar (400 validación, 401 token o firma) → [errors.md](errors.md). Recuerda que pueden llegar con HTTP 200 y `status: failed`.

### Consideraciones
- ⚠️ No está documentado si Payku rechaza un email duplicado o crea un segundo cliente. **Busca antes de crear.**
- ⚠️ Idempotencia no documentada: ante un timeout, consulta por email antes de reintentar.
- 💡 Guarda nuestro ID interno en `additional_parameters` (p. ej. `{"techo_person_id": "12345"}`) como respaldo, pero no dependas de él para buscar.
- Normaliza teléfono y RUT antes de enviar (RUT sin puntos; Payku acepta con o sin guion ✅).

### Ejemplo práctico
Alta de socio en el formulario web → backend busca por email → si no existe, `POST /api/suclient` → guarda `payku_client_id` en `payku_cliente_map` → continúa con [create-subscription.md](workflows/create-subscription.md).

---

## Obtener cliente

Consulta el detalle de un cliente, con sus tarjetas, suscripción y cobros.

### Endpoint

```http
GET /api/suclient/{identificadorCliente}
GET /api/suclient/{emailCliente}
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Obtener cliente"

### Propósito
- **Para qué sirve:** ver datos, tarjetas activas y suscripción (con cobros) de un cliente. ✅
- **Cuándo usarlo:** (1) antes de crear, para evitar duplicados (búsqueda por email); (2) en soporte; (3) para reconstruir el estado de un socio puntual.
- **Relación:** devuelve `subcriptions` (con `plan`, `cards`, `transactions`) y `active_cards`.

### Path parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `identificadorCliente` o `emailCliente` | string | ✓ | ID de Payku **o** email. La doc indica "máximo 20 caracteres". ✅ ⚠️ Un email suele superar 20 caracteres; parece un error de la documentación. Validar. |

💡 Codifica el email en el path si contiene caracteres especiales. Recuerda que la firma se calcula sobre el **path real** (con el email o ID).

### Response (200) — resumida

```json
{
  "status": "active",
  "id": "cl0be4c8e623c167bc8b777",
  "rut": "11111111",
  "name": "John Doe",
  "email": "johndoe@example.com",
  "created_at": "2023-09-29 22:00:00",
  "update_at": null,
  "active_cards": [
    { "last_4_digits": "XXXXXXXXXXXX6622", "identifier": "surec804a8ed60c747cb8839", "card_type": "Visa", "register": "2023-07-26 08:00:19" }
  ],
  "additional_parameters": { "parameter_1": "example", "parameter_2": "example" },
  "subcriptions": {
    "id": "su867f07772aa5f5175527",
    "created_at": "2023-09-29 19:58:35",
    "status": "active",
    "amount": "15000",
    "plan": [ { "id": "pl9697fb170834ad42dd00", "name": "test plan", "currency": "CLP" } ],
    "cards": [ { "last_4_digits": "XXXXXXXXXXXX6623", "card_type": "Visa" } ],
    "transactions": [
      { "created_at": "2023-09-30 19:58:35", "date_payment": "2023-09-30", "amount": 10000, "transaction": 204444,
        "authorization_code": "1234", "order": "001", "description": "descripcion", "status": "success" }
    ]
  }
}
```

### Campos importantes

| Campo | Tipo | Descripción | Uso interno 💡 |
|---|---|---|---|
| `active_cards[].identifier` | string | ID de tarjeta. | Para cobrar a una tarjeta específica (consumo) o eliminarla. |
| `subcriptions` | **objeto** | Suscripción del cliente. ⚠️ Es un objeto, no un arreglo: no sabemos cómo se ve con 2+ suscripciones. | Para sync usa V3, no este campo. |
| `subcriptions.amount` | string | Monto de la suscripción. | — |
| `subcriptions.transactions[].status` | string | Estado del cobro (**Lista A**: incluye `retry`, `maximum attempt limit`…). | Ver [statuses.md](statuses.md#2-cobro-de-suscripción). |
| `subcriptions.transactions[].date_payment` | string | Fecha del pago. | Solo aparece aquí (no en el detalle de suscripción). |

### Errores
Estándar → [errors.md](errors.md). ⚠️ No hay ejemplo de 404 para cliente inexistente.

### Consideraciones
- Este endpoint es de **un cliente a la vez**. No lo uses para sincronizar en masa.
- Los estados de cobro de aquí (Lista A) son distintos a los del detalle de suscripción (Lista B).

---

## Actualizar cliente

### Endpoint

```http
PUT /api/suclient/{identificadorCliente}
PUT /api/suclient/{emailCliente}
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Actualizar cliente"

### Propósito
Actualizar datos de contacto del cliente. 💡 Úsalo cuando el socio cambia email, teléfono o dirección en nuestro sistema.

### Path parameters
Igual que "Obtener cliente" (ID; el título del endpoint también admite email ✅).

### Request body (todos opcionales)

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `email` | string | | Máx. 50. (La doc lo describe por error como "Nombre del cliente"). |
| `name` | string | | Máx. 80. |
| `phone` | string | | Máx. 20. |
| `address` | string | | Máx. 200. |
| `country` | string | | Máx. 40. |
| `region` | string | | Máx. 120. |
| `city` | string | | Máx. 40. |
| `postal_code` | string | | Máx. 10. |
| `additional_parameters` | object | | Máx. 4000. |

⚠️ `rut` **no aparece** en el body de actualización. No sabemos si se puede corregir un RUT.

### Response (200)
Igual estructura que "Obtener cliente", con `update_at` lleno (ej. `"2023-10-2 08:32:52"`, sin cero en el día). Los estados de `transactions[]` pueden incluir `canceled by paymáster` (con tilde). ✅

### Consideraciones
- 💡 Envía solo los campos que cambian: cada campo enviado entra en la firma.
- ⚠️ No está documentado si `additional_parameters` se **reemplaza** completo o se **mezcla**. Envía siempre el objeto completo.
- Si cambias el email, actualiza también nuestra tabla `payku_cliente_map` (el email deja de servir como clave de búsqueda antigua).

---

## Eliminar cliente

### Endpoint

```http
DELETE /api/suclient/{identificadorCliente}
DELETE /api/suclient/{emailCliente}
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Eliminar cliente"

### Propósito
"Eliminación de un cliente asociado a un ID de usuario." ✅

### Response (200)

```json
{ "status": "success", "id": "cl0be4c8e623c167bc8b777" }
```

### Consideraciones ⚠️
- No está documentado qué pasa con las **suscripciones activas** del cliente al eliminarlo (¿se cancelan?, ¿se rechaza la operación?).
- No sabemos si es borrado físico o lógico.
- 💡 **Recomendación:** no eliminar clientes. Para dar de baja a un socio, elimina su suscripción ([cancel-subscription.md](workflows/cancel-subscription.md)) y conserva el cliente para historial.

---

## Obtener clientes (listado)

### Endpoint

```http
GET /api/suclient/customers?page=1&per_page=100
```

### Documentación oficial
https://docs.payku.com/cl/api/subscriptions/ → "Obtener clientes"

### Propósito
Listar todos los clientes de la cuenta. Útil para carga inicial y para detectar clientes nuevos creados fuera de nuestra integración (p. ej. desde el panel de Payku).

### Query parameters

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `page` | int | | Página. ✅ |
| `per_page` | int | | Máximo **100**. ✅ |
| (filtro de fecha) | date | | "Posee un filtro de fecha; si no se ingresa se toma la fecha actual". ✅ **Nombre del parámetro no documentado.** ⚠️ 💡 Probar `date_init` / `date_end`. |

### Response (200) ⚠️

```json
[ { "Customers": [ { … }, { … } ] } ]
```

⚠️ El ejemplo oficial está **mal formado**: dentro de `Customers` mezcla datos de tarjetas con el **esquema** OpenAPI de `subcriptions` (`"type": "array"`, `"items"`…). No podemos saber la forma real de cada cliente hasta probarlo. 💡 Probablemente cada elemento se parece a la respuesta de "Obtener cliente", con `subcriptions` como arreglo.

### Paginación
Página por página, máximo 100 → [pagination.md](pagination.md).

### Consideraciones
- 💡 Por el límite de 100 y la falta de esquema fiable, para sincronizar preferimos **V3 de suscripciones** (que ya trae los datos del cliente) y usar este listado solo como control.
- Sin filtro de fecha devuelve solo los clientes de **hoy**. ✅
