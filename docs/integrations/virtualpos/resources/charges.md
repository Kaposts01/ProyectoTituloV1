# Charges (Cargos)

> Fuente: https://virtualpos.readme.io/reference/objeto-charge-1 · Verificado: 2026-10-12

Un **Charge** es cada cobro de una suscripción: monto + fecha programada + descripción. Cuando se cobra, genera un **Payment** (orden) asociado.

```text
Plan ──< Suscription ──< Charge ──1 Payment (order.uuid) ──> Abono (deposit sales)
```

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `POST` | `/v3/charge` | [Crear un Charge](#crear-un-charge) |
| `POST` | `/v3/charge/online` | [Crear un Charge Online](#crear-un-charge-online) |
| `GET` | `/v3/charge/{charge_id}` | [Recuperar Charge](#recuperar-charge) |
| `DELETE` | `/v3/charge/{charge_id}` | [Cancelar Charge](#cancelar-charge) |
| `GET` | `/v3/charge/{charge_id}/retry` | [Reintentar Charge](#reintentar-charge) |
| `DELETE` | `/v3/charges/{suscription_id}` | [Cancelar Cargos Futuros](#cancelar-cargos-futuros) |
| `GET` | `/v3/suscription/{suscription_id}/charges` | [Listar Charges](#listar-charges) |

## Objeto Charge

| Status | Significado (inferido de los enums y ejemplos) |
| --- | --- |
| `pendiente` | Programado, aún no cobrado |
| `procesando` | En proceso de autorización |
| `pagado` | Cobrado |
| `rechazado` | Rechazado (se puede reintentar) |
| `cancelado` | Cancelado (manual, por cancelar cargos futuros o por cancelar la suscripción) |

> La doc oficial no tiene tabla de descripción de estados de Charge; solo el enum. Las descripciones son inferencia.

Ejemplo oficial de un cargo pagado (incluye el Payment asociado):

```json
{
  "id": "cid_2566645567e51ef2b7.76832273",
  "charge_date": "2023-05-08",
  "amount": 9900,
  "status": "pagado",
  "description": "Cargo 1 de 3",
  "created_at": "2021-09-08 11:20:31",
  "payment": {
    "client": { "email": "user@example.com", "first_name": "John", "last_name": "Doe", "social_id": "12345678-9", "phone": "56961934502" },
    "commerce": { "commerce_id": "76123456-7", "name": "ACME CORP" },
    "order": {
      "uuid": "083613a748190d26",
      "status": "pagado",
      "created_at": "2023-05-08 11:20:31",
      "card_number": 1234,
      "authorized_at": "2021-08-08 11:21:31",
      "auth_code": "1234",
      "installment_amount": 0,
      "installment_number": 0,
      "payment_type_code": "VN",
      "amount": 9990,
      "deposits": [ { "description": "1/1", "installment": 9900, "processing_flat_fee": 0, "processing_fee": 117, "payout_amount": 9783, "payout_date": "2023-03-11" } ]
    }
  }
}
```

---

## Crear un Charge

> Fuente oficial: [Crear un Charge](https://virtualpos.readme.io/reference/crear-un-charge)

### Endpoint

```http
POST /v3/charge
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Programa un cargo en una suscripción para una fecha futura (o hoy). Típico de planes `MONTO_VARIABLE`.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

No aplica.

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| charge_date | string (date) | Sí | Fecha en que se realizará el cargo. |
| amount | number (float) | Sí | Monto a cargar |
| description | string | Sí | Descripción asociada al cargo. |
| suscription_id | string | Sí | Identificador de la suscripción |
| internal_code | string | No | Identificador del servicio. |

Ejemplo:

```json
{
  "suscription_id": "3a4d77f2e4",
  "charge_date": "2026-11-05",
  "amount": 10000,
  "description": "Aporte noviembre 2026",
  "internal_code": "DON-2026-11-000123"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "suscription_id": "3a4d77f2e4",
  "charge": {
    "id": "id_2566645567e51ef2b7.76832273",
    "charge_date": "2023-05-08",
    "amount": 9900,
    "status": "pendiente",
    "description": "Cargo 1 de 3",
    "created_at": "2021-09-08 11:20:31"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `charge.id` | ID del cargo (`cid_...` según los demás ejemplos; aquí el ejemplo muestra `id_...`). |
| `charge.status` | `pendiente`. |

### Estados posibles

Nace `pendiente` → `procesando` → `pagado` | `rechazado`; o `cancelado`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-050` | Error en el parámetro suscription_id. |
| `E-054` | Error en el parámetro charge_date. |
| `E-055` | Error en el parámetro amount(Decimal). |
| `E-060` | No existe una suscripción ACTIVA para este charge_id: $charge_id |
| `E-076` | Error en el parámetro charge_date: no es una fecha válida. |
| `E-078` | Error en el parámetro charge_date: la fecha debe ser igual o mayor al día de hoy. |
| `E-085` | Error en el parámetro internal_code. |
| `E-086` | El internal_code ya ha sido utilizado para autorizar un cargo |
| `E-087` | Ha superado el máximo de cargos mensuales permitidos. |
| `E-112` | El plan id $plan_id no está activo. |
| `E-113` | El plan id $plan_id no es de tipo MONTO_VARIABLE. |

### Consideraciones

- `charge_date` ≥ hoy (`E-078`), formato `YYYY-MM-DD`.
- `internal_code` funciona como **llave de idempotencia**: `E-086` = "El internal_code ya ha sido utilizado para autorizar un cargo". Úsalo siempre (ej. `<socio>-<periodo>`).
- Por los mensajes `E-112`/`E-113`, se infiere que exige plan activo y de tipo `MONTO_VARIABLE` (relación inferida desde el catálogo de errores).
- **Nota sandbox 2026-10-27:** [CLAIM:VP-C05] la inferencia anterior **no se observó**. `POST /v3/charge` fue aceptado sobre una suscripción activa de plan `MONTO_FIJO` (cargo `pendiente`, luego cancelado; no apareció E-113). El mensaje oficial de E-113 se conserva arriba sin cambios. Límites y pendientes en [VALIDATION-PLAN.md](../VALIDATION-PLAN.md) (V-5). Falta confirmar en producción.
- Límite mensual de cargos (`E-087`).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C07] (DRIFT): `internal_code` **no** es idempotente. Dos `POST /v3/charge` con el mismo `internal_code` crearon dos cargos (HTTP 200, sin E-086). La afirmación de arriba sobre la llave de idempotencia queda contradicha por esta prueba. El CRM debe deduplicar consultando los cargos de la suscripción antes de crear.
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C21] (DRIFT): E-078 (`charge_date` pasada) llega con HTTP 200 y cuerpo `{"status":"NOK","code":400,"error":{...}}`, no con HTTP 400. Ver [errors.md](errors.md#objeto-error).

### Ejemplo práctico

El día 1 de cada mes, tu job crea un cargo por socio con monto variable usando `internal_code = <id_socio>-<YYYYMM>`.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/charge
```

---

## Crear un Charge Online

> Fuente oficial: [Crear un Charge Online](https://virtualpos.readme.io/reference/crear-un-charge-online)

### Endpoint

```http
POST /v3/charge/online
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Crea un cargo inmediato (sin `charge_date`) sobre la tarjeta tokenizada de una suscripción.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

No aplica.

### Query parameters

No aplica.

### Request body

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| amount | number (float) | Sí | Monto a cargar |
| description | string | Sí | Descripción asociada al cargo. |
| suscription_id | string | Sí | Identificador de la suscripción |
| internal_code | string | No | Identificador del servicio. |

Ejemplo:

```json
{
  "suscription_id": "3a4d77f2e4",
  "amount": 5000,
  "description": "Aporte extraordinario campaña invierno",
  "internal_code": "EXTRA-2026-07-000123"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "suscription_id": "3a4d77f2e4",
  "charge": {
    "id": "id_2566645567e51ef2b7.76832273",
    "charge_date": "2023-05-08",
    "amount": 9900,
    "status": "pendiente",
    "description": "Cargo 1 de 3",
    "created_at": "2021-09-08 11:20:31"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `charge.id` | ID del cargo. |
| `charge.status` | En el ejemplo oficial: `pendiente`. Consulta *Recuperar Charge* para el resultado final. |

### Estados posibles

Igual que *Crear Charge*.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-050` | Error en el parámetro suscription_id. |
| `E-055` | Error en el parámetro amount(Decimal). |
| `E-060` | No existe una suscripción ACTIVA para este charge_id: $charge_id |
| `E-085` | Error en el parámetro internal_code. |
| `E-086` | El internal_code ya ha sido utilizado para autorizar un cargo |
| `E-087` | Ha superado el máximo de cargos mensuales permitidos. |
| `E-112` | El plan id $plan_id no está activo. |
| `E-113` | El plan id $plan_id no es de tipo MONTO_VARIABLE. |
| `E-114` | El plan id $plan_id posee cargos de activación. |
| `E-116` | El plan id $plan_id posee divisa en UF. |

### Consideraciones

- La ficha no tiene descripción; el comportamiento ("cobro inmediato") se infiere del nombre y de la ausencia de `charge_date`. No confirmado en la documentación oficial de VirtualPOS.
- Por los mensajes del catálogo (`E-113`, `E-114`, `E-116`) parece requerir plan `MONTO_VARIABLE`, sin cargos de activación y en CLP (relación inferida).
- La respuesta de ejemplo no trae el Payment: obtén el resultado con *Recuperar Charge*.

### Ejemplo práctico

Un socio quiere aportar un extra hoy con su tarjeta inscrita → `POST /v3/charge/online` → consulta el cargo.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/charge/online
```

---

## Recuperar Charge

> Fuente oficial: [Recuperar Charge](https://virtualpos.readme.io/reference/recuperar-charge)

### Endpoint

```http
GET /v3/charge/{charge_id}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Obtiene un cargo por su ID.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| charge_id | string | Sí | ID del cargo (ej. `cid_2566645567e51ef2b7.76832273`). Se obtiene en `charge.id` o en `charge_program[].id`. |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "suscription_id": "3a4d77f2e4",
  "charge": {
    "id": "cid_2566645567e51ef2b7.76832273",
    "charge_date": "2023-05-08",
    "amount": 9900,
    "status": "pendiente",
    "description": "Cargo 1 de 3",
    "created_at": "2021-09-08 11:20:31"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `charge.status` | Estado del cargo. |
| `charge.charge_date / amount` | Fecha y monto. |
| `charge.payment` | Según el [Objeto Charge](#objeto-charge), un cargo cobrado incluye el `payment` (con `order.uuid`). El ejemplo del endpoint no lo muestra. |

### Estados posibles

`pendiente`, `procesando`, `pagado`, `rechazado`, `cancelado`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-056` | Error en el parámetro charge_id. |
| `E-057` | No existe el cargo asociado al id informado : $cid |
| `E-080` | Fallido obtención de objeto cargo. |

### Consideraciones

- `charge_id` contiene un punto (`cid_xxx.yyy`): no lo uses directamente como nombre de columna/clave sin escapar.
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C28] (CONFIRMADO): el detalle (`GET /v3/charge/{id}`) trae `internal_code`. Campos observados: amount, charge_date, created_at, description, id, internal_code, status.

### Ejemplo práctico

Después de un *Charge Online*, consulta cada pocos minutos hasta que salga de `pendiente`/`procesando`.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/charge/{{charge_id}}
```

---

## Cancelar Charge

> Fuente oficial: [Cancelar Charge](https://virtualpos.readme.io/reference/cancelar-charge)

### Endpoint

```http
DELETE /v3/charge/{charge_id}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Cancela un cargo pendiente específico (no afecta la suscripción ni otros cargos).

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| charge_id | string | Sí | ID del cargo (ej. `cid_2566645567e51ef2b7.76832273`). Se obtiene en `charge.id` o en `charge_program[].id`. |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "suscription_id": "3a4d77f2e4",
  "charge": {
    "id": "cid_2566645567e51ef2b7.76832273",
    "charge_date": "2023-05-08",
    "amount": 9900,
    "status": "cancelado",
    "description": "Cargo 1 de 3",
    "created_at": "2021-09-08 11:20:31"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `charge.status` | `cancelado`. |

### Estados posibles

`pendiente` → `cancelado`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-056` | Error en el parámetro charge_id. |
| `E-057` | No existe el cargo asociado al id informado : $cid |
| `E-059` | No existe un cargo pendiente para el charge_id informado: $charge_id |

### Consideraciones

- Solo cargos pendientes (`E-059`).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C12] (DRIFT): E-059 (cargo no pendiente) llega con HTTP 200 y cuerpo `{"status":"NOK","code":400,"error":{...}}`, no con HTTP 400. Borrar un `charge_id` inexistente devuelve E-058 ("No existe el plan asociado al charge_id"), también con HTTP 200 (hallazgo adicional del informe, sin ID de afirmación).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C09] (CONFIRMADO): `DELETE /v3/charge/{id}` funciona con la firma documentada (solo `api_key`).

### Ejemplo práctico

Socio pide saltarse el aporte de este mes: cancela solo ese cargo.

Request en Postman (colección `VirtualPOS API v2`):

```http
DELETE {{base_url}}/v3/charge/{{charge_id}}
```

---

## Reintentar Charge

> Fuente oficial: [Reintentar Charge](https://virtualpos.readme.io/reference/reintentar-charge)

### Endpoint

```http
GET /v3/charge/{charge_id}/retry
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Reintenta un cargo **rechazado**: VirtualPOS hace un intento diario durante 3 días seguidos; si ninguno se aprueba, queda definitivamente rechazado.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| charge_id | string | Sí | ID del cargo (ej. `cid_2566645567e51ef2b7.76832273`). Se obtiene en `charge.id` o en `charge_program[].id`. |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "message": "Se realiza el reintento de cobro del cargo cid_28836166df68afb3400.8234682 satisfactoriamente"
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-081",
    "message": "El cargo no cumple con las condiciones para realizar el reintento de cobro.",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `message` | Confirmación de que se programó el reintento. |

### Estados posibles

`rechazado` → (reintentos) → `pagado` | `rechazado` definitivo.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-056` | Error en el parámetro charge_id. |
| `E-080` | Fallido obtención de objeto cargo. |
| `E-081` | El cargo no cumple con las condiciones para realizar el reintento de cobro. |

### Consideraciones

- Es un `GET` que **cambia estado** (no es idempotente aunque sea GET). No lo llames en reintentos automáticos de red sin control.
- `E-081` si el cargo no cumple condiciones (ej. no está rechazado).

### Ejemplo práctico

Después de que el socio cambia su tarjeta (link de cambio), reintenta los cargos rechazados del mes.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/charge/{{charge_id}}/retry
```

---

## Cancelar Cargos Futuros

> Fuente oficial: [Cancelar Cargos Futuros](https://virtualpos.readme.io/reference/cancelar-cargos-futuros)

### Endpoint

```http
DELETE /v3/charges/{suscription_id}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Cancela todos los cargos pendientes de una suscripción, sin cancelar la suscripción.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| suscription_id | string | Sí | ID de la suscripción (ej. `3a4d77f2e4`). Se obtiene en `suscription.id`. |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "suscription_id": "3a4d77f2e4",
  "cancel_charges": [
    {
      "id": "cid_277465401c94d7c204.11701242",
      "charge_date": "2023-10-30",
      "amount": 9,
      "status": "cancelado",
      "description": "Cargo 1 de 12",
      "created_at": "2023-10-30 18:13:56",
      "internal_code": ""
    },
    {
      "id": "cid_277465401c94d97597.84080436",
      "charge_date": "2023-11-30",
      "amount": 9,
      "status": "cancelado",
      "description": "Cargo 2 de 12",
      "created_at": "2023-10-30 18:13:56",
      "internal_code": ""
    }
  ]
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `cancel_charges[]` | Cargos que quedaron `cancelado`. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-050` | Error en el parámetro suscription_id. |
| `E-079` | No se encontraron cargos pendientes asociados a la suscripcion. |

### Consideraciones

- Ojo con la ruta: es `/v3/charges/{suscription_id}` (**plural** `charges` + ID de **suscripción**).
- La suscripción sigue `ACTIVA`: podrías crear cargos nuevos después (planes variables).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C11] (DRIFT): E-079 (sin cargos pendientes) llega con HTTP 200 y cuerpo `status: NOK`, no con HTTP 400.

### Ejemplo práctico

Reprogramación: cancelas los cargos futuros y creas un nuevo calendario con *Crear Charge*.

Request en Postman (colección `VirtualPOS API v2`):

```http
DELETE {{base_url}}/v3/charges/{{suscription_id}}
```

---

## Listar Charges

> Fuente oficial: [Listar Charges](https://virtualpos.readme.io/reference/listar-charges)

### Endpoint

```http
GET /v3/suscription/{suscription_id}/charges
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Lista los cargos de una suscripción con filtro por estado. Soporta paginación.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| suscription_id | string | Sí | ID de la suscripción (ej. `3a4d77f2e4`). Se obtiene en `suscription.id`. |

### Query parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| status | string | No | Estado del objeto charge Valores: `pendiente`, `pagado`, `cancelado`, `procesando`, `rechazado` |
| page | integer | No | Página solicitada. Documentado en la página *Paginación*, no en la ficha del endpoint. |
| limit | integer | No | Registros por página. Mínimo 1, máximo 100 (según *Paginación*). |
| charge_date_from | string (YYYY-MM-DD) | No | ⚠️ **No declarado** en la ficha. Aparece solo en los errores `E-093`/`E-095`. No confirmado en la documentación oficial de VirtualPOS. |
| charge_date_to | string (YYYY-MM-DD) | No | ⚠️ **No declarado** en la ficha. Aparece solo en los errores `E-094`/`E-095`. No confirmado en la documentación oficial de VirtualPOS. |

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "pagination": {
    "limit": 1,
    "page": 1,
    "pages": 2,
    "total": 6
  },
  "suscription_id": "3a4d77f2e4",
  "charges": [
    {
      "id": "cid_2566645567e51ef2b7.76832273",
      "charge_date": "2023-05-08",
      "amount": 9900,
      "status": "pendiente",
      "description": "Cargo 1 de 3",
      "created_at": "2021-09-08 11:20:31"
    },
    {
      "id": "cid_7273457723bb3.94487839",
      "charge_date": "2023-06-08",
      "amount": 9900,
      "status": "pendiente",
      "description": "Cargo 2 de 3",
      "created_at": "2021-09-08 11:20:31"
    },
    {
      "id": "cid_99383327567e51ef2b8.83782272",
      "charge_date": "2023-07-08",
      "amount": 9900,
      "status": "pendiente",
      "description": "Cargo 3 de 3",
      "created_at": "2021-09-08 11:20:31"
    }
  ]
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `charges[]` | Cargos: `id`, `charge_date`, `amount`, `status`, `description`, `created_at`. |
| `suscription_id` | Suscripción consultada. |
| `pagination` | `limit`, `page`, `pages`, `total`. |

### Estados posibles

`pendiente`, `pagado`, `cancelado`, `procesando`, `rechazado`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-050` | Error en el parámetro suscription_id. |
| `E-090` | Error en el parámetro page. |
| `E-091` | Error en el parámetro limit. |
| `E-092` | Error en el parámetro status. |
| `E-093` | Error en el parámetro charge_date_from. Debe ser YYYY-MM-DD |
| `E-094` | Error en el parámetro charge_date_to. Debe ser YYYY-MM-DD |
| `E-095` | Error en el parámetro charge_date_to. Debe ser mayor o igual a charge_date_to |

### Consideraciones

- Es **por suscripción**: no existe un "listar todos los cargos del comercio". Para un barrido global: suscripciones → cargos de cada una (N+1 llamadas).
- Alternativa más barata para cargos **cobrados**: abonos diarios (`/v3/deposit/{date}/sales` trae `suscription_charge.cid`).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C13] (CONFIRMADO): `status=pendiente` devuelve solo cargos pendientes (no incluyó cancelados y sí incluyó el pendiente de prueba).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C26] (DRIFT): `charge_date_from` y `charge_date_to` se ignoran; devuelve todos los cargos (18 de 18, igual que sin filtro).
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C19] (PARCIAL): en el listado `amount` es número entero (no string); `charge_date` es `YYYY-MM-DD`; el `id` es string con prefijo `cid_`.
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C28] (CONFIRMADO): `internal_code` aparece en el listado de cargos y en el detalle. No viene en `charge_program[]` del listado de suscripciones (ver [subscriptions.md](subscriptions.md)).

### Ejemplo práctico

Sincronización: por cada suscripción activa, `GET /v3/suscription/{id}/charges?limit=100&page=1`.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/suscription/{{suscription_id}}/charges
```

---
