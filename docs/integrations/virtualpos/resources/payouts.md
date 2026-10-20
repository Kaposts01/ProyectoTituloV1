# Payouts (Transferencias)

> Fuente: https://virtualpos.readme.io/reference/introducción-a-payout · Verificado: 2026-10-12

Servicio para **enviar** dinero por transferencia electrónica (TEF) desde la cuenta del comercio: pagos a proveedores, devoluciones, reembolsos. Es una API **separada** de Payments.

| Ambiente | Base URL |
| --- | --- |
| Sandbox | `https://payout-api.virtualpos-sandbox.com` |
| Producción | `https://payout-api.virtualpos.cl` |

### Seguridad (obligatorio)

- Firma JWT (como el resto de la API, pero con payload propio).
- **mTLS** (certificado de cliente).
- Informar a VirtualPOS las **IPs** desde donde se llamará.
- API KEY y SECRET KEY propias de Payout, entregadas durante el proyecto de integración.

### Firma

Para *Crear payout*, *Consultar por id* y *Consultar por merchant id*, el payload del JWT es:

```json
{
  "api_key": "yourApiKey",
  "tef": {
    "merchant_id": "tef-XXXXX-XX",
    "message": "Devolución de compra OC XXX",
    "amount": 12500,
    "recipient": { "rut": "1111111-1", "name": "John Doe", "email": "johndoe@virtualpos.cl" },
    "bank": { "sbif_code": "111", "account_number": "11111111" }
  }
}
```

### Webhook de payout

