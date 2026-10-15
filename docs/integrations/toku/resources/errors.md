# Errores, códigos de respuesta y límites de tasa

Docs oficiales:
- <https://docs.trytoku.com/reference/errores-y-codigos-de-respuesta>
- <https://docs.trytoku.com/reference/codigos-http-de-respuesta>
- <https://docs.trytoku.com/reference/codigos-de-api>
- <https://docs.trytoku.com/reference/codigos-de-pago-rechazado>
- <https://docs.trytoku.com/reference/rate-limits>

## 1. Formatos de error [Confirmado]

Toku usa **varios formatos** según el módulo. El cliente HTTP debe tolerarlos todos.

| Schema | Forma | Dónde aparece |
|---|---|---|
| `ApiBilling_ErrorResponse` | `{ "error": { "code": "TKxxxxx", "message": "..." } }` | `422` de Customers, Subscriptions e Invoices |
| `HTTPError` | `{ "code": 404, "message": "..." }` (`code` es **entero**) | `401`, `403`, `404`, `429` de Customers, Subscriptions e Invoices |
| `ApiPaymentMethod_ErrorResponse` / `ApiWebhook_ErrorResponse` | `{ "error": { "code", "message" } }` | Payment Methods, Webhooks, Transactions |
| `ApiPaymentMethod_BaseResponse` | `{ "success": false, "detail": ... }` | `400`/`404` en asociación de Payment Methods y Collection Accounts |
| Detalle de validación | `{ "error": {...}, "detail": [ { "loc": [...], "msg": "...", "type": "..." } ] }` | Algunos `422` |

**[Recomendación]** Normalizar todo en una excepción interna:

```python
class TokuAPIError(Exception):
    def __init__(self, http_status, toku_code=None, message=None, details=None, raw=None): ...

def parse_error(status, body):
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return TokuAPIError(status, err.get("code"), err.get("message"), body.get("detail"), body)
        if "message" in body:  # HTTPError
            return TokuAPIError(status, str(body.get("code")), body.get("message"), None, body)
        if body.get("success") is False:
            return TokuAPIError(status, None, str(body.get("detail")), None, body)
    return TokuAPIError(status, None, None, None, body)
```

## 2. Códigos HTTP [Confirmado: significado] / [Recomendación: acción]

| HTTP | Significado (Toku) | ¿Reintentar? | Acción recomendada |
|---|---|---|---|
| 200 | OK (también un upsert que **actualizó**) | — | — |
| 201 | Creado (upsert que **creó**) | — | Persistir el `id` devuelto |
| 202 | Aceptado, se procesa de forma asíncrona (por ejemplo, borrado diferido de una Invoice con cobro en curso) | — | Registrar y confirmar después por webhook o GET |
| 204 | OK sin body (DELETE) | — | — |
| 400 | Petición mal formada | No | Corregir el request |
| 401 | Falta credencial o formato incorrecto | No | Revisar la key; alertar |
| 403 | Credencial válida sin permisos | No | Revisar permisos o la `x-account-key` |
| 404 | No existe o no es visible para la organización/cuenta | No | En sync: marcar como "no encontrado"; puede ser la cuenta equivocada |
| 409 | Choca con el estado actual del recurso | No sin cambiar algo | Releer el recurso y decidir |
| 422 | Bien formada pero no valida | No | Revisar `error.code` y `detail` |
| 429 | Rate limit | **Sí** | Backoff exponencial, sin paralelismo |
| 5xx | Error de Toku | **Sí, acotado** | 3–5 reintentos con backoff y luego alerta |

