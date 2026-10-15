# Plans

> Fuente: https://virtualpos.readme.io/reference/objeto-plan · Verificado: 2026-10-12

Un **Plan** define las reglas de un cobro recurrente: monto, moneda (CLP o UF), frecuencia, número de cobros y día del cobro. Toda **Suscription** pertenece a un plan.

| Tipo | Uso |
| --- | --- |
| `MONTO_FIJO` | Monto fijo y número de cobros fijo (ej. $10.000 × 12 meses). |
| `MONTO_VARIABLE` | El comercio informa cada monto con *Crear Charge* (ej. consumo). |
| `PROGRAMA_DE_PAGOS` | Serie de cobros con montos distintos; se envía en `charges_program` al suscribir. |

## Endpoints de este recurso

| Método | Ruta | Operación |
| --- | --- | --- |
| `POST` | `/v3/plan` | [Crear un Plan](#crear-un-plan) |
| `GET` | `/v3/plan/{plan_id}` | [Recuperar un Plan](#recuperar-un-plan) |
| `GET` | `/v3/plans` | [Listar plans](#listar-plans) |

## Objeto Plan

```json
{
  "plan": {
    "id": "fd53ead26f78b56113312609b668411b",
    "name": "Seguro automotriz",
    "description": "Asegura tu vehiculo",
    "is_active": "T",
    "amount": 9990,
    "currency": "CLP",
    "trial_days": 0,
    "num_charges": 12,
    "frequency_type": "Mensual",
    "return_url": "https://www.misitio.com",
    "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258",
    "type": "MONTO_FIJO",
    "fixed_amount_day_charge": "05",
    "automatic_renewal": "T",
    "show_in_terminal": "F",
    "created_at": "2023-05-15 23:15:00",
    "shipping_address": "F"
  }
}
```

| Atributo | Tipo | Descripción |
| --- | --- | --- |
| `id` | String | Identificador único del plan |
| `name` | String | Nombre del plan |
| `description` | String | Descripción |
| `is_active` | enum | `T` activo / `F` no activo |
| `amount` | float | Monto o precio del plan |
| `currency` | enum | `CLP`, `UF` |
| `trial_days` | Integer | Días sin cobro |
| `num_charges` | Integer | Cantidad de cobros |
| `frequency_type` | enum | La tabla oficial lista Diario, Semanal, Mensual, Semestral, Anual (el enum de *Crear Plan* solo Diario/Semanal/Mensual) |
| `return_url` | String | Retorno cuando se suscribe vía formulario VirtualPOS |
| `suscription_url` | String | Formulario de suscripción hospedado por VirtualPOS |
| `type` | enum | `MONTO_FIJO`, `MONTO_VARIABLE`, `PROGRAMA_DE_PAGOS` |
| `fixed_amount_day_charge` | enum | Día del cobro: `0`,`01`,`05`,`10`,`15`,`20`,`25`,`28`,`30`. `0` = en el momento de suscribir |
| `show_in_terminal` | enum | Disponible en SmartPOS (`T`/`F`) |
| `automatic_renewal` | enum | Renovación automática al terminar (`T`/`F`) |
| `created_at` | datetime | Fecha de creación |
| `shipping_address` | enum | Requiere dirección de despacho (`T`/`F`), opcional |

---

## Crear un Plan

> Fuente oficial: [Crear un Plan](https://virtualpos.readme.io/reference/crear-un-plan)

### Endpoint

```http
POST /v3/plan
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Crea un plan de cobro recurrente: monto, moneda, frecuencia, cantidad de cobros y día de cobro. Toda suscripción se crea contra un plan.

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
| name | string | Sí | Nombre del plan recurrente |
| description | string | Sí | Descripción del plan recurrente |
| type | string | No | Tipo de plan Valores: `MONTO_FIJO`, `MONTO_VARIABLE`, `PROGRAMA_DE_PAGOS` |
| currency | string | Sí | Moneda utilizada Valores: `CLP`, `UF` |
| amount | number (float) | No | Monto fijo |
| trial_days | integer (int32) | No |  |
| num_charges | integer (int32) | No |  |
| frequency_type | string | No | Frecuencia de los cobros Valores: `Diario`, `Semanal`, `Mensual` |
| fixed_amount_day_charge | string | No | Valores: `0`, `01`, `05`, `10`, `15`, `20`, `25`, `28`, `30` |
| return_url | string | No | URL de su aplicación a la cual se retornará una vez que se haya finalizado la suscripción. En esta URL se deberá ejecutar la consulta del resultado de suscripción, ya que por motivos de seguridad la respuesta no se entrega en forma directa a la URL de retorno |
| automatic_renewal | string | No | Flag de renovación automática. Valores: `T`, `F` Default: `F` |
| show_in_terminal | string | No | Flag para visualización en SmartPOS Valores: `T`, `F` Default: `F` |
| shipping_address | string | No | Flag para indicar que requiere direcciones de despacho. Valores: `T`, `F` |

Ejemplo:

```json
{
  "name": "Socio Mensual",
  "description": "Aporte mensual Techo",
  "type": "MONTO_FIJO",
  "currency": "CLP",
  "amount": 10000,
  "trial_days": 0,
  "num_charges": 12,
  "frequency_type": "Mensual",
  "fixed_amount_day_charge": "05",
  "return_url": "https://www.misitio.cl/suscripcion/resultado",
  "automatic_renewal": "T",
  "show_in_terminal": "F",
  "shipping_address": "F"
}
```

### Response

**HTTP 200** (éxito):

```json
{
  "status": "OK",
  "code": 200,
  "plan": {
    "id": "fd53ead26f78b56113312609b668411b",
    "name": "Seguro automotriz",
    "description": "Asegura tu vehiculo",
    "is_active": "T",
    "amount": 9990,
    "currency": "CLP",
    "trial_days": 0,
    "num_charges": 12,
    "frequency_type": "Mensual",
    "return_url": "https://www.misitio.com",
    "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258",
    "type": "MONTO_FIJO",
    "fixed_amount_day_charge": "05",
    "automatic_renewal": "T",
    "show_in_terminal": "F",
    "created_at": "2023-05-15 23:15:00",
    "shipping_address": "F"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `plan.id` | ID del plan → `plan_id` al crear suscripciones. |
| `plan.suscription_url` | Formulario de suscripción hospedado por VirtualPOS para este plan (alternativa sin integración). |
| `plan.is_active` | `T`/`F`. |

### Estados posibles

`is_active`: `T` (activo) / `F` (no activo). Un plan inactivo da `E-112` al cobrar.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-061` | Error en el parámetro name. |
| `E-062` | Error en el parámetro currency. |
| `E-063` | Error en el parámetro trial_days. |
| `E-064` | Error en el parámetro num_charges. |
| `E-065` | Error en el parámetro frequency_type. |

### Consideraciones

- Tipos: `MONTO_FIJO` (monto y número de cobros fijos), `MONTO_VARIABLE` (el comercio informa cada cargo con *Crear Charge*), `PROGRAMA_DE_PAGOS` (lista de cobros con montos distintos, se envía en `charges_program` al suscribir).
- `fixed_amount_day_charge`: día del mes del cobro (`0` = cobra en el momento de la suscripción).
- La tabla del Objeto Plan menciona frecuencias `Semestral` y `Anual`, pero el enum de *Crear Plan* solo acepta `Diario`, `Semanal`, `Mensual`.
- No hay endpoints documentados para **editar ni eliminar** planes. No confirmado en la documentación oficial de VirtualPOS.
- `return_url` aquí va en texto plano (la doc no pide Base64 para este campo, a diferencia de Payment/Suscription).

### Ejemplo práctico

Crea una vez los planes de socios (ej. $5.000, $10.000, $20.000 mensuales) y guarda sus `plan.id` en tu configuración.

Request en Postman (colección `VirtualPOS API v2`):

```http
POST {{base_url}}/v3/plan
```

---

## Recuperar un Plan

> Fuente oficial: [Recuperar un Plan](https://virtualpos.readme.io/reference/recuperar-un-plan)

### Endpoint

```http
GET /v3/plan/{plan_id}
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Obtiene la definición de un plan por su ID.

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
| plan_id | string | Sí | ID del plan (ej. `fd53ead26f78b56113312609b668411b`). Se obtiene en `plan.id`. |

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
  "plan": {
    "id": "fd53ead26f78b56113312609b668411b",
    "name": "Seguro automotriz",
    "description": "Asegura tu vehiculo",
    "is_active": "T",
    "amount": 9990,
    "currency": "CLP",
    "trial_days": 0,
    "num_charges": 12,
    "frequency_type": "Mensual",
    "return_url": "https://www.misitio.com",
    "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258",
    "type": "MONTO_FIJO",
    "fixed_amount_day_charge": "05",
    "automatic_renewal": "T",
    "show_in_terminal": "F",
    "created_at": "2023-05-15 23:15:00",
    "shipping_address": "F"
  }
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `plan` | Objeto Plan completo (ver tabla de atributos). |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-044` | Error en el parámetro plan_id. |
| `E-047` | No existe el plan asociado al uuid : $uuid |
| `E-067` | No se encontró información para el id_plan: $plan_id |

### Consideraciones

- El plan es casi estático: cachéalo y refréscalo una vez al día.

### Ejemplo práctico

Al mostrar una suscripción en tu panel, enriquece con nombre y frecuencia del plan.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/plan/{{plan_id}}
```

---

## Listar plans

> Fuente oficial: [Listar plans](https://virtualpos.readme.io/reference/listar-plans)

### Endpoint

```http
GET /v3/plans
```

Base URL: `https://api.virtualpos-sandbox.com` (sandbox) · `https://api.virtualpos.cl` (producción)

### Propósito

Lista los planes del comercio. Soporta paginación.

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
| page | integer | No | Página solicitada. Documentado en la página *Paginación*, no en la ficha del endpoint. |
| limit | integer | No | Registros por página. Mínimo 1, máximo 100 (según *Paginación*). |

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
  "plans": [
    {
      "id": "fd53ead26f78b56113312609b668411b",
      "name": "Seguro automotriz",
      "description": "Asegura tu vehiculo",
      "is_active": "T",
      "amount": 9990,
      "currency": "CLP",
      "trial_days": 0,
      "num_charges": 12,
      "frequency_type": "Mensual",
      "return_url": "https://www.misitio.com",
      "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/31a2b726a23ff92487984ba17e0b7258",
      "type": "MONTO_FIJO",
      "fixed_amount_day_charge": "05",
      "automatic_renewal": "T",
      "show_in_terminal": "F",
      "created_at": "2023-05-15 23:15:00",
      "shipping_address": "F"
    },
    {
      "id": "fx53ead26f78b5s113325679b66884573f",
      "name": "Seguro de vida",
      "description": "Protege a tu familia",
      "is_active": "T",
      "amount": 2.4,
      "currency": "UF",
      "trial_days": 0,
      "num_charges": 12,
      "frequency_type": "Mensual",
      "return_url": "https://www.misitio.com",
      "suscription_url": "https://pat.virtualpos.cl/suscripcion/acme-corp/56b2b726a23ff92487984ba17b0b86784",
      "type": "MONTO_FIJO",
      "fixed_amount_day_charge": "05",
      "automatic_renewal": "F",
      "show_in_terminal": "T",
      "created_at": "2023-05-25 13:55:00",
      "shipping_address": "T"
    }
  ]
}
```

**HTTP 400** — el ejemplo oficial está vacío (`{}`). Se espera el formato estándar del [Objeto Error](errors.md#objeto-error) (inferencia).

### Campos importantes

| Campo | Qué significa / para qué sirve |
| --- | --- |
| `plans[]` | Arreglo de objetos Plan. |
| `pagination` | `limit`, `page`, `pages`, `total`. |

### Estados posibles

No aplica.

### Errores

Códigos del catálogo oficial cuyo mensaje aplica a este endpoint (la ficha del endpoint no lista sus errores; la asociación es por el texto del mensaje):

| Código | Mensaje oficial |
| --- | --- |
| `E-066` | No existen planes asociados al comercio. |
| `E-090` | Error en el parámetro page. |
| `E-091` | Error en el parámetro limit. |

### Consideraciones

- No hay filtros documentados (ej. por `is_active`); filtra en tu lado.

### Ejemplo práctico

Paso 1 de la sincronización: carga todos los planes en `vpos_plans`.

Request en Postman (colección `VirtualPOS API v2`):

```http
GET {{base_url}}/v3/plans
```

---