Obligatorio. VirtualPOS envía un `HTTPS POST` con el objeto payout en el body por cada transferencia procesada. El header **`Signature`** trae un **HMAC-SHA256 del body** con tu secret key: **valídalo siempre**. Ver [webhooks.md](webhooks.md#4-webhook-de-payout).

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `POST` | `/v3/payout` | [Crear una nueva instrucción de payout](#crear-una-nueva-instrucción-de-payout) |
| `GET` | `/v3/payout/account/balance` | [Obtener saldo disponible](#obtener-saldo-disponible) |
| `GET` | `/v3/payout/{payout_id}` | [Consultar estado de payout por id](#consultar-estado-de-payout-por-id) |
| `GET` | `/v3/payout/merchant/{merchant_id}` | [Consultar estado de payout por merchant id](#consultar-estado-de-payout-por-merchant-id) |

## Objeto Payout

| Status | Descripción |
| --- | --- |
| `PENDING` | Inicial: creado, esperando procesamiento. |
| `PROCESSING` | Transitorio: en proceso, terminará en `COMPLETED` o `FAILED`. |
| `COMPLETED` | Final: transferencia realizada. |
| `FAILED` | Final: no se pudo realizar; ver `errorType`. |

```json
{
  "id": "po_406538224cd1628",
  "status": "PENDING",
  "created_at": "2023-10-12 10:50:11",
  "updated_at": "2023-10-12 11:10:50",
  "tef": {
    "merchant_id": "tef-12801-01",
    "message": "Devolución de compra OC 873",
    "amount": 12500,
    "recipient": { "rut": "18123328-1", "name": "John Doe", "email": "johndoe@virtualpos.cl" },
    "bank": { "sbif_code": "037", "account_number": "786345987" }
  }
}
```

### Tipos de error en transferencias fallidas (`errorType`)

| Error type | Descripción |
| --- | --- |
| `ERROR_ACCOUNT_INCORRECT` | La cuenta proporcionada no es válida o no existe. |
| `ERROR_ACCOUNT_NOT_ACCEPT_TRANSFERS` | La cuenta especificada no acepta transferencias. |
| `ERROR_ACCOUNT_CLOSED` | La cuenta se encuentra cerrada o inactiva. |
| `ERROR_AMOUNT_INCORRECT` | El monto especificado es incorrecto o inválido |
| `ERROR_BENEFICIARY_DOCUMENT_ID_INVALID` | El documento de identificación del beneficiario no es válido. |
| `ERROR_INVALID_REQUEST_BODY` | Indica un problema con el contenido de la solicitud, como un formato incorrecto o datos faltantes. |
| `NETWORK_SERVICE_UNAVAILABLE` | Servicio de red no disponible. No se puede completar la operación debido a problemas de conectividad. |
| `INSUFFICIENT_USER_BALANCE` | Saldo insuficiente en la cuenta del usuario para realizar la transacción. |
| `ERROR_OTHER` | Otro error no clasificado. Puede ser necesario revisar los detalles adicionales para obtener más información sobre el problema específico. |

### Códigos de error de la API de Payout

> Ojo: los códigos `E-###` de Payout **no significan lo mismo** que los de Payments (ej. `E-003` es `merchant_id` aquí y `amount` allá). Discrimina por API.

| Código | Mensaje |
| --- | --- |
| `E-001` | Error en el parámetro Authorization. |
| `E-002` | Error en el parámetro Signature. |
| `E-003` | Error en el parámetro merchant_id. |
| `E-004` | Error en el parámetro message. |
| `E-005` | Error en el parámetro amount. |
| `E-006` | Error en el parámetro rut. |
| `E-007` | Error en el parámetro name. |
| `E-008` | Error en el parámetro email. |
| `E-009` | Error en el parámetro sbif_code. |
| `E-010` | Error en el parámetro account_number. |
| `E-011` | Error en el parámetro amount, debe ser numérico. |
| `E-012` | Error en el parámetro amount, debe ser número entero mayor o igual a. |
| `E-013` | Error en el parámetro amount, debe ser número entero menor o igual a. |
| `E-014` | Error en el parámetro email, no cumple con formato. |
| `E-015` | Error, no existe el comercio asociado a la api key. |
| `E-016` | La verificación de la firma es incorrecta. |
| `E-017` | Firma es incorrecta. |
| `E-018` | Parámetros en la firma tienen errores. |
| `E-019` | merchant_id duplicado. |
| `E-020` | Error, Ha sobrepasado el número máximo de transacciones permitidas para 1 dia. |
| `E-021` | Error, Ha sobrepasado el monto máximo de transacciones permitidas para 1 dia. |
| `E-022` | Error al generar la TEF. |
| `E-022-001` | Error al generar la TEF - El monto solicitado para realizar la transferencia supera el monto máximo permitido. |
| `E-022-002` | Error al generar la TEF - El código de banco, no se encuentra registrado o permitido para operar. |
| `E-022-003` | Error al generar la TEF - El RUT ingresado no tiene un formato válido. |
| `E-022-004` | Error al generar la TEF - Saldo insuficiente para realizar la transferencia. |
| `E-022-005` | Error al generar la TEF - La cuenta bancaria proporcionada es inválida. |
| `E-023` | Error en el parámetro payout_id. |
| `E-024` | Error al obtener el estatus de la TEF. |
| `E-025` | Error al obtener la TEF. |
| `E-026` | No existe payout |
| `E-027` | Error al obtener el balance. |

### Bancos (códigos SBIF)

| Código SBIF | Banco |
| --- | --- |
| `001` | Banco de Chile |
| `009` | Banco Internacional |
| `012` | Banco del Estado |
| `014` | Scotiabank, BancoDesarrollo |
| `016` | Banco BCI / Mach, TBanc, Banco Nova |
| `028` | Banco BICE |
| `031` | Banco HSBC |
| `037` | Banco Santander, Banefe |
| `039` | Banco Itaú Corpbanca, Banco Corpbanca |
| `049` | Banco Security |
| `051` | Banco Falabella |
| `053` | Banco Ripley |
| `055` | Banco Consorcio |
| `504` | Scotiabank Azul BBVA |
| `672` | Coopeuch |
| `729` | Prepago Los Héroes |
| `730` | Tenpo |
| `732` | Prepago Los Andes |
| `738` | Global 66 |
| `875` | MercadoPago |

---

## Crear una nueva instrucción de payout

> Fuente oficial: [Crear una nueva instrucción de payout](https://virtualpos.readme.io/reference/crear-una-nueva-instrucción-de-payout)

### Endpoint

```http
POST /v3/payout
```

Base URL: `https://payout-api.virtualpos-sandbox.com` (sandbox) · `https://payout-api.virtualpos.cl` (producción)

### Propósito

Ordena una transferencia electrónica de fondos (TEF) desde la cuenta del comercio a un destinatario (proveedores, devoluciones, reembolsos).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", "tef": { ...body... }}` (confirmado en *Autenticación y firma – Payout*). Además requiere **mTLS** e IP en lista blanca.

### Path parameters

No aplica.

### Query parameters

No aplica.

### Request body

Ejemplo:

```json
{
  "merchant_id": "tef-12801-01",
  "message": "Devolución de compra OC 873",
  "amount": 12500,
  "recipient": {
    "rut": "18123328-1",
    "name": "John Doe",
    "email": "johndoe@virtualpos.cl"
  },
  "bank": {
    "sbif_code": "037",
    "account_number": "786345987"
  }
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "id": "po_406538224cd1628",
  "status": "pending",
  "created_at": "2023-10-12 10:50:11",
  "updated_at": "2023-10-12 11:10:50",
  "tef": {
    "merchant_id": "tef-12801-01",
    "message": "Devolución de compra OC 873",
    "amount": 12500,
    "recipient": {
      "rut": "18123328-1",
      "name": "John Doe",
      "email": "johndoe@virtualpos.cl"
    },
    "bank": {
      "sbif_code": "037",
      "account_number": "786345987"
    }
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `id` | ID del payout (`po_...`). |
| `status` | Estado inicial (`pending` en el ejemplo, `PENDING` en el objeto). |
| `tef` | Eco de la instrucción. |

### Estados posibles

`PENDING` → `PROCESSING` → `COMPLETED` | `FAILED`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-003` | Error en el parámetro merchant_id. |
| `E-004` | Error en el parámetro message. |
| `E-005` | Error en el parámetro amount. |
| `E-006` | Error en el parámetro rut. |
| `E-007` | Error en el parámetro name. |
| `E-008` | Error en el parámetro email. |
| `E-009` | Error en el parámetro sbif_code. |
| `E-010` | Error en el parámetro account_number. |
| `E-011` | Error en el parámetro amount, debe ser numérico. |
| `E-012` | Error en el parámetro amount, debe ser número entero mayor o igual a. |
| `E-013` | Error en el parámetro amount, debe ser número entero menor o igual a. |
| `E-019` | merchant_id duplicado. |
| `E-020` | Error, Ha sobrepasado el número máximo de transacciones permitidas para 1 dia. |
| `E-021` | Error, Ha sobrepasado el monto máximo de transacciones permitidas para 1 dia. |
| `E-022` | Error al generar la TEF. |
| `E-022-001` | Error al generar la TEF - El monto solicitado para realizar la transferencia supera el monto máximo permitido. |
| `E-022-002` | Error al generar la TEF - El código de banco, no se encuentra registrado o permitido para operar. |
| `E-022-003` | Error al generar la TEF - El RUT ingresado no tiene un formato válido. |
| `E-022-004` | Error al generar la TEF - Saldo insuficiente para realizar la transferencia. |
| `E-022-005` | Error al generar la TEF - La cuenta bancaria proporcionada es inválida. |

### Consideraciones

- **Base URL distinta:** `https://payout-api.virtualpos.cl` (sandbox `https://payout-api.virtualpos-sandbox.com`).
- Requiere **mTLS** y lista blanca de IPs además de JWT; las llaves se entregan en el proyecto de integración (no son las del portal).
- Firma: el payload JWT es `{"api_key": ..., "tef": { ...body... }}`.
- `merchant_id` es tu ID único de la transferencia (`E-019` si se repite) → **idempotencia natural**.
- RUT del destinatario sin puntos.
- El ejemplo devuelve `status` en minúscula (`pending`) y el objeto Payout lo documenta en mayúscula: normaliza.

### Ejemplo práctico

Devolución de una donación duplicada: crea el payout con `merchant_id = DEV-<id_donacion>` y espera el webhook de payout.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url_payout}}/v3/payout
```

---

## Obtener saldo disponible

> Fuente oficial: [Obtener saldo disponible](https://virtualpos.readme.io/reference/obtener-saldo-disponible)

### Endpoint

```http
GET /v3/payout/account/balance
```

Base URL: `https://payout-api.virtualpos-sandbox.com` (sandbox) · `https://payout-api.virtualpos.cl` (producción)

### Propósito

Devuelve el saldo disponible para hacer payouts.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}` (ver nota en Consideraciones). Además requiere **mTLS** e IP en lista blanca.

### Path parameters

No aplica.

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "balance": 1000000
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `balance` | Saldo disponible (entero). |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-001` | Error en el parámetro Authorization. |
| `E-002` | Error en el parámetro Signature. |
| `E-015` | Error, no existe el comercio asociado a la api key. |
| `E-027` | Error al obtener el balance. |

### Consideraciones

- La OpenAPI nombra el header como `Authentication` (probable errata); el resto de la doc usa `Authorization`. Envía `Authorization`. No confirmado en la documentación oficial de VirtualPOS.
- Consulta el saldo antes de lotes grandes para evitar `E-022-004` (saldo insuficiente).

### Ejemplo práctico

Antes de un lote de devoluciones, valida que `balance` ≥ suma del lote.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url_payout}}/v3/payout/account/balance
```

---

## Consultar estado de payout por id

> Fuente oficial: [Consultar estado de payout por id](https://virtualpos.readme.io/reference/consultar-estado-de-payout)

### Endpoint

```http
GET /v3/payout/{payout_id}
```

Base URL: `https://payout-api.virtualpos-sandbox.com` (sandbox) · `https://payout-api.virtualpos.cl` (producción)

### Propósito

Consulta un payout por el `id` que entregó VirtualPOS (`po_...`).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}` (ver nota en Consideraciones). Además requiere **mTLS** e IP en lista blanca.

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| payout_id | string | Sí | ID del payout (`po_...`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "id": "po_406538224cd1628",
  "status": "pending",
  "errorType": "",
  "created_at": "2023-10-12 10:50:11",
  "updated_at": "2023-10-12 11:10:50",
  "tef": {
    "merchant_id": "tef-12801-01",
    "message": "Devolución de compra OC 873",
    "amount": 12500,
    "recipient": {
      "rut": "18123328-1",
      "name": "John Doe",
      "email": "johndoe@virtualpos.cl"
    },
    "bank": {
      "sbif_code": "037",
      "account_number": "786345987"
    }
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `status` | Estado actual. |
| `errorType` | Motivo cuando `FAILED` (ver tabla de tipos de error). |

### Estados posibles

`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-023` | Error en el parámetro payout_id. |
| `E-024` | Error al obtener el estatus de la TEF. |
| `E-025` | Error al obtener la TEF. |
| `E-026` | No existe payout |

### Consideraciones

- La doc dice que para este método la firma también lleva la estructura `tef`, lo que no tiene sentido en un GET sin body. Prueba primero con `{api_key}`. No confirmado en la documentación oficial de VirtualPOS.

### Ejemplo práctico

Respaldo del webhook: si no llegó notificación en X minutos, consulta el estado.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url_payout}}/v3/payout/{{payout_id}}
```

