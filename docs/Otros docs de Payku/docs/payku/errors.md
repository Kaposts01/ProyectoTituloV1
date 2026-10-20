# Errores

Documentación oficial:
- Introducción (nota sobre HTTP 200): https://docs.payku.com/cl/introduction/
- Errores: https://docs.payku.com/cl/errors/

---

## 1. La regla más importante ✅

> "No te fíes solo del código HTTP (por ejemplo, 200). En nuestra API, muchas respuestas con error también llegan con código HTTP 200. Esto es intencional y forma parte del diseño de la API."

Siempre revisa el campo `status` del JSON:

- `status == "success"` → la operación se realizó. ✅
- `status == "failed"` → hubo un error; lee el mensaje que viene en la misma respuesta. ✅

⚠️ **Matiz que la regla no cubre:** muchos endpoints exitosos **no** devuelven `"success"` en `status`, sino el **estado del recurso**:

| Endpoint | `status` en respuesta exitosa |
|---|---|
| `POST /api/transaction` | `pending` |
| `POST /api/suclient`, `GET /api/suclient/{id}` | `active` (estado del cliente) |
| `POST /api/sususcription` | `register` (estado de la suscripción) |
| `DELETE /api/maclient/{id}` | `suspended` |
| `POST /api/suscriptionsdeletecards` | `Delete` |
| `GET /api/sususcription` / `v3` / `/api/suclient/customers` | No hay `status` raíz: la respuesta es un **arreglo** |

💡 **Regla para nuestro backend:** un response es error si (a) HTTP ≥ 400, **o** (b) HTTP 200 y `status == "failed"`, **o** (c) HTTP 200 y el JSON no tiene la forma esperada para ese endpoint (validación de esquema). Nunca uses "`status != success` = error".

---

## 2. Códigos HTTP documentados ✅

| HTTP | Nombre | Significado (Payku) | Acción recomendada 💡 |
|---|---|---|---|
| 400 | Bad Request | Hay un problema con tu request | No reintentar. Corregir datos. Loguear `message_error`. |
| 401 | Unauthorized | Token incorrecto o error de firma | No reintentar. Revisar token y firma ([authentication.md](authentication.md)). Alertar. |
| 403 | Forbidden | No tienes permiso para ver esta página | No reintentar. Revisar permisos o productos habilitados en la cuenta. |
| 404 | Not Found | El recurso no fue encontrado | No reintentar. En sync: marcar como "no encontrado", no como borrado (ver abajo). |
| 405 | Method Not Allowed | Método inválido | Bug nuestro. |
| 406 | Not Acceptable | Pediste un formato que no es JSON | Enviar `Accept: application/json`. |
| 410 | Gone | El recurso fue removido | No reintentar. 💡 Candidato a marcar como eliminado en origen. |
| 422 | Unprocessable Entity | No se puede procesar tu solicitud | No reintentar. Validación de datos. |
| 429 | Too Many Requests | "¡Estás solicitando muchos recursos! ¡Detente!" | Reintentar con backoff exponencial + jitter. ⚠️ Límites no documentados. |
| 500 | Internal Server Error | Problema en el servidor de Payku | Reintentar con backoff (solo GET o POST idempotentes, ver § 5). |
| 503 | Service Unavailable | Offline por mantenimiento | Reintentar con backoff largo. |

⚠️ No hay **rate limits** documentados (requests por segundo o por minuto), ni header `Retry-After`. Empieza conservador (p. ej. ≤ 2 req/s) y mide.

---

## 3. Formatos de error observados en la documentación ✅

Payku **no usa un único formato**. El parser debe aceptar todos:

**A. Validación (400 / 422, y también con HTTP 200):**

```json
{
  "status": "failed",
  "type": "Unprocessable Entity",
  "message_error": "subject:invalid,amount:is empty,email:is empty,order:invalid"
}
```

`message_error` es un string con pares `campo:problema` separados por coma. 💡 Se puede convertir a dict para logs.

**B. Token público inválido (401):**