**[Recomendación]** Reintentar también ante timeouts y errores de red, **pero solo en operaciones idempotentes**. En Toku, los `POST` de creación son upserts por clave de negocio, así que reintentarlos con el **mismo body** es seguro (ver [data-model.md](data-model.md#3-idempotencia)). En `POST /subscriptions/associate/payment-method` y en las acciones de estado, verificar con un GET antes de reintentar.

## 3. Códigos internos `TKxxxxx` [Confirmado]

Formato: `TK` + 5 dígitos. La doc los publica para Customer, Subscription e Invoice. **Otros endpoints pueden devolver códigos no listados.** En ese caso hay que usar el status HTTP y `error.message`.

### Generales
| Código | Descripción |
|---|---|
| TK30000 | La validación de la petición falló |
| TK30100 | País no soportado para validar `government_id` |

### Customer
| Código | Descripción | Acción interna sugerida |
|---|---|---|
| TK20400 | Customer no existe | Verificar el ID; resincronizar |
| TK20401 | Customer bloqueado por otra carga en curso | **Reintentar más tarde** |
| TK30400 | El payload no incluye identificador externo | Enviar `external_id` |
| TK30401 | `external_id` no coincide con `customer_external_id_parameter` de la organización | Revisar qué campo usa la organización como ID externo |
| TK30402 | `government_id` inválido | Validar el RUT antes de enviar |
| TK30403 | Preferencia de teléfono inválida | Corregir el dato |
| TK30404 | Teléfono inválido | Normalizar a E.164 (`+569…`) |
| TK30405 | Email con sintaxis inválida | Validar el formato |
| TK30406 | Email en lista negra | Pedir otro mail |
| TK30407 | Conflicto lógico al eliminar | Revisar sus dependencias |
| TK30408 | Código de país del teléfono no soportado | — |
| TK30409 | Customer no encontrado por `external_id` | — |
| TK30410 | Customer ya existe en una operación donde no se permite | — |
| TK30411 | **`external_id` no se puede actualizar** | No enviar `external_id` en `PUT /customers/{id}` |
| TK00499 | Error interno al guardar el Customer | Reintentar acotado |

### Subscription
| Código | Descripción |
|---|---|
| TK20500 | Subscription no existe |
| TK20501 | No hay Subscription para ese Customer |
| TK30500 | Conflicto lógico al eliminar |
| TK30501 | Se intentó transferir la Subscription a otro Customer |
| TK30502 | Conflicto lógico al editar |
| TK30503 | Faltan campos requeridos |
| TK30504 | Conflicto lógico al crear |
| TK30505 | Ya existe en una operación donde no se permite |
| TK00599 | Error interno al guardar |

### Invoice
| Código | Descripción |
|---|---|
| TK20600 | Invoice no existe |
| TK20601 | No hay Invoice para ese Customer |
| TK30600 | Conflicto lógico al eliminar |
| TK30601 | Conflicto lógico al crear |
| TK30602 | Conflicto lógico al anular |
| TK30603 | Conflicto lógico al editar |
| TK30604 | Ya existe en una operación donde no se permite |
| TK30605 | Conflicto al validar la fecha de expiración |
| TK30606 | Conflicto al validar los campos de expiración |
| TK00600 | El servicio que actualiza montos no está disponible → **reintentar más tarde** |
| TK00699 | Error interno al guardar |

### Otros
| Código | Descripción |
|---|---|
| TK00799 | Error interno al guardar un Payment Method |
| TK00899 | Error interno al guardar una Transaction |
| TK30700 | Error de validación en el pre-procesamiento de un archivo de carga masiva |
| TK30701 | Error al cargar el archivo en el pre-procesamiento |

**[Recomendación]** Códigos reintentables: `TK20401`, `TK00600` y los `TK00x99` (errores internos), siempre con backoff y un máximo de intentos.

## 4. Códigos de resultado de cobro (`response_code` / `toku_response_code`) [Confirmado]

Están en Transactions (`response_code`) y en Payment Methods (`toku_response_code`). No son errores HTTP: describen **el resultado del cobro o de la inscripción**.

Formato: `GRAVEDAD(2) + FUENTE(3) + DETALLE(4)`. Ejemplo: `SUTOK0000`.

| Prefijo | Gravedad | Tratamiento |
|---|---|---|
| `SU` | Éxito | No es error. `0000` = cobro exitoso |
| `TE` | Temporal | Se puede reintentar con backoff |
| `PE` | Permanente | Reintentar no sirve: cambiar el medio de pago o contactar al socio |
| `UE` | Desconocido | Tratarlo como no reintentable. `9999` = respuesta no clasificable |

Listado completo con mensajes: <https://docs.trytoku.com/reference/codigos-de-pago-rechazado>.

**[Recomendación]** Guardar `response_code` crudo en STG y derivar en el modelo normalizado `gravedad = response_code[0:2]`, para reportes de rechazo (por ejemplo, socios con rechazo `PE` → campaña de actualización de medio de pago).

## 5. Límites de tasa [Confirmado]

| Grupo | Límite |
|---|---|
| Customers (todos los endpoints) | 20 req/s |
| Subscriptions | 20 req/s |
| Invoices | 20 req/s |
| **Transactions** (`GET /transactions`, `GET /transactions/{id}`) | **1 req/s** |
| Payment Methods, Webhook Endpoints, Collection Accounts | **[No confirmado]**: la doc solo documenta el `429` |

Reglas generales:
- Se superan → `429 Too Many Requests`. **La petición se descarta sin procesarse**: no se creó ni modificó nada, se puede reenviar.
- **La cuota es por credencial**, no por IP. Varios servidores con la misma key comparten la cuota.
- No se documentan headers de rate limit (`Retry-After`, `X-RateLimit-*`). **[No confirmado]** que existan; si llegan, conviene respetarlos.
- Toku recomienda backoff exponencial (1 s, 2 s, 4 s…) y **no reintentar en paralelo**. Si el `429` es sostenido, contactar a Toku.