---

## Consultar estado de payout por merchant id

> Fuente oficial: [Consultar estado de payout por merchant id](https://virtualpos.readme.io/reference/consultar-estado-de-payout-por-id-copy)

### Endpoint

```http
GET /v3/payout/merchant/{merchant_id}
```

Base URL: `https://payout-api.virtualpos-sandbox.com` (sandbox) · `https://payout-api.virtualpos.cl` (producción)

### Propósito

Consulta un payout por **tu** `merchant_id`. Útil cuando hubo timeout y no recibiste el `po_...`.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}` (ver nota en Consideraciones). Además requiere **mTLS** e IP en lista blanca.

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| merchant_id | string | Sí | Tu identificador de la transferencia (ej. `tef-12801-01`). |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "id": "po_406538224cd1628",
  "status": "pending",
  "errorType": "",
  "created_at": "2023-10-12 10:50:11",
  "updated_at": "2023-10-12 11:10:50",
  "tef": {
    "merchant_id": "tef-12801-01",
    "message": "Devolución de compra OC 873",
    "amount": 12500,
    "recipient": {
      "rut": "18123328-1",
      "name": "John Doe",
      "email": "johndoe@virtualpos.cl"
    },
    "bank": {
      "sbif_code": "037",
      "account_number": "786345987"
    }
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `status` | Estado actual. |
| `errorType` | Motivo de falla. |

### Estados posibles

`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-024` | Error al obtener el estatus de la TEF. |
| `E-025` | Error al obtener la TEF. |
| `E-026` | No existe payout |

### Consideraciones

- Clave para reintentos seguros: si el POST dio timeout, consulta por `merchant_id` antes de reenviar.

### Ejemplo práctico

Timeout al crear el payout → `GET /v3/payout/merchant/{merchant_id}` → si existe, no lo vuelvas a crear.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url_payout}}/v3/payout/merchant/{{payout_merchant_id}}
```

---