```json
{ "type": "Unauthorized", "message_error": { "error": "waiting token public" } }
```

Aquí `message_error` es un **objeto** y no hay campo `status`.

**C. Identificador inexistente (404):**

```json
{ "status": "failed", "type": "Not Found", "id": "is not valid" }
```

**D. Tarjeta inválida (Eliminar tarjeta, 400):**

```json
{ "status": "failed", "type": "card", "message_error": "is not valid" }
```

**E. Catálogos (bancos / métodos de pago, 400):**

```json
{ "status": "failed", "type": "Unprocessable Entity", "message_error": "Hay un problema con tu request" }
```

💡 Modelo interno sugerido para cualquier error:

```python
@dataclass
class PaykuError(Exception):
    http_status: int
    payku_status: str | None      # "failed" o None
    error_type: str | None        # "Unprocessable Entity", "Unauthorized", "Not Found", "card"...
    message: str                  # message_error aplanado a string
    field_errors: dict[str, str]  # {"amount": "is empty", ...} si se pudo parsear
    raw: dict | str               # respuesta original completa (para auditoría)
    endpoint: str
    request_id: str               # nuestro ID de correlación
```

---

## 4. Mensajes de rechazo de pago (no son errores de API) ✅

Un pago **rechazado** es un resultado válido de negocio, no un error HTTP. En transacciones, `gateway_response.message` puede traer:

- `successful transaction`
- `Rechazo de transacción.`
- `Transacción debe reintentarse.`
- `Error en transacción.`
- `Rechazo por error de tasa.`
- `Excede cupo máximo mensual.`
- `Excede límite diario por transacción.`
- `Rubro no autorizado.`

💡 Guárdalos tal cual en staging y clasifícalos después en el modelo normalizado (rechazo del emisor / reintentable / error técnico).

---

## 5. Reintentos e idempotencia

⚠️ **Payku no documenta claves de idempotencia** (no hay header tipo `Idempotency-Key`).

| Operación | ¿Reintentar automáticamente ante timeout/5xx? | Por qué |
|---|---|---|
| `GET` (cualquiera) | Sí, con backoff | Solo lectura. |
| `DELETE /api/sususcription/{id}` | Sí, con cuidado | 💡 Repetir un borrado debería ser inofensivo; confirmar con `GET` después. |
| `POST /api/suclient` | **No a ciegas** | Puede crear un cliente duplicado. Primero `GET /api/suclient/{email}`. |
| `POST /api/sususcription` | **No a ciegas** | Puede crear una segunda suscripción. Verifica con la lista del cliente. |
| `POST /api/sutransaction` | **Nunca a ciegas** | **Puede cobrar dos veces.** Primero busca el `order` en los cobros de la suscripción. |
| `POST /api/transaction` | **No a ciegas** | Puede generar dos órdenes de pago. |
| `POST /api/nullification`, `wallet/payout`, `wallet/withdraw` | **Nunca a ciegas** | Mueven dinero. Requiere revisión manual. |

💡 Patrón "verificar antes de reintentar":
1. Antes del POST, guarda en nuestra BD la intención con un `order` único nuestro (estado `PENDING_SEND`).
2. Si hay timeout o 5xx, **no** repitas: consulta el recurso (por `order`, `email` o ID) para ver si se creó.
3. Solo si confirmas que no existe, reintenta con el **mismo** `order`.

Backoff sugerido: 1 s, 2 s, 4 s, 8 s, 16 s (máximo 5 intentos) + jitter aleatorio de 0–1 s. Timeout de conexión 5 s y de lectura 30 s (listados grandes pueden tardar; ⚠️ tiempos de respuesta no documentados).

---

## 6. 404 en sincronización

💡 Un 404 en `GET /api/sususcription/{id}` **no** significa necesariamente que la suscripción fue borrada (puede ser un ID mal copiado, otro ambiente u otra cuenta). En sync:
- marca el registro como `NOT_FOUND_IN_SOURCE` con fecha;
- solo considéralo "eliminado" tras N verificaciones o si el estado previo era `delete` o `cancel`.
