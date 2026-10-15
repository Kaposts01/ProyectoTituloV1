# Clients

> Fuente: https://virtualpos.readme.io/reference/objeto-client · Verificado: 2026-10-12

El **Client** representa al cliente final (persona o empresa) del comercio, con sus datos de identificación y contacto.

> ⚠️ **Relación con otros recursos no documentada.** Ni Payment ni Suscription reciben ni devuelven el `uuid` del Client: se relacionan solo por `email` / `social_id`. Para tu base central, usa el RUT normalizado como llave de unión. No confirmado en la documentación oficial de VirtualPOS.

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `POST` | `/v3/client` | [Crear un Client](#crear-un-client) |
| `GET` | `/v3/client/{uuid}` | [Recuperar un objeto Client](#recuperar-un-objeto-client) |
| `GET` | `/v3/clients` | [Listar objetos Client](#listar-objetos-client) |
| `PUT` | `/v3/client/{uuid}` | [Actualizar un objeto Client](#actualizar-un-objeto-client) |

## Objeto Client

```json
{
  "client": {
    "uuid": "cli_0316825ee546f8d9",
    "type": "PERSONA",
    "first_name": "John",
    "last_name": "Doe",
    "social_id_type": 1,
    "social_id": "18271783-1",
    "email": "john@doe.cl",
    "phone_number": "912345678",
    "status": "ACTIVO",
    "gender_id": "Masculino",
    "birth_date": "1989-12-01",
    "created": "2025-05-15 09:38:28"
  }
}
```

| Atributo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| `uuid` | string | Solo respuesta | `cli_<alfanumérico>` |
| `status` | enum | Opcional (default `ACTIVO`) | `ACTIVO`, `BLOQUEADO` |
| `type` | enum | **Sí** | `PERSONA`, `EMPRESA` |
| `first_name` | string | **Sí** | Nombre o razón social |
| `last_name` | string | Condicional | Requerido si `PERSONA` |
| `email` | string | **Sí** | Único por comercio |
| `phone_number` | string | No | Teléfono |
| `social_id_type` | enum | No | `1` RUT, `2` DNI (si es RUT se valida formato) |
| `social_id` | string | No | RUT o DNI, único por comercio |
| `birth_date` | date | No | `YYYY-MM-DD` |
| `gender_id` | enum | No | `1` Masculino, `2` Femenino, `4` Otro |
| `private_note` | string | No | Nota interna |
| `created` / `updated` | datetime | Solo respuesta | Gestionados por el sistema |

---

## Crear un Client

> Fuente oficial: [Crear un Client](https://virtualpos.readme.io/reference/crear-un-client)

### Endpoint

```http
POST /v3/client
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Crea un cliente (persona o empresa) asociado al comercio.

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
| type | string | Sí | PERSONA o EMPRESA Valores: `PERSONA`, `EMPRESA` |
| social_id | string | No | Número de documento asociado a social_id_type. Debe ser único. |
| first_name | string | Sí | Nombre del cliente (o razón social si es type = EMPRESA) |
| last_name | string | No | Obligatorio cuando es type = PERSONA. Opcional para EMPRESA |
| email | string | Sí | Email del cliente. Debe ser único y con formato válido |
| phone_number | string | No | Teléfono del cliente. |
| social_id_type | string | No | 1 si es RUT o 2 si es DNI. Si es RUT se valida el formato. |
| birth_date | string (date) | No | Fecha de nacimiento YYYY-MMDD |
| gender_id | string | No | 1 para Masculino, 2 Femenino o 4 para Otro Valores: `Masculino`, `Femenino`, `Otro` |
| private_note | string | No | Nota interna del comercio. |

Ejemplo:

```json
{
  "type": "PERSONA",
  "first_name": "John",
  "last_name": "Doe",
  "email": "user@example.com",
  "phone_number": "56961934502",
  "social_id_type": 1,
  "social_id": "12345678-9",
  "birth_date": "1990-01-01",
  "gender_id": 1,
  "private_note": "Socio desde campaña invierno"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "client": {
    "uuid": "cli_00183af742e91dc3",
    "status": "ACTIVO",
    "type": "PERSONA",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "phone_number": "56961934502",
    "social_id_type": "RUT",
    "social_id": "12345678-9",
    "birth_date": "1990-01-01",
    "gender_id": "Masculino",
    "private_note": "Cliente recurrente de suscripciones de seguros.",
    "created": "2025-01-08 11:20:31",
    "updated": "2025-01-08 11:20:31"
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `client.uuid` | ID del cliente (`cli_...`). Guárdalo. |
| `client.status` | `ACTIVO` por defecto. |
| `client.social_id_type / gender_id` | En la respuesta vuelven como texto (`RUT`, `Masculino`). |

### Estados posibles

`ACTIVO` / `BLOQUEADO`.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-004` | Error en el parámetro email. |
| `E-005` | Error en el parámetro social_id. |
| `E-006` | Error en el parámetro first_name. |
| `E-007` | Error en el parámetro last_name. |
| `E-012` | Error en el parámetro email, no cumple con formato. |
| `E-083` | Este cliente ya existe. |
| `E-084` | Error en el parámetro social_id. No cumple con el formato. |
| `E-102` | El campo first_name solo puede contener letras y espacios. |
| `E-103` | El campo last_name solo puede contener letras y espacios. |

### Consideraciones

- `email` y `social_id` son **únicos por comercio** → `E-083` "Este cliente ya existe". Antes de crear, busca con `GET /v3/clients?social_id=...` (upsert manual).
- `last_name` obligatorio si `type = PERSONA`.
- **Discrepancia de tipos:** la OpenAPI tipa `social_id_type` y `gender_id` como string (y `gender_id` con enum de texto `'Masculino'…`), pero su descripción dice `1`/`2`/`4`. En tus pruebas funcionó con **números**: `social_id_type: 1`, `gender_id: 1`.
- `birth_date`: la descripción dice `YYYY-MMDD` (errata); usa `YYYY-MM-DD`.
- La relación Client ↔ Suscription **no está documentada**: la suscripción no recibe `client_uuid`, solo email/RUT. No confirmado en la documentación oficial de VirtualPOS.

### Ejemplo práctico

Alta de socio: busca por RUT → si no existe, crea el Client → guarda `cli_...` junto al socio.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/client
```

---

## Recuperar un objeto Client

> Fuente oficial: [Recuperar un objeto Client](https://virtualpos.readme.io/reference/recuperar-un-objeto-client)

### Endpoint

```http
GET /v3/client/{uuid}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Obtiene un cliente por su `uuid`.

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
| uuid | string | Sí | UUID del cliente (ej. `cli_00183af742e91dc3`). ⚠️ La OpenAPI oficial lo declara como *query*, pero la ruta es `/v3/client/{uuid}`: se envía en el path. |

### Query parameters

No aplica.

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "client": {
    "uuid": "cli_00183af742e91dc3",
    "status": "ACTIVO",
    "type": "PERSONA",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "phone_number": "56961934502",
    "social_id_type": "RUT",
    "social_id": "12345678-9",
    "birth_date": "1990-01-01",
    "gender_id": "Masculino",
    "private_note": "Cliente recurrente de suscripciones de seguros.",
    "created": "2025-01-08 11:20:31",
    "updated": "2025-01-10 09:15:00"
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `client` | Objeto Client completo, incluye `updated`. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-082` | Error no existen cliente asociado al comercio. |

### Consideraciones

- Las respuestas de Client **no** traen el envoltorio `status`/`code` en el ejemplo 200 (a diferencia del resto de la API).

### Ejemplo práctico

Refrescar datos de contacto antes de enviar una campaña.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/client/{{client_uuid}}
```

---

## Listar objetos Client

> Fuente oficial: [Listar objetos Client](https://virtualpos.readme.io/reference/listar-objetos-client)

### Endpoint

```http
GET /v3/clients
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Lista clientes con filtros por estado, tipo, documento, email y fecha de creación. Orden por defecto: `created` descendente.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>"}`. Ver [authentication.md](authentication.md).

### Path parameters

No aplica.

### Query parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| page | integer (int32) | No | Página a recuperar. Default: `1` |
| limit | integer (int32) | No | Cantidad de registros por página. Default: `100` |
| status | string | No | Filtra por estado del cliente: ACTIVO, BLOQUEADO. Valores: `ACTIVO`, `BLOQUEADO` Default: `all` |
| type | string | No | Filtra por tipo de cliente: PERSONA, EMPRESA. Valores: `PERSONA`, `EMPRESA` |
| social_id | string | No | Filtra por documento. |
| email | string | No | Fitra por email. |
| created_from | string (date) | No | Filtra clientes creados desde esta fecha (inclusive). |
| created_to | string (date) | No | Filtra clientes creados hasta esta fecha (inclusive). |

### Request body

No aplica (sin body).

### Response

**HTTP 200** (éxito):

```json
{
  "clients": [
    {
      "uuid": "cli_00183af742e91dc3",
      "status": "ACTIVO",
      "type": "PERSONA",
      "first_name": "John",
      "last_name": "Doe",
      "email": "user@example.com",
      "phone_number": "56961934502",
      "social_id_type": "RUT",
      "social_id": "12345678-9",
      "birth_date": "1990-01-01",
      "gender_id": "Masculino",
      "created": "2025-01-08 11:20:31",
      "updated": "2025-01-10 09:15:00"
    },
    {
      "uuid": "cli_00183af742e91dc4",
      "status": "BLOQUEADO",
      "type": "EMPRESA",
      "first_name": "Acme S.A.",
      "last_name": "",
      "email": "user2@example.com",
      "phone_number": "56223456789",
      "social_id_type": "RUT",
      "social_id": "76432154-2",
      "birth_date": “”,
      "gender_id": “”,
      "created": "2025-01-01 09:00:00",
      "updated": "2025-01-05 10:00:00"
    }
  ],
  "page": 1,
  "limit": 100,
  "total": 2
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `clients[]` | Arreglo de clientes. |
| `page / limit / total` | ⚠️ Paginación **distinta** al resto: campos en la raíz, sin objeto `pagination` y sin `pages` → calcula `pages = ceil(total / limit)`. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-082` | Error no existen cliente asociado al comercio. |
| `E-090` | Error en el parámetro page. |
| `E-091` | Error en el parámetro limit. |
| `E-092` | Error en el parámetro status. |

### Consideraciones

- `limit` default 100, `page` default 1.
- `status` default `all` según la OpenAPI (aunque el enum solo lista `ACTIVO`/`BLOQUEADO`).
- Filtrar por `social_id` o `email` es la forma de "buscar un cliente" (no hay endpoint de búsqueda aparte).
- No hay filtro `updated_from`: para detectar cambios hay que releer todo o comparar `updated`.
- En el ejemplo oficial hay comillas tipográficas (`“”`) que lo hacen JSON inválido: es un error del ejemplo, no de la API.

### Ejemplo práctico

`GET /v3/clients?social_id=12345678-9` para saber si el socio ya existe antes de crearlo.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/clients
```

---

## Actualizar un objeto Client

> Fuente oficial: [Actualizar un objeto Client](https://virtualpos.readme.io/reference/actualizar-un-objeto-client)

### Endpoint

```http
PUT /v3/client/{uuid}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Actualiza parcialmente un cliente: solo cambian los campos enviados.

### Autenticación

| Header | Valor |
| --- | --- |
| Content-Type | `application/json` |
| Authorization | `<API_KEY>` |
| Signature | JWT HS256 firmado con la `SECRET_KEY` |

Payload del JWT: `{"api_key": "<API_KEY>", ...atributos del body}` según la doc oficial ("junto con los atributos requeridos"). En sandbox también funcionó firmar solo `{api_key}`. Ver [authentication.md](authentication.md).

### Path parameters

| Nombre | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| uuid | string | Sí | UUID del cliente (ej. `cli_00183af742e91dc3`). ⚠️ La OpenAPI oficial lo declara como *query*, pero la ruta es `/v3/client/{uuid}`: se envía en el path. |

### Query parameters

No aplica.

### Request body

Ejemplo:

```json
{
  "client": {
    "status": "BLOQUEADO",
    "phone_number": "56977777777",
    "private_note": "Cliente bloqueado por mora.",
    "email": "user@example.com"
  }
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "client": {
    "uuid": "cli_00183af742e91dc3",
    "status": "BLOQUEADO",
    "type": "PERSONA",
    "first_name": "John",
    "last_name": "Doe",
    "email": "user@example.com",
    "phone_number": "56977777777",
    "social_id_type": "RUT",
    "social_id": "12345678-9",
    "birth_date": "1990-01-01",
    "gender_id": "Masculino",
    "private_note": "Cliente bloqueado por mora.",
    "created": "2025-01-08 11:20:31",
    "updated": "2025-01-15 10:30:00"
  }
}
```

**HTTP 400** (error):

```json
{
  "status": "NOK",
  "code": 400,
  "error": {
    "error_code": "E-###",
    "message": "detalle del error",
    "doc_url": "https://virtualpos.readme.io/reference/objeto-error"
  }
}
```

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `client` | Cliente actualizado; `updated` cambia automáticamente. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-004` | Error en el parámetro email. |
| `E-012` | Error en el parámetro email, no cumple con formato. |
| `E-083` | Este cliente ya existe. |
| `E-084` | Error en el parámetro social_id. No cumple con el formato. |

### Consideraciones

- **Ojo con el body:** el ejemplo oficial envuelve los campos en `{"client": {...}}`, pero el schema está vacío. Tu colección enviaba los campos en la raíz. Prueba ambos en sandbox y documenta el que funcione. No confirmado en la documentación oficial de VirtualPOS.
- No se pueden modificar `uuid` ni `created`.
- Se re-validan formato de email y unicidad de `email`/`social_id`.
- Para bloquear un cliente: `status: BLOQUEADO`.

### Ejemplo práctico

El socio cambia su teléfono en tu portal → `PUT /v3/client/{uuid}` con solo `phone_number`.

Request en Postman (colección `VirtualPOS API v2`):

```http
PUT {{base_url}}/v3/client/{{client_uuid}}
```

---
